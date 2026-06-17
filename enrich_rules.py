import json
import os
import sys
from app.core.config import llm_client, PRIMARY_AUDITOR_MODEL

def enrich_rule_metadata(rule):
    """
    Feeds a single rule into Llama 70B using the robust dual-persona prompt
    to generate scenario anchors, violation patterns, key terms, and negative anchors.
    """
    
    # Dynamically scale quotas based on severity/complexity to avoid LLM panic filler
    severity = rule.get("severity", "medium").lower()
    if severity in ["critical", "high"]:
        anchor_count = "10 to 15"
        pattern_count = "6 to 8"
        terms_count = "10 to 15"
    else:
        anchor_count = "4 to 8"
        pattern_count = "3 to 5"
        terms_count = "5 to 10"

    prompt = f"""You are a dual-expertise specialist with two roles that must NEVER conflict:

ROLE 1 — FDCPA Compliance Attorney
You have 15 years of experience litigating Fair Debt Collection Practices Act cases.
You know every statutory nuance, every exception, every safe harbor clause.
Your legal interpretations are conservative and defensible in court.

ROLE 2 — Conversational AI Retrieval Engineer
You specialize in making legal rules retrievable from messy, real-world phone call transcripts.
You know that collectors say "your account" not "the debt", debtors say "stop calling me" not
"cease communication", and roommates appear as "the guy who answered" not "third party".

YOUR PRIME DIRECTIVE:
Enrich the retrieval fields WITHOUT EVER weakening, broadening, or misrepresenting the legal rule.

OUTPUT CONTRACT:
- Return ONLY a valid JSON object. Do not include markdown code blocks (like ```json).
- Every string must be properly escaped.
- Arrays must never be empty.
- Do not add fields not specified in the schema.
- Do not modify or return the fields: id, type, rule, mapped_sections, sub_section_citation, severity, rule_type.

RULE TO ENRICH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ID:                  {rule.get('id')}
STATUTORY TEXT:      {rule.get('rule')}
CURRENT EXPLANATION: {rule.get('explanation')}
SEVERITY:            {rule.get('severity')}
RULE TYPE:           {rule.get('rule_type', 'commission')}
CITATION:            {rule.get('sub_section_citation')}
MAPPED SECTIONS:     {rule.get('mapped_sections')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULE TYPE GUIDANCE:
If this is a COMMISSION rule, the violation is something the collector DID. scenario_anchors must describe active collector behavior heard in the transcript.
If this is an OMISSION rule, the violation is something the collector FAILED to do.

DYNAMIC CAPACITY GUIDANCE:
Based on this rule's severity level, you must generate:
- Approximately {anchor_count} unique scenario_anchors.
- Approximately {pattern_count} unique violation_patterns.
- Approximately {terms_count} unique key_terms synonym pairs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIELD-BY-FIELD INSTRUCTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] "explanation"
    PURPOSE: The primary semantic anchor for the vector embedding. Paraphrase in clean, plain English without legal jargon. Max 2-3 sentences.
    Never use the phrase "debt collector must" — use "collectors are prohibited from" or "collectors are required to".
    Must NOT narrow or broaden the rule scope.

[2] "scenario_anchors"
    PURPOSE: Colloquial phrases that would appear verbatim or near-verbatim in a real call transcript when this rule is being violated.
    - Write each anchor as a natural spoken phrase (1-2 sentences), NOT an analytical description.
    - Mix first-person collector speech and third-person transcript narratives.
    - Cycle through realistic variations: roommates, spouses, parents, coworkers, shared voicemail, speakerphone exposure, etc.
    - Do NOT write abstract summaries. (e.g., BAD: "collector disclosed info". GOOD: "her roommate answered and I told him the balance").

[3] "violation_patterns"
    PURPOSE: Analytical third-person professional descriptions of the violation as an auditor would write them in a formal report.
    - Professional tone, past tense. Focus on specific mechanics of the violation.

[4] "key_terms"
    PURPOSE: Explicit formal-term to street-language synonym pairs for BM25 mapping.
    - Format: array of 2-element arrays: [["formal legal term", "street conversational equivalent"]]
    - Examples: [["third party", "roommate"]], [["debt", "balance"]], [["prior consent", "permission"]]

[5] "negative_anchors"
    PURPOSE: Phrases describing situations that LOOK like a violation on the surface but are completely legal due to safe harbors or exceptions.
    - Must reflect actual statutory parameters (e.g., consumer explicitly authorized their spouse on the line). Generate 4 to 6 entries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-CHECK BEFORE OUTPUTTING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
□ Does every anchor isolated to this rule's exact mechanics and not neighboring ones?
□ Are all array fields cleanly matching their target schemas?
□ Output contains absolutely zero trailing commas or extra commentary keys?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT THE FOLLOWING JSON STRUCTURE ONLY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "explanation": "<your enriched explanation here>",
  "scenario_anchors": [
    "<anchor 1>",
    "<anchor 2>"
  ],
  "violation_patterns": [
    "<pattern 1>",
    "<pattern 2>"
  ],
  "key_terms": [
    ["<legal_term>", "<conversational_term>"]
  ],
  "negative_anchors": [
    "<negative anchor 1>"
  ]
}}
"""

    try:
        response = llm_client.chat.completions.create(
            model=PRIMARY_AUDITOR_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise data engine that outputs only valid, raw JSON objects matching the structural contract precisely. No markdown wrapper blocks."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.15
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Strip code blocks if Llama accidentally spills markdown wrappers
        if result_text.startswith("```"):
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end != 0:
                result_text = result_text[start:end]
                
        enriched_data = json.loads(result_text)
        return enriched_data
        
    except Exception as e:
        print(f"\n❌ Failover during LLM call on rule {rule.get('id')}: {e}")
        return None

def execute_enrichment_pipeline():
    json_path = "data/rules_core.json"
    
    if not os.path.exists(json_path):
        print(f"❌ Target path '{json_path}' not found. Verify your file structure.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        master_rules = json.load(f)

    print(f"🧬 Initializing Metadata Enrichment Matrix on {len(master_rules)} legal entities...")
    print("⚡ Utilizing Production-Grade Dual-Persona Structural Controls...\n")

    successful_enrichments = 0
    for idx, rule in enumerate(master_rules):
        rule_id = rule.get("id")
        print(f"⚙️  [{idx+1}/{len(master_rules)}] Processing Rule: {rule_id}...", end="", flush=True)
        
        # Execute the robust prompt schema generation
        payload = enrich_rule_metadata(rule)
        
        if payload and isinstance(payload, dict):
            # Inject new metadata vectors safely without overriding core elements
            rule["explanation"] = payload.get("explanation", rule.get("explanation"))
            rule["scenario_anchors"] = payload.get("scenario_anchors", [])
            rule["violation_patterns"] = payload.get("violation_patterns", [])
            rule["key_terms"] = payload.get("key_terms", [])
            rule["negative_anchors"] = payload.get("negative_anchors", [])
            
            successful_enrichments += 1
            print(" [SUCCESS] (Anchors: {}, KeyTerms: {})".format(
                len(rule["scenario_anchors"]), len(rule["key_terms"])
            ))
        else:
            print(" [SKIPPED due to generation fault]")
            
        # Intermediate flash save every 5 items to protect data against pipeline crashes
        if idx % 5 == 0 or idx == len(master_rules) - 1:
            with open(json_path, "w", encoding="utf-8") as out_f:
                json.dump(master_rules, out_f, indent=2, ensure_ascii=False)

    print(f"\nPipeline complete! Successfully enriched {successful_enrichments}/{len(master_rules)} rules with high-fidelity semantic capabilities.")

if __name__ == "__main__":
    execute_enrichment_pipeline()