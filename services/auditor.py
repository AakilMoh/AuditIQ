import sqlite3
import chromadb
import json
import os
import logging
from datetime import datetime
from core.config import SQLITE_DB_PATH, CHROMA_DB_PATH, nvidia_ef, llm_client

#-----------------------------------------------------------------------------------------------------------------
#Ensuring the logs directory exists
os.makedirs("logs", exist_ok=True)

#setting up a logger that writes to a file instead of the terminal
logger = logging.getLogger("auditor")
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(f"logs/auditor_trace_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

if not logger.handlers:    
    logger.addHandler(file_handler)

#-----------------------------------------------------------------------------------------------------------------

#Connecting to the Local Databases
sql_conn = sqlite3.connect(SQLITE_DB_PATH)
cursor = sql_conn.cursor()

chroma_client = chromadb.PersistentClient(CHROMA_DB_PATH)
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
    logger.info(f"\nEvaluating Transcript for: {account_name}")

    # Step A: Query SQL
    cursor.execute("SELECT balance, status FROM debtors WHERE name=?", (account_name,))
    row = cursor.fetchone()
    if row is None:
        return json.dumps({"error": "Account not found."})
    sql_facts = f"True Balance: ${row[0]}, status: {row[1]}."

    categories = detect_categories(transcript)

    # Step B: Query ChromaDB
    if len(categories) == 1:
        where_filter = {"category": categories[0]}
    else:
        where_filter = {
            "$or" : [
                {"category": cat}
                for cat in categories
            ]
        }

    rag_results = collection.query(
        query_texts=[transcript],
        n_results=5,
        where=where_filter
    ) or {"documents": [[]]} # Fallback in case of empty results

    docs = rag_results.get('documents', [[]])[0]
    distances = rag_results.get("distances", [[]])[0]

    legal_rules = " | ".join(docs[:3]) if docs else ""

    if debug:
        logger.debug("---Retrieval Debug---")
        logger.debug(f"QUERY: {transcript}")

        if docs:
            for i, (doc,dist) in enumerate(zip(docs, distances)):
                logger.debug(f"Result {i+1}: {doc} (Distance: {dist})")
        else:
            logger.debug("No relevant documents retrieved.")
        logger.debug("--------------")

        logger.debug("---SQL DEBUG---")
        logger.debug(f"ACCOUNT: {account_name}")
        logger.debug(f"FACTS: {sql_facts}")
        logger.debug("--------------")

    # Step C: LLM Synthesis
    system_prompt = """
    You are a strict QA Auditor for a debt collection agency.
    
    Your job:
    1. Determine if the transcript violates any rule based ONLY on explicit conflicts.
    2. Score the agent's performance on a scale of 1 to 10.
       - A major compliance violation is an automatic 1.
       - A polite, compliant call with no violations is a 10.

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
        "performance_score": integer,
        "reasoning": "short explanation referencing exact rule match"
    }}

    Facts:
    {sql_facts}
    Rules:
    {legal_rules}
    Transcript: 
    "{transcript}"
    """.format(sql_facts=sql_facts, legal_rules=legal_rules, transcript=transcript)
    
    if debug:
        logger.debug("---LLM INPUT---")
        logger.debug(system_prompt)
        logger.debug("--------------")
    
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
            logger.debug("---LLM OUTPUT---")
            logger.debug(content)
            logger.debug("--------------")

        llm_result = json.loads(content)
        
        logger.info(f"Audit Complete. Score: {llm_result.get('performance_score')}")

        return {
            **llm_result,
            "retrieved_rules": docs,
            "retrieval_scores": distances,
            "sql_facts": sql_facts,
            "account_name": account_name,
            "transcript": transcript,
            "llm_prompt_used": system_prompt
        }
        
    except Exception as e:
        logger.error(f"LLM Processing Error: {str(e)}")
        return {"error": str(e), "compliance_passed": False, "raw_output": content if 'content' in locals() else None}


