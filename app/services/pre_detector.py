# ─────────────────────────────────────────────────────────────────────────────
# PRE-DETECTION LAYER
# ─────────────────────────────────────────────────────────────────────────────
# Runs BEFORE the auditor LLM. Performs deterministic regex + keyword checks
# on the raw transcript to:
#   1. Detect obvious/clear-cut FDCPA violations with certainty
#   2. Flag suspicious patterns that need LLM evaluation
#   3. Confirm presence of required disclosures (Mini-Miranda etc.)
#   4. Produce a structured PreDetectionReport fed into the auditor prompt
#
# WHY THIS EXISTS:
#   The LLM is powerful but probabilistic. Basic violations like threatening
#   arrest, calling before 8am, or saying "I'll sue you" are deterministic —
#   they are always violations. Detecting them with regex before the LLM:
#     - Anchors the LLM to concrete evidence it cannot ignore
#     - Reduces hallucination (LLM now confirms pre-detected facts, not invents)
#     - Gives the grader model a ground-truth signal to evaluate LLM accuracy
#     - Makes the audit reproducible and explainable
#
# OUTPUT STRUCTURE: PreDetectionReport (dataclass)
#   fed directly into the auditor prompt as structured context
# ─────────────────────────────────────────────────────────────────────────────

import re
import logging
from dataclasses import dataclass, field
from typing      import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# VIOLATION CATALOG
# Maps RULE_ID → detection config
# These RULE_IDs must match exactly what's in rules_core.json
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DetectedFlag:
    rule_id:      str           # Must match rules_core.json exactly
    citation:     str           # e.g. "§ 806(5)"
    category:     str           # "confirmed_violation" | "suspicious" | "disclosure_missing"
    confidence:   str           # "certain" | "high" | "moderate"
    evidence:     List[str]     # Exact transcript snippets that triggered this
    explanation:  str           # Plain English: what was found and why it matters

@dataclass
class PreDetectionReport:
    # ── Confirmed violations (regex certainty — LLM should almost always agree)
    confirmed_violations:   List[DetectedFlag] = field(default_factory=list)

    # ── Suspicious patterns (need LLM judgment — may be violations in context)
    suspicious_patterns:    List[DetectedFlag] = field(default_factory=list)

    # ── Required disclosures — did the agent say what they legally must say?
    mini_miranda_detected:  bool = False
    mini_miranda_evidence:  str  = ""          # exact snippet if found
    validation_rights_mentioned: bool = False  # § 809(a) — 30-day dispute right

    # ── Confirmed clean behaviors (reduces false positives)
    confirmed_compliant:    List[str] = field(default_factory=list)

    # ── Summary for prompt injection
    high_risk_score:        int  = 0   # 0-10, used to set auditor focus level
    has_any_flag:           bool = False

    def to_prompt_block(self) -> str:
        """Renders the report as a structured block for injection into the audit prompt."""
        lines = ["═" * 60]
        lines.append("PRE-DETECTION LAYER REPORT (Deterministic Python Analysis)")
        lines.append("═" * 60)

        # Required disclosures
        lines.append("\n[REQUIRED DISCLOSURES CHECK]")
        if self.mini_miranda_detected:
            lines.append(f"  ✓ Mini-Miranda (§ 807(11)): DETECTED")
            lines.append(f"    Evidence: \"{self.mini_miranda_evidence}\"")
        else:
            lines.append(f"  ✗ Mini-Miranda (§ 807(11)): NOT DETECTED IN TRANSCRIPT")
            lines.append(f"    → This is a CONFIRMED OMISSION VIOLATION unless an exception applies.")

        if self.validation_rights_mentioned:
            lines.append(f"  ✓ Validation Rights (§ 809(a)): Mentioned")
        else:
            lines.append(f"  ~ Validation Rights (§ 809(a)): Not detected (only required in first written notice — verify call context)")

        # Confirmed violations
        if self.confirmed_violations:
            lines.append(f"\n[CONFIRMED VIOLATIONS — {len(self.confirmed_violations)} detected]")
            lines.append("  These were detected with high certainty by pattern matching.")
            lines.append("  Your analysis MUST address each one explicitly.")
            for i, v in enumerate(self.confirmed_violations, 1):
                lines.append(f"\n  [{i}] RULE_ID: {v.rule_id}  |  Citation: {v.citation}")
                lines.append(f"      Confidence: {v.confidence.upper()}")
                lines.append(f"      What was found: {v.explanation}")
                for ev in v.evidence:
                    lines.append(f"      Transcript evidence: \"{ev}\"")
        else:
            lines.append("\n[CONFIRMED VIOLATIONS] None detected by pattern matching.")

        # Suspicious patterns
        if self.suspicious_patterns:
            lines.append(f"\n[SUSPICIOUS PATTERNS — {len(self.suspicious_patterns)} flagged for LLM review]")
            lines.append("  These may or may not be violations depending on full context.")
            lines.append("  Evaluate each one and explicitly state your conclusion.")
            for i, v in enumerate(self.suspicious_patterns, 1):
                lines.append(f"\n  [{i}] RULE_ID: {v.rule_id}  |  Citation: {v.citation}")
                lines.append(f"      What was found: {v.explanation}")
                for ev in v.evidence:
                    lines.append(f"      Transcript evidence: \"{ev}\"")
        else:
            lines.append("\n[SUSPICIOUS PATTERNS] None flagged.")

        # Compliant behaviors
        if self.confirmed_compliant:
            lines.append(f"\n[CONFIRMED COMPLIANT BEHAVIORS]")
            for c in self.confirmed_compliant:
                lines.append(f"  ✓ {c}")

        lines.append(f"\n[RISK SCORE] {self.high_risk_score}/10 (pre-LLM estimate)")
        lines.append("═" * 60)
        return "\n".join(lines)

    def get_pre_detected_rule_ids(self) -> List[str]:
        """All rule IDs detected with certainty — used to validate LLM output."""
        return [v.rule_id for v in self.confirmed_violations]


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION PATTERNS
# Each entry: (pattern, flags) for re.compile
# Group names in patterns are used to extract evidence snippets
# ─────────────────────────────────────────────────────────────────────────────

# § 807(4) — False threat of arrest / criminal action
ARREST_THREAT_PATTERNS = [
    r"(arrest(?:ed)?(?:\s+\w+){0,5})",
    r"((?:send|call|call in|dispatch)\s+(?:the\s+)?(?:police|cops|sheriff|law enforcement))",
    r"((?:put|throw|lock)\s+(?:you\s+)?in\s+(?:jail|prison|handcuffs))",
    r"(criminal\s+(?:charges?|case|complaint|warrant))",
    r"(warrant\s+(?:out\s+)?(?:for\s+)?(?:your\s+)?arrest)",
    r"(bench\s+warrant)",
]

# § 807(4) — False threat of legal action not intended/authorized
LEGAL_ACTION_THREAT_PATTERNS = [
    r"((?:we\s+(?:will|are\s+going\s+to|are\s+gonna)|i\s+(?:will|am\s+going\s+to))\s+(?:sue|take\s+you\s+to\s+court|file\s+a\s+lawsuit))",
    r"((?:garnish|garnishment)\s+(?:your\s+)?(?:wages?|salary|paycheck|bank\s+account))",
    r"(seize\s+(?:your\s+)?(?:assets?|property|home|car|vehicle))",
    r"((?:file|taking)\s+(?:legal|court)\s+(?:action|proceedings?))",
    r"((?:judgment|lien)\s+(?:against|on)\s+(?:you|your))",
]

# § 806 — Harassment / oppressive conduct
HARASSMENT_PATTERNS = [
    r"((?:calling|call)\s+(?:you\s+)?(?:back\s+)?(?:every|all\s+(?:day|night|week)))",
    r"((?:won't|will\s+not|never\s+stop)\s+(?:calling|contacting))",
    r"(call(?:ing)?\s+(?:you\s+)?(?:\d+\s+)?times?\s+(?:a\s+day|daily|per\s+day))",
    r"(keep\s+(?:calling|harassing|bothering)\s+you)",
    r"((?:obscene|profane|abusive|vulgar)\s+(?:language|words?))",
]

# § 806 — Specific profanity/abuse (high confidence)
PROFANITY_PATTERNS = [
    r"\b(fuck(?:ing)?|shit|bitch|asshole|bastard|goddamn|damn\s+(?:you|it))\b",
    r"(stupid|idiot|moron|loser|deadbeat)\s+(?:like\s+)?you",
]

# § 805(b) — Third-party disclosure
THIRD_PARTY_PATTERNS = [
    r"((?:told|tell|telling|inform(?:ed)?|mentioned\s+(?:it\s+)?to)\s+(?:your\s+)?(?:wife|husband|spouse|mother|father|mom|dad|sister|brother|roommate|neighbor|friend|coworker|boss|employer|manager|supervisor))",
    r"((?:your\s+)?(?:wife|husband|spouse|mother|father|mom|dad|sister|brother|roommate|neighbor|friend|coworker|boss|employer|manager|supervisor)\s+(?:knows?|found\s+out|heard|told\s+me|picked\s+up))",
    r"(left\s+(?:a\s+)?(?:message|voicemail|note)\s+(?:with|for)\s+(?:someone|a\s+person|(?:your\s+)?(?:wife|husband|roommate|coworker|boss|neighbor)))",
    r"((?:spoke|talked|speaking|talking)\s+to\s+(?:your\s+)?(?:wife|husband|spouse|mother|father|roommate|neighbor|friend|coworker|boss|employer))",
]

# § 805(a)(1) — Inconvenient time (before 8am or after 9pm)
TIME_VIOLATION_PATTERNS = [
    r"(?:^|\s)((?:[1-9]|1[0-2])(?::\d{2})?\s*(?:am))\b",   # matches times like 7am, 6:30am
    r"(?:^|\s)((?:9|10|11)(?::\d{2})?\s*(?:pm))\b",          # matches 9pm, 10:30pm etc
    r"(calling\s+(?:you\s+)?(?:early|late|at\s+night|after\s+hours|before\s+(?:you\s+wake|work)))",
]

# § 805(a)(3) — Calling at known inconvenient place (workplace)
WORKPLACE_PATTERNS = [
    r"(calling\s+(?:you\s+)?(?:at\s+)?(?:your\s+)?(?:work|job|office|workplace|employer))",
    r"((?:your\s+)?(?:employer|workplace|company|office)\s+(?:knows?|found\s+out|will\s+find\s+out))",
    r"(I\s+(?:called|will\s+call|am\s+calling)\s+(?:your\s+)?(?:work|job|office|employer))",
]

# § 807(2) — False representation of debt amount
FALSE_AMOUNT_PATTERNS = [
    r"((?:owe|balance|debt|amount)\s+(?:is\s+)?(?:now\s+)?(?:\$[\d,]+(?:\.\d{2})?|\d[\d,]*(?:\.\d{2})?)\s*(?:dollars?)?)",
    # NOTE: this pattern alone isn't a violation — needs cross-reference with sql_facts
    # flagged as "suspicious" not "confirmed"
]

# § 806(6) — False implication of attorney involvement
ATTORNEY_FALSE_PATTERNS = [
    r"((?:our\s+|the\s+)?attorney\s+(?:will|has|is\s+going\s+to)\s+(?:contact|call|file|sue))",
    r"(this\s+(?:matter|case|account)\s+has\s+been\s+(?:forwarded|referred|sent)\s+to\s+(?:our\s+)?(?:legal|attorney|law\s+(?:firm|office|department)))",
    r"((?:legal|law)\s+(?:department|team|firm)\s+(?:will|has|is))",
]

# § 807(11) — Mini-Miranda (required disclosure)
MINI_MIRANDA_PATTERNS = [
    r"((?:this\s+is\s+)?(?:an?\s+)?attempt\s+to\s+collect\s+(?:a\s+)?debt)",
    r"((?:I\s+am|this\s+is)\s+(?:a\s+)?debt\s+collector)",
    r"(calling\s+(?:from|on\s+behalf\s+of)\s+(?:a\s+)?(?:collection|debt\s+collection)\s+(?:agency|company))",
    r"(any\s+information\s+(?:you\s+provide\s+)?(?:will\s+be\s+used|obtained\s+will\s+be\s+used)\s+(?:for\s+(?:that\s+)?purpose|to\s+collect))",
    r"((?:debt\s+collection|collection\s+(?:agency|company|call)))",
]

# § 809(a) — Validation rights
VALIDATION_RIGHTS_PATTERNS = [
    r"((?:you\s+have\s+)?(?:30|thirty)\s+days?\s+to\s+(?:dispute|challenge|verify|contest))",
    r"(right\s+to\s+(?:dispute|verify|request\s+verification))",
    r"(written\s+(?:dispute|verification\s+request|notice))",
    r"(cease\s+(?:collection\s+)?(?:activities?|efforts?|contact))",
]

# Compliant behaviors (reduces false positives)
COMPLIANT_PATTERNS = [
    (r"((?:I\s+understand|I\s+respect)\s+(?:your\s+)?(?:decision|wish|request))", "Agent acknowledged consumer's request"),
    (r"((?:you\s+have\s+the\s+right|you\s+are\s+entitled)\s+to)", "Agent informed of consumer rights"),
    (r"(please\s+don't\s+hesitate\s+to\s+(?:call|contact|reach))", "Agent offered cooperative communication"),
    (r"(have\s+a\s+(?:good|great|nice)\s+(?:day|evening|night))", "Agent closed professionally"),
]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DETECTOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class PreDetector:
    """
    Runs deterministic FDCPA violation detection on a raw transcript.
    Produces a PreDetectionReport consumed by the auditor prompt builder.
    """

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        flags = re.IGNORECASE | re.MULTILINE
        self._arrest          = [re.compile(p, flags) for p in ARREST_THREAT_PATTERNS]
        self._legal_action    = [re.compile(p, flags) for p in LEGAL_ACTION_THREAT_PATTERNS]
        self._harassment      = [re.compile(p, flags) for p in HARASSMENT_PATTERNS]
        self._profanity       = [re.compile(p, flags) for p in PROFANITY_PATTERNS]
        self._third_party     = [re.compile(p, flags) for p in THIRD_PARTY_PATTERNS]
        self._time_violation  = [re.compile(p, flags) for p in TIME_VIOLATION_PATTERNS]
        self._workplace       = [re.compile(p, flags) for p in WORKPLACE_PATTERNS]
        self._false_amount    = [re.compile(p, flags) for p in FALSE_AMOUNT_PATTERNS]
        self._attorney_false  = [re.compile(p, flags) for p in ATTORNEY_FALSE_PATTERNS]
        self._mini_miranda    = [re.compile(p, flags) for p in MINI_MIRANDA_PATTERNS]
        self._validation      = [re.compile(p, flags) for p in VALIDATION_RIGHTS_PATTERNS]
        self._compliant       = [(re.compile(p, flags), desc) for p, desc in COMPLIANT_PATTERNS]

    def _find_matches(self, patterns: list, transcript: str) -> List[str]:
        """Returns all unique matched snippets from a list of patterns."""
        found = []
        for pat in patterns:
            for match in pat.finditer(transcript):
                snippet = match.group(0).strip()
                if snippet and snippet not in found:
                    found.append(snippet)
        return found

    def _extract_context(self, transcript: str, snippet: str, window: int = 60) -> str:
        """Returns the sentence/window around a matched snippet for context."""
        idx = transcript.lower().find(snippet.lower())
        if idx == -1:
            return snippet
        start = max(0, idx - window)
        end   = min(len(transcript), idx + len(snippet) + window)
        return "..." + transcript[start:end].strip() + "..."

    def analyze(self, transcript: str, sql_balance: Optional[float] = None) -> PreDetectionReport:
        """
        Main entry point. Analyzes transcript and returns PreDetectionReport.

        Args:
            transcript:   Raw transcript string from Whisper
            sql_balance:  True balance from SQLite — used to detect false amount claims
        """
        report = PreDetectionReport()
        t      = transcript  # alias

        # ── 1. Mini-Miranda check ─────────────────────────────────────────────
        mm_matches = self._find_matches(self._mini_miranda, t)
        if mm_matches:
            report.mini_miranda_detected = True
            report.mini_miranda_evidence = mm_matches[0]
        # NOTE: mini-miranda ABSENCE is itself a violation — no else branch needed,
        # the prompt block handles the "not detected" case explicitly

        # ── 2. Validation rights check ────────────────────────────────────────
        val_matches = self._find_matches(self._validation, t)
        if val_matches:
            report.validation_rights_mentioned = True

        # ── 3. Arrest / criminal threats (§ 807(4)) ───────────────────────────
        arrest_matches = self._find_matches(self._arrest, t)
        if arrest_matches:
            evidence = [self._extract_context(t, m) for m in arrest_matches[:3]]
            report.confirmed_violations.append(DetectedFlag(
                rule_id     = "RULE_FALSE_LEGAL_THREAT",
                citation    = "§ 807(4)",
                category    = "confirmed_violation",
                confidence  = "certain",
                evidence    = evidence,
                explanation = (
                    "Agent made references to arrest, criminal charges, or law enforcement. "
                    "Debt collectors cannot threaten arrest to collect a civil debt — "
                    "this is explicitly prohibited by § 807(4)."
                )
            ))
            report.high_risk_score += 3

        # ── 4. False legal action threats (§ 807(4) / § 807(5)) ──────────────
        legal_matches = self._find_matches(self._legal_action, t)
        if legal_matches:
            evidence = [self._extract_context(t, m) for m in legal_matches[:3]]
            report.confirmed_violations.append(DetectedFlag(
                rule_id     = "RULE_FALSE_LEGAL_STATUS",
                citation    = "§ 807(5)",
                category    = "confirmed_violation",
                confidence  = "high",
                evidence    = evidence,
                explanation = (
                    "Agent threatened lawsuits, wage garnishment, or asset seizure. "
                    "These are violations if the collector is not authorized to take "
                    "such action or does not actually intend to do so."
                )
            ))
            report.high_risk_score += 3

        # ── 5. Harassment / repeated calls (§ 806) ───────────────────────────
        harass_matches = self._find_matches(self._harassment, t)
        if harass_matches:
            evidence = [self._extract_context(t, m) for m in harass_matches[:3]]
            report.confirmed_violations.append(DetectedFlag(
                rule_id     = "RULE_HARASSMENT_OR_ABUSE",
                citation    = "§ 806",
                category    = "confirmed_violation",
                confidence  = "high",
                evidence    = evidence,
                explanation = (
                    "Agent made statements indicating harassment through repeated contact "
                    "or oppressive tactics. § 806 prohibits conduct whose natural consequence "
                    "is to harass, oppress, or abuse."
                )
            ))
            report.high_risk_score += 2

        # ── 6. Profanity / abusive language (§ 806(2)) ───────────────────────
        prof_matches = self._find_matches(self._profanity, t)
        if prof_matches:
            evidence = [self._extract_context(t, m) for m in prof_matches[:3]]
            report.confirmed_violations.append(DetectedFlag(
                rule_id     = "RULE_ABUSIVE_LANGUAGE",
                citation    = "§ 806(2)",
                category    = "confirmed_violation",
                confidence  = "certain",
                evidence    = evidence,
                explanation = (
                    "Agent used obscene, profane, or abusive language. "
                    "§ 806(2) explicitly prohibits this."
                )
            ))
            report.high_risk_score += 3

        # ── 7. Third-party disclosure (§ 805(b)) ─────────────────────────────
        tp_matches = self._find_matches(self._third_party, t)
        if tp_matches:
            evidence = [self._extract_context(t, m) for m in tp_matches[:3]]
            report.suspicious_patterns.append(DetectedFlag(
                rule_id     = "RULE_THIRD_PARTY_DISCLOSURE",
                citation    = "§ 805(b)",
                category    = "suspicious",
                confidence  = "high",
                evidence    = evidence,
                explanation = (
                    "Transcript contains references to third parties (spouse, roommate, "
                    "coworker etc.) in connection with the debt. Evaluate whether debt "
                    "information was disclosed to them without prior consent."
                )
            ))
            report.high_risk_score += 2

        # ── 8. Workplace contact (§ 805(a)(3)) ───────────────────────────────
        work_matches = self._find_matches(self._workplace, t)
        if work_matches:
            evidence = [self._extract_context(t, m) for m in work_matches[:3]]
            report.suspicious_patterns.append(DetectedFlag(
                rule_id     = "RULE_INCONVENIENT_PLACE_CONTACT",
                citation    = "§ 805(a)(3)",
                category    = "suspicious",
                confidence  = "moderate",
                evidence    = evidence,
                explanation = (
                    "Workplace or employer referenced. If agent called the consumer's "
                    "workplace knowing employer disapproves, this violates § 805(a)(3)."
                )
            ))
            report.high_risk_score += 1

        # ── 9. False attorney involvement (§ 807(3)) ─────────────────────────
        atty_matches = self._find_matches(self._attorney_false, t)
        if atty_matches:
            evidence = [self._extract_context(t, m) for m in atty_matches[:3]]
            report.suspicious_patterns.append(DetectedFlag(
                rule_id     = "RULE_FALSE_ATTORNEY_REPRESENTATION",
                citation    = "§ 807(3)",
                category    = "suspicious",
                confidence  = "high",
                evidence    = evidence,
                explanation = (
                    "Agent implied legal department or attorney involvement. "
                    "This is a § 807(3) violation if the attorney is not meaningfully "
                    "involved in the collection decision."
                )
            ))
            report.high_risk_score += 2

        # ── 10. Balance claim cross-reference (§ 807(2)) ─────────────────────
        if sql_balance is not None:
            amount_matches = self._find_matches(self._false_amount, t)
            for match_text in amount_matches:
                # Extract the number from the match
                num_match = re.search(r'[\d,]+(?:\.\d{2})?', match_text)
                if num_match:
                    try:
                        claimed = float(num_match.group().replace(',', ''))
                        # Allow ±$5 tolerance for fees/rounding
                        if abs(claimed - sql_balance) > 5.0:
                            report.confirmed_violations.append(DetectedFlag(
                                rule_id     = "RULE_FALSE_DEBT_AMOUNT",
                                citation    = "§ 807(2)",
                                category    = "confirmed_violation",
                                confidence  = "certain",
                                evidence    = [f"Agent stated: \"{match_text}\" | True balance: ${sql_balance:.2f}"],
                                explanation = (
                                    f"Agent stated balance of ${claimed:,.2f} but SQLite record "
                                    f"shows true balance is ${sql_balance:,.2f}. "
                                    f"This is a § 807(2) false representation violation."
                                )
                            ))
                            report.high_risk_score += 3
                            break
                    except ValueError:
                        pass

        # ── 11. Compliant behavior detection ─────────────────────────────────
        for pat, desc in self._compliant:
            if pat.search(t):
                report.confirmed_compliant.append(desc)

        # ── Finalize ─────────────────────────────────────────────────────────
        report.high_risk_score  = min(report.high_risk_score, 10)
        report.has_any_flag     = bool(
            report.confirmed_violations or
            report.suspicious_patterns  or
            not report.mini_miranda_detected
        )

        logger.info(
            f"PreDetector: {len(report.confirmed_violations)} confirmed violations, "
            f"{len(report.suspicious_patterns)} suspicious patterns, "
            f"Mini-Miranda={'YES' if report.mini_miranda_detected else 'NO'}, "
            f"Risk={report.high_risk_score}/10"
        )

        return report


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON — import this in auditor.py
# ─────────────────────────────────────────────────────────────────────────────
pre_detector = PreDetector()
