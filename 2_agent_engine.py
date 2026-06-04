import sqlite3
import chromadb
import json
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# 1. Loading the Local LLM
print("Booting LLM Engine - CPU Mode")
model_path = hf_hub_download(
    repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    local_dir="./models" # Caching inside my local folder
)

llm = Llama(model_path=model_path, n_ctx=2048, verbose=False)

# 2. Connecting to the Local Databases
sql_conn = sqlite3.connect("data/collectiq.sqlite")
cursor = sql_conn.cursor()
chroma_client = chromadb.PersistentClient(path="data/chroma_db")
collection = chroma_client.get_collection(name="compliance_rules")

# 3.Agentic pipeline
def run_qa_audit(transcript, account_name):
    print(f"\nEvaluating Transcript for: {account_name}")

    # Step A: Query SQL
    cursor.execute("SELECT balance, status FROM debtors WHERE name=?", (account_name,))
    row = cursor.fetchone()
    if not row:
        return "Account not found."
    sql_facts = f"True Balance: ${row[0]}, status: {row[1]}."

    # Step B: Query ChromaDB
    rag_results = collection.query(query_texts=[transcript], n_results=2)
    if rag_results and rag_results['documents'] and rag_results['documents'][0]:
        legal_rules = " | ".join(rag_results['documents'][0])
    else:
        legal_rules = ""
    
    # Step C: LLM Synthesis
    system_prompt = f"""
    You are a strict QA Auditor. Compare the transcript against the facts and rules.
    Output ONLY a JSON object with keys: "compliance_passed" (boolean) and "reasoning" (string).
    
    Facts: {sql_facts}
    Rules: {legal_rules}
    Transcript: "{transcript}"
    """
    
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": "You output strictly valid JSON."},
            {"role": "user", "content": system_prompt}
        ],
        max_tokens=200,
        temperature=0.1 # Keeps the logic deterministic and robotic
    )
    
    return response['choices'][0]['message']['content']

# 4. Testing the Agent
bad_call = "Listen Ali, you owe us $5000. Pay now or I sue you tomorrow."
good_call = "Hi Sarah, your settlement is in place. Have a good day."

print("\n--- Test 1: The Violation ---")
print(run_qa_audit(bad_call, "Ali Khan"))

print("\n--- Test 2: The Compliant Call ---")
print(run_qa_audit(good_call, "Sarah Connor"))




