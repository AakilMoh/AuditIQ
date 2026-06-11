import sqlite3
import os
import logging
from datetime import datetime
from app.core.config import SQLITE_DB_PATH
from app.services.transcriber import transcribe_call
from app.services.auditor import run_qa_audit

#Dual Output Logging
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("orchestrator")
logger.setLevel(logging.INFO)

#File Handler
file_handler = logging.FileHandler(f"logs/orchestrator_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [Orchestrator] %(message)s'))

#Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('\n[Orchestrator] %(message)s'))

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
# ---------------------------------------------------------

def process_call(audio_path: str, debtor_id: int, agent_id: int, auditor_id: int):
    logger.info(f"Initiating QA Pipeline for Audio: {audio_path}")

    #Connecting to DB to get the Debtor's name
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM debtors WHERE debtor_id = ?", (debtor_id,))
    row = cursor.fetchone()
    if not row:
        logger.error("Debtor ID not found in the database.")
        return "[!] Error: Debtor ID not found in the database."
    account_name = row[0]

    #Transcribing the Audio
    logger.info("Sending to GROQ Whisper")
    transcript = transcribe_call(audio_path)

    if "Error" in transcript:
        logger.error(f"Transcription failed: {transcript}")
        return transcript
    
    #Auditing the transcript
    logger.info("Passing Transcript to Llama 3.1 70B")
    audit_result = run_qa_audit(transcript, account_name)

    if "error" in audit_result:
        logger.error(f"Audit Error: {audit_result['error']}")
        return f"[!] Audit Error: {audit_result['error']}"
    
    #Saving to the call logs
    logger.info("Saving Audit Trail to SQLite Vault...")

    passed = 1 if audit_result.get("compliance_passed") else 0
    score = audit_result.get("performance_score", 0)
    reasoning = audit_result.get("reasoning", "")
    prompt_used = audit_result.get("llm_prompt_used", "")

    try:
        cursor.execute('''
            INSERT INTO call_logs (
                debtor_id, agent_id, auditor_id, cloud_audio_uri, 
                transcript, llm_prompt, compliance_passed, 
                ai_performance_score, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            debtor_id, agent_id, auditor_id, audio_path, 
            transcript, prompt_used, passed, score, reasoning
        ))
        conn.commit()

        #Building the final message
        success_msg = (
            f"\n{'='*60}\n"
            f"✅ PIPELINE SUCCESS: Call Saved to Database\n"
            f"{'='*60}\n"
            f"Customer Name : {account_name}\n"
            f"Agent Score   : {score}/10\n"
            f"Compliance    : {'PASSED' if passed else 'FAILED'}\n"
            f"Transcript    : '{transcript}'\n"
            f"AI Reasoning  : {reasoning}\n"
            f"Verifier Notes : {audit_result.get('verification_notes', 'N/A')}\n"
            f"{'='*60}"
        )
        logger.info(success_msg)

    except sqlite3.IntegrityError as e:
        logger.warning(f"Database Error: {str(e)} -> (You already audited this exact file!)")
    finally:
        conn.close()
    
    return "Pipeline execution complete."

#Execution
if __name__ == "__main__":
    test_audio = "compliant_call.mp3"
    
    if os.path.exists(test_audio):
        process_call(
            audio_path=test_audio, 
            debtor_id=3, 
            agent_id=1, 
            auditor_id=1
        )
    else:
        logger.error(f"Please place an audio file named '{test_audio}' to test")