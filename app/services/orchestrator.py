# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR — fixed to consume the generator correctly
# ─────────────────────────────────────────────────────────────────────────────
# v1 was broken: called run_qa_audit() and treated it as a dict return.
# run_qa_audit is a generator that yields events — must be iterated.
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3
import os
import json
import logging
from datetime import datetime
from app.core.config      import SQLITE_DB_PATH
from app.services.transcriber import transcribe_call
from app.services.auditor     import run_qa_audit

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("orchestrator")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = logging.FileHandler(
        f"logs/orchestrator_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - [Orchestrator] %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("\n[Orchestrator] %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(ch)


def process_call(audio_path: str, debtor_id: int, agent_id: int, auditor_id: int):
    """
    Batch/CLI mode pipeline. Runs transcription + audit + DB save synchronously.
    Fixed: now correctly iterates run_qa_audit() as a generator.
    """
    logger.info(f"Initiating QA Pipeline for: {audio_path}")

    conn   = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM debtors WHERE debtor_id = ?", (debtor_id,))
    row = cursor.fetchone()
    if not row:
        logger.error("Debtor ID not found.")
        conn.close()
        return "[!] Error: Debtor ID not found."

    account_name = row[0]

    logger.info("Sending to Groq Whisper")
    transcript = transcribe_call(audio_path)
    if transcript.startswith("Error"):
        logger.error(f"Transcription failed: {transcript}")
        conn.close()
        return transcript

    logger.info("Passing transcript to audit pipeline")

    # ── Correctly consume the generator ──────────────────────────────────────
    final_result = None
    for event in run_qa_audit(transcript, account_name, think_mode=False, debug=True):
        if event["type"] == "status":
            logger.info(f"[{event['step'].upper()}] {event['message']}")
        elif event["type"] == "token":
            pass  # tokens not printed in batch mode
        elif event["type"] == "complete":
            final_result = event["result"]
        elif event["type"] == "error":
            logger.error(f"Pipeline error: {event['message']}")
            conn.close()
            return f"[!] Pipeline Error: {event['message']}"

    if not final_result:
        conn.close()
        return "[!] Pipeline returned no result."

    # ── Save to call_logs ─────────────────────────────────────────────────────
    passed  = 1 if final_result.get("compliance_passed") else 0
    score   = final_result.get("performance_score", 0)
    reason  = final_result.get("reasoning", "")
    v_notes = final_result.get("verification_notes", "")
    viols   = json.dumps(final_result.get("violations_found", []))
    rules   = json.dumps(final_result.get("retrieved_rules", []))
    facts   = final_result.get("sql_facts", "")

    try:
        cursor.execute("""
            INSERT INTO call_logs (
                debtor_id, agent_id, auditor_id, cloud_audio_uri,
                transcript, compliance_passed, ai_performance_score,
                reasoning, violations, verification_notes, retrieved_rules, sql_facts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            debtor_id, agent_id, auditor_id, audio_path,
            transcript, passed, score,
            reason, viols, v_notes, rules, facts,
        ))
        conn.commit()
        logger.info(
            f"\n{'='*60}\n"
            f"PIPELINE SUCCESS\n{'='*60}\n"
            f"Account    : {account_name}\n"
            f"Score      : {score}/10\n"
            f"Compliance : {'PASSED' if passed else 'FAILED'}\n"
            f"Violations : {final_result.get('violations_found', [])}\n"
            f"{'='*60}"
        )
    except sqlite3.IntegrityError as e:
        logger.warning(f"DB IntegrityError: {e}")
    finally:
        conn.close()

    return "Pipeline execution complete."


if __name__ == "__main__":
    test_audio = "compliant_call.mp3"
    if os.path.exists(test_audio):
        process_call(audio_path=test_audio, debtor_id=3, agent_id=1, auditor_id=1)
    else:
        logger.error(f"Place an audio file named '{test_audio}' to test.")