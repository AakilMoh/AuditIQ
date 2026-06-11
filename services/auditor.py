import sqlite3
import chromadb
import json
import os
import logging
from datetime import datetime
from core.config import SQLITE_DB_PATH, CHROMA_DB_PATH, nvidia_ef, llm_client
from services.hybrid_retriever import LegalRetriever

#-----------------------------------------------------------------------------------------------------------------
#Ensuring the logs directory exists
os.makedirs("logs", exist_ok=True)

#setting up a logger that writes to a file instead of the terminal
logger = logging.getLogger("auditor")
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(f"logs/auditor_trace_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('\n[Auditor] %(message)s'))

if not logger.handlers:    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

#-----------------------------------------------------------------------------------------------------------------

#Connecting to the Local Databases
sql_conn = sqlite3.connect(SQLITE_DB_PATH)
cursor = sql_conn.cursor()

# Initializing new Advanced Hybrid Search
retriever = LegalRetriever()

#Agentic pipeline
def run_qa_audit(transcript, account_name, debug=False):
    logger.info(f"\nEvaluating Transcript for: {account_name}")

    # Step A: Query SQL
    cursor.execute("SELECT balance, status FROM debtors WHERE name=?", (account_name,))
    row = cursor.fetchone()
    if row is None:
        logger.error(f"Account {account_name} not found in SQL database.")
        return {"error": "Account not found."}

    sql_facts = f"True Balance: ${row[0]}, status: {row[1]}."

    if debug:
        logger.debug("---SQL DEBUG---")
        logger.debug(f"ACCOUNT: {account_name}")
        logger.debug(f"FACTS: {sql_facts}")
        logger.debug("--------------")

    # Step B: Query Hybrid Retriever (Dense + Sparse + Reranker)
    logger.info("Fetching relevant federal law via Hybrid Retriever")
    retrieved_context = retriever.retrieve_context(transcript, top_k=3)

    # Format context cleanly for the LLM
    context_string = ""
    for i, rule in enumerate(retrieved_context):
        context_string += f"--- Rule {i+1}: {rule['rule_id']} ---\n"
        context_string += f"Citation: {rule['citation']}\n"
        context_string += f"Rule Summary: {rule['rule_statement']}\n"
        context_string += f"Architect Explanation: {rule['explanation']}\n"
        context_string += f"Raw Federal Law Text:\n{rule['raw_federal_text']}\n\n"

    if debug:
        logger.debug("---Retrieval Debug---")
        logger.debug(context_string)
        logger.debug("--------------")

    # Step C: Agent 1 (The Primary Auditor - Llama 70B)
    logger.info("Agent 1 (Llama-70B) is analyzing the transcript")
    audit_prompt = f"""You are an elite QA Compliance Auditor for a massive debt collection agency.
    
    YOUR MISSION:
    1. Cross-Reference Facts: Compare the agent's spoken claims in the transcript against the SQL FACTS. If the agent misrepresents the balance or account status, flag it.
    2. Enforce the Law: Evaluate the agent's behavior strictly against the provided FDCPA LEGAL CONTEXT. 
    3. Score the Call: Determine the final compliance status and assign a performance score.

    SQL FACTS (Account Reality):
    {sql_facts}

    LEGAL CONTEXT (Federal Law):
    {context_string}

    TRANSCRIPT:
    "{transcript}"

    RULES:
    - Only flag a violation if a federal rule is clearly broken or if the agent lied about the SQL facts.
    - YOUR REASONING MUST:
        a) Explicitly verify if the required Mini-Miranda (debt collector disclosure) was spoken.
        b) Confirm if the balance stated matches the SQL FACTS.
        c) Explicitly state that no specific rule (like Harassment § 806 or Attorney Rep § 805) was violated.
    - If the call is compliant, detail exactly how it met the requirements of § 809(a) and § 807.
    - "Allowed" or "may" means OPTIONAL, not required. Do not penalize for missing optional disclosures.
    - If no rule is clearly violated and facts are accurate → compliance_passed = true.
    - A major compliance violation (threats, harassment, lying) is an automatic score of 1.

    Respond ONLY with a raw JSON object using this exact schema:
    {{
        "compliance_passed": boolean,
        "performance_score": integer,
        "violations_found": ["RULE_ID_1", "RULE_ID_2"],
        "reasoning": "Detailed explanation citing the specific FDCPA rules and SQL facts used to make this decision."
    }}
    """
    
    try:
        # The request to NVIDIA
        response_1 = llm_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user", "content": audit_prompt}
            ],
            temperature=0.0,
            max_tokens=1024
        )
        
        audit_result = json.loads(response_1.choices[0].message.content)

        # Step D: Agent 2 (The Verifier - Llama 8B)
        logger.info("Agent 2 (Llama-8B) is checking Agent 1 for hallucinations")

        verify_prompt = f"""You are a strict Legal Verifier. 
        An AI Auditor just reviewed a transcript and provided this reasoning:
        "{audit_result.get('reasoning', '')}"
        
        Here is the actual Federal Law that was retrieved:
        {context_string}
        
        Does the AI Auditor's reasoning directly contradict the provided Federal Law? 
        If the auditor hallucinated a rule or made up a citation, flag it.
        Respond ONLY with a raw JSON object:
        {{
            "contradiction_found": boolean,
            "verification_notes": "Explanation of why the logic is valid or contradictory."
        }}
        """

        response_2 = llm_client.chat.completions.create(
            model="meta/llama-3.1-8b-instruct",
            messages=[
                {"role": "system", "content": "You output strictly valid JSON without markdown blocks."},
                {"role": "user", "content": verify_prompt}
            ],
            temperature=0.0,
            max_tokens=800
        )
        
        verify_result = json.loads(response_2.choices[0].message.content)

        # Step E: Contradiction Handling & Final Output
        if verify_result.get("contradiction_found"):
            logger.warning("CONTRADICTION DETECTED! Agent 2 caught a hallucination. Nullifying score.")
            audit_result["compliance_passed"] = False
            audit_result["performance_score"] = 1
            audit_result["reasoning"] = f"[REJECTED BY VERIFIER]: {verify_result['verification_notes']} | Original Logic: {audit_result.get('reasoning')}"

        logger.info(f"Audit Complete. Final Score: {audit_result.get('performance_score')}")
        
        return {
            **audit_result,
            "verification_notes": verify_result.get("verification_notes"),
            "retrieved_rules": [rule['rule_id'] for rule in retrieved_context],
            "sql_facts": sql_facts,
            "account_name": account_name,
            "transcript": transcript,
            "llm_prompt_used": audit_prompt
        }

    except Exception as e:
        logger.error(f"LLM Processing Error: {str(e)}")
        return {"error": str(e), "compliance_passed": False}


