# AuditIQ — Technical Architecture

> Deep-dive reference for engineers reviewing the codebase or extending the system.

---

## 1. System Overview

AuditIQ is structured as a classic three-tier application — React SPA frontend, FastAPI backend, dual-database data layer — but the interesting engineering lives entirely in the service layer. The backend exposes one primary endpoint (`/audit/stream`) that orchestrates a multi-stage AI pipeline and streams results back to the client as Server-Sent Events.

The pipeline has eight sequential stages. Each stage either adds data, transforms data, or makes a decision that constrains downstream stages. The critical design principle is **defense in depth**: no single component is trusted to catch all violations. Deterministic Python catches the obvious ones. Hybrid RAG ensures legal grounding. The LLM handles nuance. A second LLM grades the first.

---

## 2. Data Flow

```
Audio File (.mp3 / .wav)
        │
        ▼
[Whisper Large v3 via Groq]
        │
        ▼  flat transcript string
[Speaker Segmenter]
        │
        ├──── agent_text ──────► [Pre-Detector]
        │                              │
        │                        PreDetectionReport
        │                        (confirmed_violations,
        │                         suspicious_patterns,
        │                         mini_miranda_detected)
        │
        ├──── full transcript ──► [Hybrid Retriever]
        │                              │
        │                    List[Dict] — top 5 rules
        │                    + direct fetch for pre-detected rule IDs
        │
        ├──── formatted_transcript (labeled)
        ├──── sql_facts (from SQLite)
        ├──── pre_block (prompt-formatted report)
        └──── context_string (formatted retrieved rules)
                     │
                     ▼
             [Audit Prompt Builder]
                     │
                     ▼
         [Agent 1 — Llama 3.1 70B]
                     │  streamed JSON tokens
                     ▼
         [Violation ID Normalizer]
                     │
                     ▼
         [Agent 2 — DeepSeek V4 Pro]
           (Prompt Grader — rubric)
                     │
                     ▼
            Final Result Payload
                     │
                     ├──► SSE "complete" event → Frontend
                     ├──► POST /audit/save → SQLite call_logs
                     └──► POST /audit/report/preview → PDF download
```

---

## 3. Component Deep-Dives

### 3.1 Speaker Segmenter (`speaker_segmenter.py`)

**Problem:** Whisper returns a flat string. FDCPA only regulates the agent. Debtor threats, profanity, and emotional language must never trigger compliance violations.

**Approach:** Rule-based per-sentence classification using weighted pattern scoring. No ML model, no API call — runs in milliseconds.

**Scoring architecture:**

```
Score > 0  →  AGENT
Score < 0  →  DEBTOR
Score = 0  →  continue previous speaker (default)

+3.0  per AGENT_STRONG match  (self-identification, disclosure language)
+1.5  per AGENT_MODERATE match (account framing, professional phrasing)
+3.0  per AGENT_THREATENING_DEBTOR match (garnishment, arrest, legal referral)
-3.5  per DEBTOR_THREATENING_AGENT match (lawyer threats, CFPB reports)
-3.0  per DEBTOR_STRONG match (dispute, denial, "stop calling")
-1.5  per DEBTOR_MODERATE match (reactive short phrases)
+0.5  position bias for first 3 sentences (agents always open the call)
+/-0.5 continuation bonus if |score| < 2.0 and no question mark
```

**Critical design:** `AGENT_THREATENING_DEBTOR` and `DEBTOR_THREATENING_AGENT` are separate pattern sets, not a single "threat" set. This is what correctly attributes "we will garnish your wages" to the agent and "I'll get my lawyer" to the debtor.

**Fallback:** If confidence < 0.55, a segmentation warning is injected into the audit prompt so the LLM knows to be conservative about attributing violations to ambiguous turns.

**Output fields:**
- `agent_text` — concatenated agent turns → fed to pre-detector
- `debtor_text` — concatenated debtor turns → discarded by pre-detector
- `formatted_transcript` — labeled `[AGENT]` / `[DEBTOR]` / `[UNKNOWN]` → fed to LLM prompt

---

### 3.2 Pre-Detector (`pre_detector.py`)

**Problem:** LLMs are probabilistic. Obvious violations (arrest threats, profanity, false balance amounts) should be detected with 100% certainty, not ~97% certainty.

**Detection categories:**

| Category | FDCPA Section | Confidence | Method |
|---|---|---|---|
| Arrest / criminal threats | § 807(4) | certain | regex — "will have you arrested", "send the sheriff" |
| False lawsuit threats | § 807(5) | high | regex — "sue you", "garnish your wages" |
| Harassment / repeated calls | § 806 | high | regex — "keep calling you", "call every hour" |
| Profanity / abuse | § 806(2) | certain | profanity word list |
| Third-party disclosure | § 805(b) | suspicious | regex — third-party relationship terms |
| Workplace contact | § 805(a)(3) | suspicious | regex — employer/office references |
| False attorney involvement | § 807(3) | suspicious | regex — attorney/legal department framing |
| False balance amount | § 807(2) | certain | regex + SQL cross-reference (±$5 tolerance) |
| Mini-Miranda absent | § 807(11) | certain | regex — required disclosure phrases |
| Validation rights | § 809(a) | informational | regex — 30-day dispute language |

**Confirmed vs Suspicious:** Confirmed violations go into the prompt as hard facts the LLM must address. Suspicious patterns are presented as flags for the LLM to evaluate with context. This distinction prevents the pre-detector from overriding nuanced judgment calls.

**Balance cross-reference:** The pre-detector receives `sql_balance` from Stage A. It extracts dollar amounts from the agent transcript using regex, compares them to the true balance, and flags any discrepancy over $5 as a § 807(2) violation — deterministically, with no LLM involved.

**Output:** `PreDetectionReport` dataclass with a `to_prompt_block()` method that renders a structured, human-readable block injected into the audit prompt as STEP 2.

---

### 3.3 Hybrid Retriever (`hybrid_retriever.py`)

**Problem:** The LLM must reason against the actual statute, not its training data. Retrieval must bridge the vocabulary gap between formal legal language and colloquial transcript speech.

**Three-stage pipeline:**

```
Stage 1: Dense search (ChromaDB + NVIDIA nv-embed-v1)
  - Embedding text = explanation + violation_patterns + scenario_anchors
  - top_k=15 candidates
  - Captures semantic similarity across vocabulary gap

Stage 2: BM25 sparse search (rank-bm25, BM25Okapi)
  - Improved tokenizer: strips legal stopwords, preserves § references
  - Corpus = full enriched metadata (scenario_anchors + key_terms + violation_patterns)
  - top_k=15 candidates
  - Captures exact legal term matches ("§ 806", "debt collector")

Stage 3: Merge + Cluster dedup
  - Union of dense and sparse candidates by rule_id
  - One rule per cluster_id (priority field determines winner)
  - superseded_by field checked against candidate set

Stage 4: Cross-encoder reranking
  - Local MiniLM-L-6-v2 (ms-marco fine-tuned)
  - Input pairs: (transcript_snippet, rule_doc)
  - Resolves disagreements between dense and sparse

Stage 5: Negative anchor filter
  - Rules with >35% token overlap between negative_anchors and query are downranked
  - Prevents safe-harbor situations from triggering false violation retrievals

Stage 6: Parent-child fetch
  - mapped_sections (CSV) used to fetch raw statute text from Collection A
  - Each returned rule includes both the curated summary AND the raw federal law
```

**Direct fetch merge:** Pre-detected violation rule IDs are fetched directly from Collection B via `retrieve_by_rule_ids()` and merged into the standard results. This guarantees the LLM always has the law for confirmed violations, regardless of whether they rank in the top 5 semantically.

---

### 3.4 Rules Knowledge Base

**Collection B** is built from `rules_core.json` — 115 enriched compliance rules. Each rule has 10 fields:

```
id                    — unique rule identifier (RULE_SNAKE_CASE)
type                  — "compliance_rule"
rule                  — verbatim or close paraphrase of statute
severity              — critical / high / medium / low
rule_type             — commission / omission / disclosure / contextual
mapped_sections       — array of Collection A document IDs
sub_section_citation  — "§ 805(b)"
explanation           — plain English summary (primary embedding document)
scenario_anchors      — 8-14 colloquial transcript phrases
violation_patterns    — 5-8 analytical violation descriptions
key_terms             — [[legal_term, street_equivalent], ...]
negative_anchors      — 4-6 safe-harbor situation descriptions
cluster_id            — assigned by semantic dedup pass
priority              — 1 = primary rule in cluster
superseded_by         — ID of higher-priority cluster rule (if any)
```

**Enrichment pipeline (offline):**
1. `expand_rules.py` — extracts structured rules from raw PDF text via LLM
2. `enrich_rules.py` — generates retrieval-critical fields via dual-persona prompt
3. `patch_rules.py` — validates quality (minimum counts, generic content detection, schema validation), re-enriches failures
4. `document_processor.py` — runs semantic dedup (cosine similarity matrix, 0.88 threshold), assigns clusters, ingests into ChromaDB

**ChromaDB storage:** `scenario_anchors`, `violation_patterns`, `key_terms`, `negative_anchors` are flattened to pipe-delimited strings (ChromaDB metadata cannot store arrays) and expanded back to lists on retrieval.

---

### 3.5 Audit Prompt Architecture

The prompt fed to Agent 1 has four structured steps, each clearly delimited:

```
STEP 1 — SQL ACCOUNT FACTS
  True balance and account status.
  Explicit instruction: if agent's stated balance differs → § 807(2) violation.

STEP 2 — PRE-DETECTION LAYER
  Rendered PreDetectionReport — confirmed violations with evidence, 
  suspicious patterns, Mini-Miranda status.
  Explicit instruction: address EVERY flag with transcript evidence.

STEP 3 — RETRIEVED LEGAL CONTEXT
  5+ rules, each with: rule_id, citation, severity, rule_statement,
  explanation, violation_patterns (top 5), raw federal law text.

STEP 4 — CALL TRANSCRIPT
  Speaker-attributed formatted transcript [AGENT] / [DEBTOR] / [UNKNOWN].
  Speaker attribution rules injected: FDCPA only regulates [AGENT].

AUDIT INSTRUCTIONS
  Explicit reasoning checklist: (a) Mini-Miranda, (b) each pre-detected flag,
  (c) balance accuracy, (d) third-party disclosure, (e) compliant behaviors.

VALID RULE IDs LIST
  All 115 rule IDs from rules_core.json injected explicitly.
  LLM instructed: use ONLY these IDs, no citation strings.

OUTPUT SCHEMA
  Strict JSON: compliance_passed, performance_score, violations_found, reasoning.
```

**Why inject the valid rule IDs?** Without this, models produce inconsistent violation ID formats — sometimes `RULE_FALSE_LEGAL_STATUS`, sometimes `§ 807(5)`, sometimes `FALSE_LEGAL_STATUS`. The ID list constrains the output space. Post-processing normalizes any stragglers.

---

### 3.6 Prompt Grader (Agent 2)

**Purpose:** Evaluate Agent 1's audit quality for prompt engineering iteration, not just catch hallucinations.

**Rubric (10 points total):**

| Criterion | Points | Evaluates |
|---|---|---|
| Mini-Miranda handling | 0-2 | Correct identification and verdict action |
| Pre-detection coverage | 0-3 | Did Agent 1 address every flagged pattern with evidence? |
| Legal grounding | 0-2 | Are citations traceable to retrieved rules? |
| Violation ID accuracy | 0-2 | Valid IDs, correctly mapped to violations? |
| Score calibration | 0-1 | Is the score consistent with the findings? |

**Critical hallucination rule:** The grader is explicitly told that citing a section not in the retrieved context is **not** automatically a hallucination — the model may have correct FDCPA knowledge from training. A hallucination is only flagged when a citation **contradicts** the retrieved law or the facts in evidence. This fixed the Case 4 false-positive override from v1.

**Override condition:** `override_verdict=true` only when `compliance_passed` is demonstrably wrong based on transcript evidence. The grader also returns `missed_violations` — a list of rule IDs it identified that Agent 1 missed — which are merged into the final `violations_found` list.

**`prompt_improvement_suggestion`:** One sentence per run identifying the single most impactful change to the audit prompt. These are logged and reviewed across eval runs to drive prompt iteration.

---

### 3.7 SSE Streaming Architecture

`run_qa_audit()` is a synchronous Python generator — it yields events as the pipeline progresses. The FastAPI endpoint is async. Bridging these correctly without blocking the event loop requires a queue pattern:

```python
event_queue = asyncio.Queue()

def _run_pipeline():
    for event in run_qa_audit(...):
        asyncio.run_coroutine_threadsafe(
            event_queue.put(mapped_event), loop
        )
    asyncio.run_coroutine_threadsafe(
        event_queue.put(None), loop   # sentinel
    )

loop.run_in_executor(None, _run_pipeline)  # thread pool

while True:
    event = await event_queue.get()
    if event is None: break
    yield _sse(event)
    if event["step"] in ("complete", "error"): break
```

The generator runs in a thread pool. Events are posted to the asyncio queue via `run_coroutine_threadsafe`. The async handler consumes the queue and yields SSE strings. The sentinel `None` fires in `finally:` — guaranteed even on pipeline crash.

**Token streaming:** Agent 1's response is streamed token-by-token. Markdown fences (` ```json `) are stripped from tokens before yielding to the UI but preserved in `full_response` for the JSON parser. The parser has three fallback attempts: direct parse, fence-stripped parse, and `{...}` substring extraction.

---

## 4. Database Design

### SQLite Schema

```sql
CREATE TABLE debtors (
    debtor_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    account_number TEXT    UNIQUE NOT NULL,
    name           TEXT    NOT NULL,
    balance        REAL    NOT NULL CHECK(balance >= 0),
    status         TEXT    NOT NULL CHECK(status IN ('Active', 'Settlement negotiated', 'Pending Legal Action'))
);

CREATE TABLE call_logs (
    log_id                INTEGER  PRIMARY KEY AUTOINCREMENT,
    debtor_id             INTEGER  NOT NULL REFERENCES debtors(debtor_id),
    agent_id              INTEGER  NOT NULL REFERENCES agents(agent_id),
    auditor_id            INTEGER  NOT NULL REFERENCES auditors(auditor_id),
    cloud_audio_uri       TEXT     UNIQUE,
    transcript            TEXT     NOT NULL,
    llm_prompt            TEXT,
    compliance_passed     BOOLEAN  NOT NULL CHECK(compliance_passed IN (0, 1)),
    ai_performance_score  INTEGER  NOT NULL CHECK(ai_performance_score BETWEEN 1 AND 10),
    reasoning             TEXT,
    violations            TEXT,     -- JSON array serialized
    verification_notes    TEXT,
    retrieved_rules       TEXT,     -- JSON array serialized
    sql_facts             TEXT,
    human_override_score  INTEGER   CHECK(human_override_score BETWEEN 1 AND 10),
    timestamp             DATETIME  DEFAULT CURRENT_TIMESTAMP
);
```

### ChromaDB Collections

**Collection A — `fdcpa_raw_text`**
- Documents: raw FDCPA section text (§ 801 through § 818)
- IDs: `FDCPA_801`, `FDCPA_802`, ... `FDCPA_818`
- Split by regex on `§ 8XX.` patterns from PDF
- Used only for parent-child law text fetching

**Collection B — `fdcpa_compliance_rules`**
- Documents: enriched explanation strings (primary embedding)
- IDs: `RULE_*` identifiers matching `rules_core.json`
- Metadata: all enrichment fields, flattened arrays, cluster/priority fields
- Used for both semantic search and BM25 corpus

---

## 5. Override Logic and Safety Nets

Three layers of deterministic override sit between the LLM output and the final result:

```
LLM produces audit_result
        │
        ▼
[Violation ID Normalizer]
  - Pre-detected IDs force-merged (always valid)
  - Citation-style strings (§ 806) dropped with warning
  - Unknown IDs dropped with warning

        │
        ▼
[Pre-Detector Override]
  if confirmed_violations exist AND compliance_passed is True:
    → compliance_passed = False
    → performance_score = min(current_score, 4)
    → reasoning prefixed with [PRE-DETECTOR OVERRIDE]

        │
        ▼
[Mini-Miranda Override]
  if mini_miranda not detected AND compliance_passed is True:
    → compliance_passed = False
    → performance_score = min(current_score, 2)
    → reasoning prefixed with [MINI-MIRANDA OVERRIDE]
    (§ 807(11) is strict liability — score 2 not 5)

        │
        ▼
[Grader Override]
  if grader.override_verdict is True:
    → compliance_passed = False
    → performance_score = 1
    → reasoning prefixed with [OVERRIDDEN BY GRADER]
    (only fires when verdict is demonstrably wrong)
```

Score semantics post-override:
- `> 4` → at most 4 if pre-detector confirmed violations exist
- `> 2` → at most 2 if Mini-Miranda absent (strict liability)
- `= 1` → if grader override fires

---

## 6. Offline Knowledge Base Pipeline

The ChromaDB collections are built offline, not at runtime. The pipeline:

```
fdcpa_rules.pdf
      │
      ▼ PyPDFLoader + regex on § 8XX. patterns
Collection A (raw statute)
      │
      ▼ expand_rules.py — LLM extracts structured rules from raw text
rules_core.json (base rules)
      │
      ▼ enrich_rules.py — dual-persona LLM enrichment (Attorney + Retrieval Engineer)
rules_core.json (enriched)
      │
      ▼ patch_rules.py — quality validation, re-enrichment of failures
rules_core.json (validated)
      │
      ▼ document_processor.py:
        1. cluster_and_prioritize_rules() — cosine similarity matrix, 0.88 threshold
        2. Build embedding text: explanation + violation_patterns + scenario_anchors
        3. Flatten arrays for ChromaDB metadata (|| delimiter)
        4. collection_b.add()
Collection B (compliance rules)
```

**Semantic dedup:** An NxN cosine similarity matrix is computed over all rule embeddings. Pairs above 0.88 are assigned the same `cluster_id`. Within each cluster, rules are sorted by specificity (anchor count desc), severity, and section number — the most specific rule gets `priority=1`, others get `superseded_by=primary_id`.

At retrieval time, only one rule per cluster reaches the LLM — the highest priority one. This prevents near-duplicate rules (e.g., multiple harassment-adjacent rules under § 806) from consuming multiple retrieval slots.

---

## 7. Known Limitations and Future Work

| Limitation | Impact | Planned Fix |
|---|---|---|
| SQLite single-writer | Concurrent saves serialize | PostgreSQL + asyncpg migration |
| Speaker segmenter accuracy ~85-92% | ~8-15% of turns may misattribute | Integrate pyannote.audio diarization |
| No automated eval suite | Prompt changes validated manually | `eval_runner.py` — regression suite |
| Synchronous LLM calls in generator | Can't parallelize Agent 1 + Agent 2 | LangGraph async graph |
| CORS wildcard | Security risk in production | Restrict to frontend origin |
| Hardcoded `auditor_id=1` | No real auth | JWT + role-based access control |
| `ingestion.py` import side effects | Database wipes on accidental import | Wrap in `__main__` guard |