import sqlite3
import chromadb
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

print("Booting LLM Engine via NVIDIA")

# 1. Loading the Local LLM
client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = os.getenv("NVIDIA_API_KEY")
)

# 2. Connecting to the Local Databases
sql_conn = sqlite3.connect(os.getenv("SQLITE_DB_PATH"))
cursor = sql_conn.cursor()
chroma_client = chromadb.PersistentClient(path=os.getenv("CHROMA_DB_PATH"))
collection = chroma_client.get_collection(name="compliance_rules")

# 3.Agentic pipeline
def run_qa_audit(transcript, account_name):
    print(f"\nEvaluating Transcript for: {account_name}")

    # Step A: Query SQL
    cursor.execute("SELECT balance, status FROM debtors WHERE name=?", (account_name,))
    row = cursor.fetchone()
    if row is None:
        return json.dumps({"error": "Account not found."})
    sql_facts = f"True Balance: ${row[0]}, status: {row[1]}."

    # Step B: Query ChromaDB
    rag_results = collection.query(
        query_texts=[transcript],
        n_results=2
    ) or {"documents": [[]]} # Fallback in case of empty results

    docs = rag_results.get('documents', [[]])[0]
    legal_rules = " | ".join(docs) if docs else ""

    #if rag_results and rag_results['documents'] and rag_results['documents'][0]:
    #    legal_rules = " | ".join(rag_results['documents'][0])
    #else:
    #    legal_rules = ""
    
    # Step C: LLM Synthesis
    system_prompt = f"""
    You are a strict QA Auditor. Compare the transcript against the facts and rules.
    Output ONLY a JSON object with keys: "compliance_passed" (boolean) and "reasoning" (string).
    
    Facts: {sql_facts}
    Rules: {legal_rules}
    Transcript: "{transcript}"
    """
    
    try:
        # The request to NVIDIA
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user", "content": system_prompt}
            ],
            temperature=0.1,
            max_tokens=200
        )
        
        content = response.choices[0].message.content
        return json.loads(content)
        
    except Exception as e:
        return {"error": str(e), "compliance_passed": False, "raw_output": content if 'content' in locals() else None}

# 4. Testing the Agent
bad_call = "Listen Ali, you owe us $5000. Pay now or I sue you tomorrow."
good_call = "Hi Sarah, your settlement is in place. Have a good day."

print("\n--- Test 1: The Violation ---")
print(run_qa_audit(bad_call, "Ali Khan"))

print("\n--- Test 2: The Compliant Call ---")
print(run_qa_audit(good_call, "Sara Connor"))




