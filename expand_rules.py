import json
import os
import chromadb
from app.core.config import llm_client, PRIMARY_AUDITOR_MODEL, CHROMA_DB_PATH

#Defining the LLM extraction function
def extract_rules_from_text(raw_legal_text, base_section_id):
    prompt = f"""You are an elite Legal Data Engineer. Read the following raw FDCPA legal text and extract EVERY distinct compliance rule into a structured JSON array.
    
    RAW TEXT (Source: {base_section_id}):
    {raw_legal_text}

    RULES FOR EXTRACTION:
    1. Extract every distinct rule, prohibition, or requirement. Do not skip subsections.
    2. Output strictly valid JSON. 
    3. Return an array of objects using this exact schema:
    [
      {{
        "id": "RULE_DESCRIPTIVE_NAME_IN_UPPER_SNAKE_CASE",
        "type": "compliance_rule",
        "rule": "The concise requirement or prohibition",
        "severity": "low", "medium", "high", or "critical",
        "mapped_sections": ["{base_section_id}"],
        "sub_section_citation": "e.g., § 805(b)",
        "explanation": "A clear, 1-sentence explanation of what this means for a debt collector."
      }}
    ]
    """

    try:
        response = llm_client.chat.completions.create(
            model=PRIMARY_AUDITOR_MODEL,
            messages=[
                {"role": "system", "content": "You output strictly valid JSON arrays without markdown blocks or conversational text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2048
        )
        
        result_text = response.choices[0].message.content or "[]"
        
        # Safely strip markdown code blocks if the model includes them
        start_idx = result_text.find('[')
        end_idx = result_text.rfind(']') + 1
        if start_idx != -1 and end_idx != 0:
            clean_json = result_text[start_idx:end_idx]
            return json.loads(clean_json)
        else:
            return json.loads(result_text)
        
    except Exception as e:
        print(f"Extraction Error on {base_section_id}: {e}")
        return []

#Defining the append function which is safe so exisiting rules are exempted
def append_to_rules_core(new_rules, filepath="data/rules_core.json"):
    #loading exisiting rules to prevent overwriting them
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                existing_rules = json.load(f)
            except json.JSONDecodeError:
                existing_rules = []
    else:
        existing_rules = []
    
    #Creating a set of exisiting citations to prevent duplicates
    existing_citations = {r.get("sub_section_citation") for r in existing_rules if r.get("sub_section_citation")}

    added_count = 0
    for rule in new_rules:
        citation = rule.get("sub_section_citation")
        if citation and citation not in existing_citations:
            existing_rules.append(rule)
            existing_citations.add(citation)
            added_count += 1
            print(f"Appended New Rule: {citation} - {rule.get('id')}")
        else:
            pass # Skip as it's a duplicate
        
    # Save safely back to JSON
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(existing_rules, f, indent=2)
        
    return added_count

#The main automation loop
def build_automated_rule_engine():
    print("Booting Automated Knowledge Extraction Engine\n")

    # Connect to existing ChromaDB Vault
    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        collection_a = chroma_client.get_collection(name="fdcpa_raw_text")
    except Exception as e:
        print("Could not find 'fdcpa_raw_text' collection. Make sure ChromaDB is populated.")
        return

    # Pull ALL raw chunks already processed from the PDF
    raw_data = collection_a.get()
    chunks = raw_data.get('documents', [])
    ids = raw_data.get('ids', [])
    
    if not chunks:
        print("No raw text chunks found in the database.")
        return
    
    print(f"Found {len(chunks)} raw legal text chunks in ChromaDB. Starting sequential extraction\n")

    total_added = 0
    for chunk_id, chunk_text in zip(ids, chunks):
        print(f"Extracting rules from chunk: {chunk_id}")
        
        extracted_rules = extract_rules_from_text(chunk_text, base_section_id=chunk_id)
        
        if extracted_rules:
            added = append_to_rules_core(extracted_rules, filepath="data/rules_core.json")
            total_added += added
        else:
            print(f"No rules extracted from {chunk_id}.")
            
    print(f"\nKnowledge expansion complete! Added {total_added} new rules.")
    print("Rules engine is now fully synchronized.")

if __name__ == "__main__":
    build_automated_rule_engine()