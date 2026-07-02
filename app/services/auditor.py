# ─────────────────────────────────────────────────────────────────────────────
# AUDITIQ — MULTI-AGENT AUDIT PIPELINE  v2.0
# ─────────────────────────────────────────────────────────────────────────────
#
# PIPELINE STAGES:
#   Stage A  →  SQL fact lookup (per-request, thread-safe)
#   Stage B  →  Speaker segmentation (debtor speech excluded from detection)
#   Stage C  →  Pre-detection (regex on AGENT text only)
#   Stage D  →  Hybrid retrieval (full transcript for recall)
#   Stage E  →  Agent 1 — Primary Auditor LLM (streamed)
#   Stage F  →  Violation ID normalization
#   Stage G  →  Agent 2 — Prompt Grader (rubric-based)
#   Stage H  →  Final result assembly
#
# EVENT TYPES (matching your existing audit.py consumer):
#   {"type": "status",   "step": "...", "message": "..."}
#   {"type": "token",    "content": "..."}
#   {"type": "complete", "result": {...}}
#   {"type": "error",    "message": "..."}
# ─────────────────────────────────────────────────────────────────────────────
import sqlite3
import json
import os
import re
import logging
from datetime import datetime
from typing   import Dict, Any, Optional, List

from app.core.config import (
    SQLITE_DB_PATH,
    llm_client,
    PRIMARY_AUDITOR_MODEL,
    VERIFIER_MODEL,
)
from app.services.hybrid_retriever  import LegalRetriever
from app.services.pre_detector      import pre_detector
from app.services.speaker_segmenter import speaker_segmenter

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

#Ensuring the logs directory exists
os.makedirs("logs", exist_ok=True)

#setting up a logger that writes to a file instead of the terminal
logger = logging.getLogger("auditor")
logger.setLevel(logging.DEBUG)

_log_file = f"logs/auditor_trace_{datetime.now().strftime('%Y%m%d')}.log"
if not logger.handlers:
    file_handler = logging.FileHandler(_log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('\n[Auditor] %(message)s'))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL RETRIEVER
# ─────────────────────────────────────────────────────────────────────────────

retriever = LegalRetriever()

# ─────────────────────────────────────────────────────────────────────────────
# VALID RULE IDs
# ─────────────────────────────────────────────────────────────────────────────

def _load_valid_rule_ids() -> List[str]:
    try:
        rules_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "rules_core.json"
        )
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)
        ids = [r["id"] for r in rules if "id" in r]
        logger.info(f"Loaded {len(ids)} valid rule IDs")
        return ids
    except Exception as e:
        logger.error(f"Could not load rules_core.json: {e}")
        return []

VALID_RULE_IDS: List[str] = _load_valid_rule_ids()

# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC PRINTER
# ─────────────────────────────────────────────────────────────────────────────

def _sep(title: str = ""):
    line = "=" * 70
    msg  = f"\n{line}\n  {title}\n{line}" if title else line
    print(msg); logger.debug(msg)

def _block(label: str, content: str):
    msg = f"\n{'─'*70}\n  {label}\n{'─'*70}\n{content}"
    print(msg); logger.debug(msg)

def _jblock(label: str, obj: Any):
    _block(label, json.dumps(obj, indent=2, default=str))

# ─────────────────────────────────────────────────────────────────────────────
# SQL FACT LOOKUP — per-request, no shared connection
# ─────────────────────────────────────────────────────────────────────────────

def _get_sql_facts(account_name: str):
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
        cur  = conn.cursor()
        cur.execute("SELECT balance, status FROM debtors WHERE name = ?", (account_name,))
        row  = cur.fetchone()
        conn.close()
        if row:
            balance, status = row
            facts = f"True Balance: ${float(balance):.2f}, Account Status: {status}."
            return facts, float(balance), str(status)
        return None, None, None
    except Exception as e:
        logger.error(f"SQL lookup error for '{account_name}': {e}")
        return None, None, None

# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL CONTEXT FORMATTER
# ─────────────────────────────────────────────────────────────────────────────

def _format_context(retrieved: List[Dict]) -> str:
    if not retrieved:
        return "No rules retrieved."
    lines = []
    for i, rule in enumerate(retrieved, 1):
        lines.append(f"--- Rule {i}: {rule['rule_id']} ---")
        lines.append(f"Citation:       {rule.get('citation', '')}")
        lines.append(f"Severity:       {rule.get('severity', '')}")
        lines.append(f"Rule Summary:   {rule.get('rule_statement', '')}")
        lines.append(f"Explanation:    {rule.get('explanation', '')}")
        violation_patterns = rule.get("violation_patterns", [])
        if violation_patterns:
            lines.append("What a violation of this rule looks like in practice:")
            for vp in violation_patterns[:5]:
                lines.append(f"  • {vp}")
        raw = rule.get("raw_federal_text", "")
        if raw:
            raw = raw[:600] + "... [truncated]" if len(raw) > 600 else raw
            lines.append(f"Raw Federal Law:\n{raw}")
        lines.append("")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_audit_prompt(formatted_transcript, sql_facts, context_string,
                         pre_block, segmentation_note, valid_rule_ids) -> str:
    if valid_rule_ids:
        id_list  = "\n".join(f"  - {rid}" for rid in valid_rule_ids)
        id_block = (
            f"VALID VIOLATION RULE IDs — use ONLY these in violations_found.\n"
            f"Do NOT use citation strings like '§ 806'. Do NOT invent IDs.\n{id_list}"
        )
    else:
        id_block = "Use the exact RULE_ID shown in each retrieved rule. Do NOT use citation strings."

    return f"""You are an elite QA Compliance Auditor for a debt collection agency.
Evaluate whether the debt collection AGENT violated the FDCPA.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — SQL ACCOUNT FACTS (Ground Truth)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sql_facts}
If the agent states a different balance → flag as § 807(2) violation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — PRE-DETECTION LAYER (Deterministic Python Analysis)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{pre_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — RETRIEVED LEGAL CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{context_string}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — CALL TRANSCRIPT (Speaker-Attributed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{formatted_transcript}
{segmentation_note}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPEAKER ATTRIBUTION RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- FDCPA ONLY regulates the [AGENT]. The [DEBTOR] may say anything.
- Do NOT flag violations based on [DEBTOR] speech — ever.
- If [DEBTOR] swears, threatens a lawyer, or says "I'll sue you" → IRRELEVANT.
- If [DEBTOR] says "you threatened to arrest me" → check [AGENT] turns to verify.
- [UNKNOWN] turns: use full context to judge before attributing violations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUDIT INSTRUCTIONS — your reasoning MUST explicitly address:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  a) Mini-Miranda (§ 807(11)): Was it stated by [AGENT]?
     If pre-detection says NOT DETECTED → confirmed omission violation.
  b) Every pre-detected flag — confirm or dispute each with transcript evidence.
  c) Balance accuracy — compare [AGENT]'s stated amount to SQL FACTS.
  d) Third-party disclosure — did [AGENT] disclose debt info to a non-consumer?
  e) What the [AGENT] did correctly — acknowledge compliant behavior.
  f) Which retrieved legal rules apply and how.

SCORING:
  10   = Fully compliant, professional, all required disclosures present
  8-9  = Minor procedural gap, no substantive violations
  5-7  = Moderate issue, borderline behavior
  2-4  = Clear violation, not automatically maximum severity
  1    = Major violation (threats, harassment, false claims, third-party disclosure)

CRITICAL RULES:
  - Only flag violations with direct evidence from [AGENT] speech.
  - "may" or "allowed" = optional. Do not penalize optional disclosures.
  - Mini-Miranda absent → compliance_passed MUST be false.
  - Any pre-detection confirmed_violation → compliance_passed MUST be false.

{id_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — ONLY this exact JSON. No markdown. No preamble.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
    "compliance_passed": boolean,
    "performance_score": integer (1-10),
    "violations_found": ["RULE_ID_FROM_LIST_ABOVE"],
    "reasoning": "Cover: (a) Mini-Miranda, (b) each pre-detected flag with evidence, (c) balance accuracy, (d) third-party disclosure if applicable, (e) what was done correctly."
}}"""

# ─────────────────────────────────────────────────────────────────────────────
# GRADER PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_grader_prompt(audit_result, pre_report, context_string,
                          transcript, sql_facts) -> str:
    pre_ids    = pre_report.get_pre_detected_rule_ids()
    mm_ok      = pre_report.mini_miranda_detected
    suspicious = [v.rule_id for v in pre_report.suspicious_patterns]

    return f"""You are a Senior FDCPA Compliance Audit Grader.
Grade the QUALITY and ACCURACY of Agent 1's audit on a structured rubric.
This is for prompt engineering evaluation — not just contradiction checking.

WHAT AGENT 1 WAS GIVEN:
  SQL FACTS: {sql_facts}
  Mini-Miranda detected: {"YES" if mm_ok else "NO — flagged as absent"}
  Confirmed violation IDs: {pre_ids if pre_ids else "None"}
  Suspicious patterns: {suspicious if suspicious else "None"}

RETRIEVED LEGAL CONTEXT:
{context_string}

TRANSCRIPT:
{transcript}

WHAT AGENT 1 PRODUCED:
{json.dumps(audit_result, indent=2)}

GRADING RUBRIC:
[A] MINI-MIRANDA HANDLING      (0-2): Correctly identified + acted on?
[B] PRE-DETECTION COVERAGE     (0-3): All flags addressed with evidence?
[C] LEGAL GROUNDING            (0-2): Citations traceable to retrieved rules?
[D] VIOLATION ID ACCURACY      (0-2): Valid IDs, correctly applied?
[E] SCORE CALIBRATION          (0-1): Score consistent with findings?

HALLUCINATION RULE:
Citing a section NOT in retrieved context is NOT automatically a hallucination.
Only flag if the citation CONTRADICTS the retrieved law or the facts.

OVERRIDE RULE:
Set override_verdict=true ONLY if compliance_passed is demonstrably WRONG.

OUTPUT — ONLY this exact JSON. No markdown.
{{
    "rubric_scores": {{
        "mini_miranda_handling":  integer (0-2),
        "pre_detection_coverage": integer (0-3),
        "legal_grounding":        integer (0-2),
        "violation_id_accuracy":  integer (0-2),
        "score_calibration":      integer (0-1)
    }},
    "total_grade":                   integer (0-10),
    "hallucinations_found":          ["description or empty"],
    "missed_violations":             ["description or empty"],
    "contradiction_found":           boolean,
    "override_verdict":              boolean,
    "verification_notes":            "What Agent 1 got right and wrong.",
    "prompt_improvement_suggestion": "Single most impactful prompt change."
}}"""

# ─────────────────────────────────────────────────────────────────────────────
# SAFE JSON PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _safe_json(raw: str, context: str = "") -> Optional[Dict]:
    if not raw or not raw.strip():
        logger.error(f"Empty response from {context}"); return None
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    try:
        start = raw.index("{"); end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        pass
    logger.error(f"JSON parse failed for {context}. Raw[:500]: {raw[:500]}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# VIOLATION ID NORMALIZER
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_violations(llm_violations, valid_ids, pre_ids):
    clean, dropped = [], []
    for pid in pre_ids:
        if pid not in clean:
            clean.append(pid)
    for v in llm_violations:
        v = v.strip()
        if not v: continue
        if v in valid_ids:
            if v not in clean: clean.append(v)
        elif v.startswith("§") or re.match(r"^\d{3}", v):
            logger.warning(f"Dropped citation-style ID '{v}'"); dropped.append(v)
        else:
            logger.warning(f"Dropped unknown ID '{v}'"); dropped.append(v)
    return clean, dropped

# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_qa_audit(transcript, account_name, think_mode=False, debug=True):
    """
    Synchronous generator — yields SSE-compatible event dicts.
    Event types are identical to your existing audit.py consumer.
    Now includes: speaker segmentation, pre-detection, grader, ID normalization.
    """
    run_id        = datetime.now().strftime("%Y%m%d_%H%M%S")
    auditor_model = PRIMARY_AUDITOR_MODEL if think_mode else VERIFIER_MODEL
    mode_label    = "Llama 3.1 70B (Think Mode)" if think_mode else "DeepSeek V4 Pro (Flash Mode)"

    _sep(f"AUDIT RUN {run_id} — {account_name}")
    _block("CONFIG", f"  Model: {mode_label}\n  Transcript: {len(transcript)} chars")

    logger.info(f"Evaluating Transcript for: {account_name}")
    yield {"type": "status", "step": "init", "message": f"Evaluating transcript for: {account_name}"}

    # ── STAGE A: SQL Fact Lookup ──────────────────────────────────────────────
    yield {"type": "status", "step": "database", "message": "Fetching debtor profile from SQLite vault"}
    sql_facts, sql_balance, sql_status = _get_sql_facts(account_name)

    if sql_facts is None:
        msg = f"Account '{account_name}' not found in SQL database."
        logger.error(msg)
        yield {"type": "error", "message": msg}
        return

    _block("STAGE A — SQL FACTS", f"  {sql_facts}")

    # ── STAGE B: Speaker Segmentation ─────────────────────────────────────────
    yield {"type": "status", "step": "database", "message": "Segmenting transcript by speaker role…"}
    segmentation = speaker_segmenter.segment(transcript)

    _block("STAGE B — SPEAKER SEGMENTATION", (
        f"  Agent turns:  {segmentation.agent_turn_count} | "
        f"Debtor turns: {segmentation.debtor_turn_count} | "
        f"Unknown: {segmentation.unknown_turn_count} | "
        f"Confidence: {segmentation.confidence:.2f}\n\n"
        f"  [AGENT TEXT — fed to pre-detector]\n"
        f"  {segmentation.agent_text[:400]}{'...' if len(segmentation.agent_text) > 400 else ''}\n\n"
        f"  [DEBTOR TEXT — excluded from pre-detector]\n"
        f"  {segmentation.debtor_text[:300]}{'...' if len(segmentation.debtor_text) > 300 else ''}"
    ))

    low_confidence = segmentation.confidence < 0.55
    if low_confidence:
        logger.warning(f"Low segmentation confidence ({segmentation.confidence:.2f})")

    segmentation_note = ""
    if low_confidence:
        segmentation_note = (
            f"\n⚠ SEGMENTATION NOTE: Speaker attribution confidence is low "
            f"({segmentation.confidence:.2f}). Some turns may be misattributed. "
            f"Focus on content clearly from the agent's institutional role.\n"
        )
    elif segmentation.unknown_turn_count > 2:
        segmentation_note = (
            f"\n~ NOTE: {segmentation.unknown_turn_count} segments marked [UNKNOWN]. "
            f"Evaluate carefully before attributing violations.\n"
        )

    # ── STAGE C: Pre-Detection — AGENT TEXT ONLY ──────────────────────────────
    yield {"type": "status", "step": "database", "message": "Running pre-detection on agent speech only…"}
    pre_report = pre_detector.analyze(
        transcript  = segmentation.agent_text,  # ← AGENT ONLY
        sql_balance = sql_balance,
    )
    pre_block = pre_report.to_prompt_block()

    _block("STAGE C — PRE-DETECTION REPORT", pre_block)
    _jblock("PRE-DETECTION STRUCTURED", {
        "confirmed":         [{"rule_id": v.rule_id, "confidence": v.confidence} for v in pre_report.confirmed_violations],
        "suspicious":        [{"rule_id": v.rule_id} for v in pre_report.suspicious_patterns],
        "mini_miranda":      pre_report.mini_miranda_detected,
        "risk_score":        pre_report.high_risk_score,
    })

    # ── STAGE D: Hybrid Retrieval — FULL TRANSCRIPT ───────────────────────────
    logger.info("Fetching relevant federal law via Hybrid Retriever")
    yield {"type": "status", "step": "database", "message": "Fetching relevant federal law via Hybrid Retriever"}
    standard_context = retriever.retrieve_context(transcript, top_k=5)

    pre_ids_for_fetch = [v.rule_id for v in pre_report.confirmed_violations]
    direct_context    = retriever.retrieve_by_rule_ids(pre_ids_for_fetch) if pre_ids_for_fetch else []

    combined_context_map = {r["rule_id"]: r for r in standard_context}
    for rule in direct_context:
        if rule["rule_id"] not in combined_context_map:
            combined_context_map[rule["rule_id"]] = rule

    retrieved_context = list(combined_context_map.values())
    context_string    = _format_context(retrieved_context)

    _block("STAGE D — RETRIEVED RULES (Merged)", context_string)

    # ── STAGE E: Build Prompt + Run Agent 1 ───────────────────────────────────
    audit_prompt = _build_audit_prompt(
        formatted_transcript = segmentation.formatted_transcript,
        sql_facts            = sql_facts,
        context_string       = context_string,
        pre_block            = pre_block,
        segmentation_note    = segmentation_note,
        valid_rule_ids       = VALID_RULE_IDS,
    )
    _block("STAGE E — FULL AUDIT PROMPT (Agent 1 Input)", audit_prompt)

    yield {"type": "status", "step": "auditing",
           "message": f"Routing to {mode_label}. Generating stream"}

    _sep(f"AGENT 1 STREAM ({mode_label})")
    full_response = ""
    try:
        response_1 = llm_client.chat.completions.create(
            model    = auditor_model,
            messages = [
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user",   "content": audit_prompt},
            ],
            temperature = 0.1,
            max_tokens  = 1500,
            stream      = True,
        )
        print("\n[AGENT 1 STREAM OUTPUT]")
        for chunk in response_1:
            token = chunk.choices[0].delta.content or ""
            if token:
                full_response += token                                          # keep raw for parser
                clean_token = token.replace("```json", "").replace("```", "") # strip markdown noise
                if clean_token:
                    print(clean_token, end="", flush=True)
                    yield {"type": "token", "content": clean_token}           # send clean to UI
        print()
        logger.debug(f"Agent 1 raw:\n{full_response}")

    except Exception as e:
        msg = f"Agent 1 failed: {e}"
        logger.error(msg)
        yield {"type": "error", "message": f"Pipeline Error: {msg}"}
        return

    # ── STAGE F: Parse + Normalize ────────────────────────────────────────────
    audit_result = _safe_json(full_response, "Agent 1")
    if audit_result is None:
        yield {"type": "error", "message": "Agent 1 returned unparseable JSON. Pipeline aborted."}
        return

    _jblock("AGENT 1 PARSED (raw)", audit_result)

    pre_ids = pre_report.get_pre_detected_rule_ids()
    raw_v   = audit_result.get("violations_found", [])
    clean_v, dropped_v = _normalize_violations(raw_v, VALID_RULE_IDS, pre_ids)
    audit_result["violations_found"] = clean_v

    _jblock("VIOLATION ID NORMALIZATION", {
        "raw_from_llm": raw_v, "pre_detected_added": pre_ids,
        "final": clean_v, "dropped": dropped_v,
    })

    # Pre-detector override
    if pre_ids and audit_result.get("compliance_passed") is True:
        logger.warning("PRE-DETECTOR OVERRIDE: LLM said compliant but confirmed violations exist.")
        audit_result["compliance_passed"] = False
        if audit_result.get("performance_score", 10) > 4:
            audit_result["performance_score"] = 4
        audit_result["reasoning"] = (
            f"[PRE-DETECTOR OVERRIDE] Confirmed violations: {pre_ids}. "
            + audit_result.get("reasoning", "")
        )

    # Mini-Miranda override
    if not pre_report.mini_miranda_detected and audit_result.get("compliance_passed") is True:
        logger.warning("Mini-Miranda absent — overriding compliance_passed.")
        audit_result["compliance_passed"] = False
        if audit_result.get("performance_score", 10) > 2:
            audit_result["performance_score"] = 2
        audit_result["reasoning"] = (
            "[MINI-MIRANDA OVERRIDE] Agent failed to provide the required § 807(11) "
            "disclosure. This is a strict liability FDCPA violation. "
            + audit_result.get("reasoning", "")
        )

    # ── STAGE G: Agent 2 — Prompt Grader ─────────────────────────────────────
    logger.info("Agent 2 is grading Agent 1's output")
    yield {"type": "status", "step": "verifying",
           "message": "Agent 2 (Prompt Grader) evaluating audit quality…"}

    grader_prompt  = _build_grader_prompt(
        audit_result   = audit_result,
        pre_report     = pre_report,
        context_string = context_string,
        transcript     = segmentation.formatted_transcript,
        sql_facts      = sql_facts,
    )
    _block("GRADER PROMPT (Agent 2 Input)", grader_prompt)

    grader_result      = None
    verification_notes = "Grader did not run."
    grade_report       = {}

    try:
        response_2 = llm_client.chat.completions.create(
            model    = VERIFIER_MODEL,
            messages = [
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user",   "content": grader_prompt},
            ],
            temperature = 0.1,
            max_tokens  = 500,
            stream      = False,
        )
        raw_grade     = response_2.choices[0].message.content
        _block("AGENT 2 RAW OUTPUT", raw_grade)
        grader_result = _safe_json(raw_grade, "Agent 2 Grader")

    except Exception as e:
        logger.error(f"Agent 2 failed: {e}. Continuing with Agent 1 result.")

    if grader_result:
        verification_notes = grader_result.get("verification_notes", "")
        grade_report       = grader_result.get("rubric_scores", {})
        total_grade        = grader_result.get("total_grade", "N/A")
        hallucinations     = grader_result.get("hallucinations_found", [])
        missed             = grader_result.get("missed_violations", [])
        suggestion         = grader_result.get("prompt_improvement_suggestion", "")
        override           = grader_result.get("override_verdict", False)

        _jblock("GRADE REPORT", {
            "rubric_scores": grade_report, "total_grade": total_grade,
            "hallucinations": hallucinations, "missed": missed,
            "suggestion": suggestion, "override": override,
        })

        print(f"\n{'='*70}")
        print(f"  PROMPT GRADE: {total_grade}/10")
        print(f"  SUGGESTION:   {suggestion}")
        if hallucinations: print(f"  HALLUCINATIONS: {hallucinations}")
        if missed:         print(f"  MISSED: {missed}")
        print(f"{'='*70}")

        if override:
            logger.warning("GRADER OVERRIDE: Verdict flagged as incorrect.")
            audit_result["compliance_passed"] = False
            audit_result["performance_score"] = 1
            audit_result["reasoning"] = (
                f"[OVERRIDDEN BY GRADER]: {verification_notes} | "
                f"Original: {audit_result.get('reasoning', '')}"
            )

        for missed_desc in missed:
            for rid in VALID_RULE_IDS:
                if rid in missed_desc and rid not in audit_result["violations_found"]:
                    logger.info(f"Adding grader-identified missed violation: {rid}")
                    audit_result["violations_found"].append(rid)

    # ── STAGE H: Final Result ─────────────────────────────────────────────────
    logger.info(f"Audit Complete. Final Score: {audit_result.get('performance_score')}")

    final_payload = {
        **audit_result,
        "verification_notes":   verification_notes,
        "retrieved_rules":      [r["rule_id"] for r in retrieved_context],
        "sql_facts":            sql_facts,
        "account_name":         account_name,
        "transcript":           transcript,
        "formatted_transcript": segmentation.formatted_transcript,
        "pre_detection": {
            "mini_miranda_detected": pre_report.mini_miranda_detected,
            "mini_miranda_evidence": pre_report.mini_miranda_evidence,
            "confirmed_violations":  [
                {"rule_id": v.rule_id, "citation": v.citation,
                 "confidence": v.confidence, "explanation": v.explanation,
                 "evidence": v.evidence}
                for v in pre_report.confirmed_violations
            ],
            "suspicious_patterns":   [
                {"rule_id": v.rule_id, "citation": v.citation,
                 "explanation": v.explanation}
                for v in pre_report.suspicious_patterns
            ],
            "risk_score": pre_report.high_risk_score,
        },
        "grade_report": {
            **grade_report,
            "total_grade":  grader_result.get("total_grade") if grader_result else None,
            "prompt_improvement_suggestion": grader_result.get("prompt_improvement_suggestion", "") if grader_result else "",
            "hallucinations_found": grader_result.get("hallucinations_found", []) if grader_result else [],
        },
        "speaker_segmentation": {
            "confidence":   segmentation.confidence,
            "agent_turns":  segmentation.agent_turn_count,
            "debtor_turns": segmentation.debtor_turn_count,
        },
    }

    _jblock("FINAL RESULT", final_payload)
    _sep(
        f"AUDIT COMPLETE — "
        f"{'COMPLIANT' if final_payload['compliance_passed'] else 'VIOLATION'} — "
        f"Score {final_payload['performance_score']}/10"
    )

    yield {"type": "complete", "result": final_payload}
