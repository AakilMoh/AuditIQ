import json
import os
from enrich_rules import enrich_rule_metadata


JSON_PATH = "data/rules_core.json"


REQUIRED_FIELDS = [
    "explanation",
    "scenario_anchors",
    "violation_patterns",
    "key_terms",
    "negative_anchors"
]


MINIMUM_COUNTS = {
    "scenario_anchors": 3,
    "violation_patterns": 2,
    "key_terms": 3,
    "negative_anchors": 2
}


GENERIC_BAD_PHRASES = [
    "this is a violation",
    "not allowed",
    "illegal",
    "this violates the rule",
    "this is prohibited"
]


def contains_generic_content(items):
    """
    Detect lazy LLM filler responses.
    """

    for item in items:

        if not isinstance(item, str):
            continue

        cleaned = item.lower().strip()

        for bad in GENERIC_BAD_PHRASES:
            if bad in cleaned:
                return True

    return False



def validate_key_terms(key_terms):
    """
    Validate BM25 mapping pairs.
    Expected:
    [
      ["formal term", "street term"]
    ]
    """

    for pair in key_terms:

        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not isinstance(pair[1], str)
            or not pair[0].strip()
            or not pair[1].strip()
        ):
            return False

    return True



def is_incomplete(rule):
    """
    Integrity gatekeeper.
    Detects missing, empty, malformed,
    or low-quality enrichment.
    """


    # 1. Missing required fields

    for field in REQUIRED_FIELDS:

        if field not in rule:
            return True



    # 2. Explanation validation

    explanation = rule.get("explanation", "")

    if (
        not isinstance(explanation, str)
        or len(explanation.strip()) < 20
    ):
        return True



    # 3. Array capacity validation

    for field, minimum in MINIMUM_COUNTS.items():

        value = rule.get(field)

        if (
            not isinstance(value, list)
            or len(value) < minimum
        ):
            return True



    # 4. key_terms schema validation

    if not validate_key_terms(rule["key_terms"]):
        return True



    # 5. Detect generic LLM filler

    if contains_generic_content(
        rule["scenario_anchors"]
    ):
        return True


    return False





def atomic_save(data, path):
    """
    Prevent JSON corruption.
    Writes temp file then swaps.
    """

    temp_path = path + ".tmp"


    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


    os.replace(
        temp_path,
        path
    )





def run_delta_patch():

    if not os.path.exists(JSON_PATH):

        print(
            f"❌ Target file missing: {JSON_PATH}"
        )

        return



    with open(
        JSON_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        rules = json.load(f)



    print(
        "🔍 Starting enrichment integrity scan...\n"
    )


    patched_count = 0
    skipped_count = 0
    failed_count = 0



    for index, rule in enumerate(rules, start=1):


        rule_id = rule.get(
            "id",
            f"UNKNOWN_{index}"
        )


        if is_incomplete(rule):


            print(
                f"🛠️ Repairing [{index}] {rule_id}"
            )


            payload = enrich_rule_metadata(rule)



            if (
                payload
                and isinstance(payload, dict)
            ):


                for field in REQUIRED_FIELDS:


                    incoming = payload.get(field)

                    existing = rule.get(field)


                    if incoming:

                        rule[field] = incoming

                    elif existing:

                        rule[field] = existing

                    else:

                        rule[field] = (
                            ""
                            if field == "explanation"
                            else []
                        )



                patched_count += 1


                print(
                    f"  ✅ Repaired "
                    f"(Anchors: {len(rule['scenario_anchors'])}, "
                    f"Terms: {len(rule['key_terms'])})"
                )


            else:

                failed_count += 1

                print(
                    "  ❌ LLM repair failed"
                )



        else:

            skipped_count += 1



    atomic_save(
        rules,
        JSON_PATH
    )



    print(
        "\n=================================================="
    )

    print(
        "🎉 DATA INTEGRITY PATCH MATRIX COMPLETE"
    )

    print(
        "=================================================="
    )

    print(
        f"✅ Clean / Skipped     : {skipped_count}"
    )

    print(
        f"🛠️ Repaired            : {patched_count}"
    )

    print(
        f"❌ Failed              : {failed_count}"
    )

    print(
        f"📊 Total Rules Checked : {len(rules)}"
    )

    print(
        "=================================================="
    )





if __name__ == "__main__":

    run_delta_patch()