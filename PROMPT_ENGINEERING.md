# AuditIQ — Prompt Engineering Decisions

> This document explains every significant prompt engineering decision in the system, why it was made, and what it replaced. Written for engineers who want to understand the design thinking or iterate on the prompts.

---

## Philosophy

The prompts in AuditIQ are not afterthoughts — they are load-bearing engineering artifacts. Each one has a contract: specific inputs, specific output schema, specific failure modes that were observed and mitigated. This document is the changelog and reasoning log for those contracts.

The core principle: **the LLM is the last resort, not the first**. Deterministic Python catches the obvious. Retrieval grounds the legal reasoning. The prompt constrains the output space. The grader evaluates the result. The LLM's job is nuanced judgment in the middle — not pattern matching at the extremes.

---

## 1. The Audit Prompt (Agent 1)

### 1.1 Four-Step Structure

**Decision:** Structure the prompt as four numbered steps (SQL Facts, Pre-Detection, Legal Context, Transcript) rather than a single block of instructions.

**Why:** When given a wall of text, LLMs tend to anchor on whichever section appears most recently before the output schema. By separating concerns into named steps with clear delimiters, each section becomes independently scannable during generation. The model can refer back to "STEP 1" or "STEP 2" explicitly in its reasoning, which makes the reasoning traceable.

**What it replaced:** A single combined context block where sql_facts, legal context, and transcript were merged into one section. This produced reasoning that conflated facts with law with transcript evidence.

---

### 1.2 Pre-Detection Block as STEP 2

**Decision:** The pre-detection report is injected as STEP 2, before the retrieved legal context.

**Why:** Primacy. The LLM reads left to right. If the pre-detection flags are buried after 600 tokens of legal text, they get lower attention weight in the generation. By placing them second — immediately after ground truth facts — they establish the violations the LLM must address before it encounters the retrieved law that should explain them.

**The instruction that matters:**
```
b) Every pre-detected flag — confirm or dispute each with transcript evidence.
```
Without this explicit instruction, models will often acknowledge the pre-detection block in passing but not systematically address each flag. "Confirm or dispute each" forces a structured traversal.

---

### 1.3 Valid Rule IDs Injected Explicitly

**Decision:** All 115 valid rule IDs from `rules_core.json` are injected into every audit prompt.

**Why:** Without this, models produce inconsistent violation ID formats across runs:
- Run 1: `RULE_FALSE_LEGAL_STATUS`
- Run 2: `§ 807(5)`
- Run 3: `FALSE_LEGAL_STATUS`
- Run 4: `False Legal Status`

This inconsistency breaks downstream processing (violation ID normalization, grader rubric, PDF report, database storage). The ID list is a hard constraint on the output vocabulary.

**The instruction that matters:**
```
VALID VIOLATION RULE IDs — use ONLY these in violations_found.
Do NOT use citation strings like '§ 806'. Do NOT invent IDs.
```

**Tradeoff:** Injecting 115 IDs adds ~800 tokens to every prompt. Acceptable cost for format consistency.

---

### 1.4 Speaker Attribution Rules in the Prompt

**Decision:** Even though speaker segmentation runs before the LLM, the prompt explicitly states the attribution rules.

**Why:** The segmenter achieves ~85-92% accuracy. Some turns will be misattributed or marked `[UNKNOWN]`. Without explicit instructions, the LLM will evaluate `[UNKNOWN]` turns and `[DEBTOR]` turns for violations — it has no context for why those labels exist. The speaker attribution rules section gives the LLM a policy for handling ambiguous cases:

```
- FDCPA ONLY regulates the [AGENT]. The [DEBTOR] may say anything.
- Do NOT flag violations based on [DEBTOR] speech — ever.
- If [DEBTOR] says "you threatened to arrest me" → check [AGENT] turns to verify.
- [UNKNOWN] turns: use full context to judge before attributing violations.
```

The last instruction is critical — it tells the LLM to use surrounding context for `[UNKNOWN]` turns rather than defaulting to the debtor or ignoring them.

---

### 1.5 Violation Patterns in the Context Block

**Decision:** Violation patterns from each retrieved rule are included in the context block (up to 5 per rule).

**Why:** This was a gap that existed for the entire v1 system. The enrichment pipeline generates violation_patterns specifically to describe what a violation looks like in analytical terms — bridging the gap between formal legal language and transcript language. But they were stored in ChromaDB and used for BM25 indexing without ever being surfaced to the LLM.

Adding them to `_format_context()`:
```
What a violation of this rule looks like in practice:
  • The collector contacted the consumer before 8:00 AM local time.
  • The collector left a message for the consumer outside of standard call hours.
```

This gives the LLM a worked example of how the statute maps to behavior, not just the statute itself. It improves detection of borderline violations where the transcript language is ambiguous.

---

### 1.6 The "Optional vs Required" Instruction

**Decision:** An explicit rule that "may" or "allowed" in the statute means optional.

```
- "may" or "allowed" = optional. Do not penalize optional disclosures.
```

**Why:** FDCPA has both required disclosures (Mini-Miranda, § 807(11) — mandatory) and permitted behaviors (certain types of contact — allowed but not required). Without this instruction, models penalize agents for not doing things the law merely permits. This produces false positives on compliant calls, eroding trust in the system.

**Example:** § 809(a) gives consumers the right to request debt validation. An agent who doesn't proactively describe this right in detail on the initial call is not violating anything — the right exists regardless. Without the "optional" instruction, models flag this omission.

---

### 1.7 Scoring Rubric in the Prompt

**Decision:** Include an explicit 6-band scoring rubric.

```
10   = Fully compliant, professional, all required disclosures present
8-9  = Minor procedural gap, no substantive violations
5-7  = Moderate issue, borderline behavior
2-4  = Clear violation, not automatically maximum severity
1    = Major violation (threats, harassment, false claims, third-party disclosure)
```

**Why:** Without a rubric, models use implicit scoring heuristics that vary between runs. A call with one technical violation might score 7 in one run and 3 in another. The rubric anchors the scoring distribution. It also explicitly separates the severity dimension ("clear violation") from the scoring dimension ("not automatically maximum severity") — preventing automatic 1/10 scores for every non-zero violation.

---

## 2. The Grader Prompt (Agent 2)

### 2.1 Rubric-Based vs Contradiction-Based

**Decision:** Replace the v1 "contradiction checker" with a rubric-based grader.

**Why the v1 verifier was broken:** The v1 verifier only had access to the retrieved context — 5 rules. When Agent 1 correctly cited § 807 or § 809(a) from its training knowledge, the verifier saw those citations against a context window that didn't contain those sections and flagged them as hallucinations. Case 4 (Emily Blunt) was a correct audit that got overridden incorrectly.

**The v2 grader solves this with two changes:**

First, the explicit hallucination rule:
```
Citing a section NOT in retrieved context is NOT automatically a hallucination.
Only flag if the citation CONTRADICTS the retrieved law or the facts.
```

Second, the grader's job is expanded from "did Agent 1 hallucinate?" to "how well did Agent 1 perform across five criteria?" This makes the grader useful for prompt engineering, not just as a safety net.

---

### 2.2 The Override Rule

**Decision:** `override_verdict=true` should be a last resort, not a default response to uncertainty.

```
Set override_verdict=true ONLY if compliance_passed is demonstrably WRONG.
Do NOT override for minor reasoning gaps.
```

**Why:** If the override fires too easily, the system becomes a two-model debate where the grader always wins. This removes value from Agent 1's reasoning and makes the system more expensive (both models running at full capacity) for no accuracy gain. The override should fire only when Agent 1's verdict is factually wrong — not when its reasoning is imprecise.

**What counts as demonstrably wrong:**
- Agent said PASS but transcript clearly shows arrest threat
- Agent said FAIL but reasoning is about debtor behavior, not agent behavior
- Agent gave 9/10 but violations_found contains three confirmed violations

---

### 2.3 Grader Sees the Pre-Detection Report

**Decision:** The grader receives the pre-detection structured output as part of its context.

**Why:** Without this, the grader has no ground truth to evaluate Agent 1's pre-detection coverage against. It can only compare Agent 1's reasoning to the retrieved law. By giving the grader the pre-detection report, it can specifically check: "Agent 1 was told the Mini-Miranda was absent — did Agent 1 address that? Did Agent 1 flag it as a violation? Did Agent 1's score reflect it?"

This is what makes Criterion B (pre-detection coverage) meaningful rather than aspirational.

---

### 2.4 prompt_improvement_suggestion Field

**Decision:** The grader always returns a single-sentence prompt improvement suggestion.

**Why:** Prompt engineering without systematic feedback is guesswork. By forcing the grader to articulate one improvement per run, every eval cycle produces a data point. These suggestions are logged, reviewed across cases, and used to update the audit prompt.

**The constraint "single sentence" is intentional.** Asking for a list of improvements produces vague items like "add more context" or "be more specific." One sentence forces prioritization — the grader has to identify the single highest-leverage change.

---

## 3. The Rule Enrichment Prompt (offline)

### 3.1 Dual-Persona System Prompt

**Decision:** The enrichment LLM is given two simultaneous roles.

```
ROLE 1 — FDCPA Compliance Attorney
  15 years experience, conservative, defensible in court.

ROLE 2 — Conversational AI Retrieval Engineer
  Specializes in bridging formal legal language to colloquial transcript speech.
```

**Why:** These two roles are in natural tension. The attorney wants precise legal language. The retrieval engineer wants colloquial phrasing. Without both, you get either formal language that doesn't retrieve well on colloquial transcripts, or informal language that misrepresents the legal rule.

The dual-persona forces the LLM to hold both constraints simultaneously. The result is scenario_anchors that are legally accurate but written in the voice of real calls.

---

### 3.2 Field-by-Field Instructions

**Decision:** Each enrichment field has its own dedicated instruction block with BAD/GOOD examples.

**Why:** Without field-specific instructions, the LLM collapses all fields toward the same content. `scenario_anchors` and `violation_patterns` start to look identical. `negative_anchors` become vague ("consumer was okay with it") rather than legally defensible safe-harbor descriptions.

The BAD/GOOD examples are essential — they teach the LLM the distinction between "what this field should contain" and "what it tends to produce without guidance."

---

### 3.3 Self-Check Checklist

**Decision:** A self-check checklist is included at the end of the enrichment prompt.

```
□ Does every scenario_anchor describe THIS rule's violation and NOT another FDCPA rule?
□ Does the explanation accurately represent the statute without narrowing or broadening it?
□ Do the negative_anchors reference ACTUAL statutory exceptions, not invented ones?
□ Are the key_terms pairs genuinely one formal term mapped to one colloquial equivalent?
□ Is every array populated to at least the minimum count specified?
```

**Why:** LLMs in generation mode tend to drift from constraints as the response gets longer. By including a self-check at the end of the prompt, the model "reviews" its own output before finalizing. This reduces the rate of incomplete or off-spec enrichments that `patch_rules.py` has to repair.

---

## 4. What Was Tried and Rejected

### Temperature > 0.1

Higher temperatures (0.3, 0.5) were tested on the audit prompt. They produced more varied reasoning but also more variance in scoring — the same call scored 6 in one run and 3 in another. For a compliance tool where score consistency matters more than creativity, 0.1 is the right tradeoff.

### Chain-of-Thought prompting ("think step by step")

Tested in think_mode. Produces better reasoning traces but also produces non-JSON output — the model explains its reasoning in prose and then produces the JSON, which breaks the streaming parser. The structured prompt (sections A through F in the reasoning field instruction) achieves similar structured reasoning without breaking the output schema.

### Asking the LLM to rate its own confidence

Added a `confidence` field to the output schema in one experiment. Models reliably output 0.9-0.95 regardless of actual certainty. The grader's rubric score provides a more meaningful external confidence estimate than self-reported confidence.

### Asking the verifier to suggest corrections

V1 verifier returned `suggested_corrections` in some experiments. This created a loop where Agent 1 could blame the verifier for any critique and the verifier had no ground truth to evaluate against. The rubric-based grader with explicit criteria is more useful than a free-form correction suggester.

---

## 5. Prompt Iteration Log

| Version | Change | Effect | Eval Cases |
|---|---|---|---|
| v1.0 | Basic audit prompt — sql_facts + context + transcript | Cases 3-5 correct. Case 4 false override from verifier. Violation IDs inconsistent. | 4/5 |
| v1.1 | Added Mini-Miranda explicit instruction | Mini-Miranda detection improved. Score calibration still inconsistent. | 4/5 |
| v2.0 | Four-step structure. Pre-detection block. Valid rule IDs injected. Speaker attribution rules. | All 5 cases correct verdict. Violation IDs consistent. Grader replaces verifier. | 5/5 |
| v2.1 | Violation patterns added to context block. Direct fetch merged into retrieval. | Improved coverage on peripheral violations. | 5/5 |
| v2.2 | Mini-Miranda override score cap changed from 5 → 2. Markdown stream filter added. | Score severity now legally accurate. UX cleaner. | 5/5 |

---

## 6. Evaluation Methodology

**Current approach:** Manual. Each eval case has a known expected outcome (PASS/FAIL, specific violation IDs). After each prompt change, all 5 cases are run via `test_client.py` and results are inspected in `eval_logs/`.

**Metrics tracked per run:**
- `compliance_passed` — binary correctness
- `violations_found` — correct IDs? Any missing? Any spurious?
- `performance_score` — calibrated to severity?
- `grade_report.total_grade` — Agent 1 quality on this run
- `grade_report.prompt_improvement_suggestion` — captured for next iteration

**Next step:** `eval_runner.py` — automated regression across all cases, diff output between prompt versions, trend chart of grader scores over time.