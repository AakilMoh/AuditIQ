import sqlite3
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
os.makedirs("logs", exist_ok=True)

print("Booting LLM Engine via NVIDIA")

# The cloud Embedding
class NvidiaEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        self.client = OpenAI(
            base_url = "https://integrate.api.nvidia.com/v1",
            api_key = os.getenv("NVIDIA_API_KEY")
        )
    def __call__(self, input: Documents) -> Embeddings:
        # Sending the raw text to NVIDIA's embedding model
        response = self.client.embeddings.create(
            model="nvidia/nv-embed-v1",
            input=input,
            encoding_format="float"
        )
        return [r.embedding for r in response.data]

nvidia_ef = NvidiaEmbeddingFunction()

# 1. Loading the Local LLM
llm_client = OpenAI(
    base_url = "https://integrate.api.nvidia.com/v1",
    api_key = os.getenv("NVIDIA_API_KEY")
)

# 2. Connecting to the Local Databases
sql_conn = sqlite3.connect(os.getenv("SQLITE_DB_PATH"))
cursor = sql_conn.cursor()
chroma_client = chromadb.PersistentClient(path=os.getenv("CHROMA_DB_PATH"))
collection = chroma_client.get_collection(
    name="compliance_rules",
    embedding_function=nvidia_ef
)

# Intent Detection
#def detect_intent(transcript):
#    transcript = transcript.lower()

#    legal_words = [
#        "court",
#        "sue",
#        "lawsuit",
#        "legal",
#        "attorney",
#        "judge"
#    ]

#    payment_words = [
#        "balance",
#        "payment",
#        "discount",
#        "settlement",
#        "pay"
#    ]

#    if any(word in transcript for word in legal_words):
#        return "legal_compliance"
#    if any(word in transcript for word in payment_words):
#        return "financial_offer"
    
#    return "general_information"

def detect_categories(transcript):
    transcript = transcript.lower()
    categories = []

    if any(word in transcript for word in ["court", "sue", "lawsuit", "legal"]):
        categories.append("legal_compliance")
    if any(word in transcript for word in ["payment", "balance", "discount", "settlement", "pay"]):
        categories.append("financial_offer")
    if "settled" in transcript:
        categories.append("communication_restriction")
    if not categories:
        categories.append("general_information")

    return categories

# 3.Agentic pipeline
def run_qa_audit(transcript, account_name, debug=False):
    print(f"\nEvaluating Transcript for: {account_name}")

    # Step A: Query SQL
    cursor.execute("SELECT balance, status FROM debtors WHERE name=?", (account_name,))
    row = cursor.fetchone()
    if row is None:
        return json.dumps({"error": "Account not found."})
    sql_facts = f"True Balance: ${row[0]}, status: {row[1]}."

    #intent = detect_intent(transcript)

    #if debug:
    #    print("\n---Intent Detection Debug---")
    #    print(intent)
    #    print("------")

    categories = detect_categories(transcript)

    if debug:
        print("\n---Category Detection Debug---")
        print(categories)
        print("------")

    # Step B: Query ChromaDB
    rag_results = collection.query(
        query_texts=[transcript],
        n_results=5,
        where = {
            "$or": [
                {"category": cat}
                for cat in categories
            ]
        }
    ) or {"documents": [[]]} # Fallback in case of empty results

    docs = rag_results.get('documents', [[]])[0]
    distances = rag_results.get("distances", [[]])[0]

    if debug:
        print("\n---Retrieval Debug---")
        print(f"QUERY: {transcript}\n")

        if docs:
            for i, (doc,dist) in enumerate(zip(docs, distances)):
                print(f"Result {i+1}: {doc} (Distance: {dist})")
                print(f"    DOC: {doc}\n")
        else:
            print("No relevant documents retrieved.")
        
        print("------")

    legal_rules = " | ".join(docs[:3]) if docs else ""

    if debug:
        print("\n---SQL DEBUG---")
        print("ACCOUNT:", account_name)
        print("FACTS:", sql_facts)
        print("------")

    # Step C: LLM Synthesis
    system_prompt = """
    You are a strict QA Auditor. 
    
    Your job:
    Determine if the transcript violates any rule based ONLY on explicit conflicts.

    RULES:
    - Only flag a violation if a rule is clearly broken.
    - "Allowed", "authorized", or "may" means OPTIONAL, not required.
    - Do NOT assume requirements unless explicitly stated.
    - Do NOT invent missing rules.
    - If no rule is clearly violated → compliance_passed = true.

    OUTPUT FORMAT (STRICT):
    Return ONLY valid JSON:
    {{
        "compliance_passed": boolean,
        "reasoning": "short explaination referencing exact rule match"
    }}

    Facts:
    {sql_facts}
    Rules:
    {legal_rules}
    Transcript: 
    "{transcript}"
    """.format(sql_facts=sql_facts, legal_rules=legal_rules, transcript=transcript)
    
    if debug:
        print("\n---LLM INPUT---")
        print(system_prompt)
        print("------")
    
    try:
        # The request to NVIDIA
        response = llm_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user", "content": system_prompt}
            ],
            temperature=0.1,
            max_tokens=200
        )
        
        content = response.choices[0].message.content
        
        if debug:
            print("\n---LLM OUTPUT---")
            print(content)
            print("------")

        llm_result = json.loads(content)
        
        return {
            **llm_result,
            "retrieved_rules": docs,
            "retrieval_scores": distances,
            "sql_facts": sql_facts,
            "account_name": account_name,
            "transcript": transcript
        }
        
    except Exception as e:
        return {"error": str(e), "compliance_passed": False, "raw_output": content if 'content' in locals() else None}
    


test_cases = [
    {
        "name": "Legal Threat Violation",
        "account": "Ali Khan",
        "transcript": "Listen Ali, pay today or I will sue you tomorrow."
    },
    {
        "name": "Settlement Contact Violation",
        "account": "Sara Connor",
        "transcript": "I know you already settled, but can you make another payment?"
    },
    {
        "name": "Correct Settlement Call",
        "account": "Sara Connor",
        "transcript": "Your settlement agreement remains active. Thank you."
    },
    {
        "name": "Balance Discussion",
        "account": "Ali Khan",
        "transcript": "Your outstanding balance is $3200. How would you like to proceed?"
    },
    {
        "name": "Legal Action Mention",
        "account": "Ali Khan",
        "transcript": "Legal action may be considered for unpaid accounts."
    },
    {
        "name": "Pending Legal Action Account",
        "account": "Jane Smith",
        "transcript": "Your account is currently under legal review regarding the outstanding balance."
    },
    {
        "name": "Aggressive Legal Threat",
        "account": "Jane Smith",
        "transcript": "Pay today or we will immediately take you to court."
    },
    {
        "name": "Settlement Offer for Legal Account",
        "account": "Jane Smith",
        "transcript": "We can offer a settlement on your $8900 balance."
    },
    {
        "name": "Balance Inquiry Legal Account",
        "account": "Jane Smith",
        "transcript": "Your balance is currently $8900. Would you like to discuss payment options?"
    }
]

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"logs/retrieval findings_{timestamp}.txt"

with open(log_file, "w", encoding="utf-8") as f:
    f.write("RETRIEVAL TEST RESULTS\n")
    f.write("=" *60 + "\n")
    f.write(f"Generated: {datetime.now()}\n\n")

print("\n--- Running Test Cases ---")

for case in test_cases:

    result = run_qa_audit(
        transcript=case["transcript"],
        account_name=case["account"],
        debug=True
    )

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\nCASE: {case['name']}\n")
        f.write("-" * 50 + "\n")

        f.write(f"Account: {case['account']}\n")
        f.write(f"Transcript:\n{case['transcript']}\n\n")

        f.write("Result:\n")
        f.write(str(result))
        f.write("\n\n")

# 4. Testing the Agent
#bad_call = "Listen Ali, you owe us $5000. Pay now or I sue you tomorrow."
#good_call = "Hi Sarah, your settlement is in place. Have a good day."

#print("\n--- Test 1: The Violation ---")
#print(run_qa_audit(bad_call, "Ali Khan", debug=True))

#print("\n--- Test 2: The Compliant Call ---")
#print(run_qa_audit(good_call, "Sara Connor", debug=True))




