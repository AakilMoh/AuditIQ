import os
import json
import shutil
import asyncio
import time
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.database.connection import get_db_connection
from app.core.schemas import SaveAuditRequest, SaveAuditResponse
from app.services.auditor import run_qa_audit
from app.services.transcriber import transcribe_call

router = APIRouter()

@router.post("/stream")
async def stream_audit(
    audio_file: UploadFile = File(...),
    debtor_id:  int        = Form(...),
    think_mode: bool       = Form(False),
    db                     = Depends(get_db_connection),
):
    """
    SSE stream. Transcribes audio, runs multi-agent FDCPA audit, streams result.
    """
    async def event_generator():
        # Step 1: Initialization & File Handling
        yield f"data: {json.dumps({'step': 'init', 'message': f'Received {audio_file.filename}. Validating payload'})}\n\n"
        await asyncio.sleep(0.2) # Tiny delay for UI smoothness

        #Local Audio Vault <- till deployment
        #appending a timestamp to the filename to prevent overwrites and to save it permanently.
        safe_filename = f"{int(time.time())}_{os.path.basename(audio_file.filename)}"
        vault_dir = "local_audio_vault"  #Swap to cloud URI when deploying
        os.makedirs(vault_dir, exist_ok=True)
        saved_audio_path = os.path.join(vault_dir, safe_filename)
        
        with open(saved_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)


        # Step 2: Database Cross-Reference
        yield f"data: {json.dumps({'step': 'database', 'message': 'Fetching debtor profile from SQLite vault'})}\n\n"
        cursor = db.cursor()
        cursor.execute("SELECT name FROM debtors WHERE debtor_id = ?", (debtor_id,))
        row = cursor.fetchone()
        if not row:
            if os.path.exists(saved_audio_path):
                os.remove(saved_audio_path)
            yield f"data: {json.dumps({'step': 'error', 'message': 'Debtor ID not found.'})}\n\n"
            return
        account_name = row[0]
        await asyncio.sleep(0.2)

        # Step 3: Audio Transcription
        yield f"data: {json.dumps({'step': 'transcribing', 'message': 'Passing audio to Whisper API'})}\n\n"
        transcript = transcribe_call(saved_audio_path)
        if "Error" in transcript:
            if os.path.exists(saved_audio_path):
                os.remove(saved_audio_path)
            yield f"data: {json.dumps({'step': 'error', 'message': 'Transcription failed.'})}\n\n"
            return
        
        # Send the transcript to the frontend immediately so the user can read it while the AI thinks!
        yield f"data: {json.dumps({'step': 'transcript_ready', 'transcript': transcript})}\n\n"

        #constructing a trackable text of  what the LLM was fed
        prompt_signature = f"SYSTEM_ROLE: FDCPA Compliance Auditor | TARGET_ACCOUNT: {account_name} | TRANSCRIPT_LENGTH: {len(transcript)} chars"

        # Step 4: Multi-Agent AI Audit
        #Will be looping through the generator built in auditor.py
        for event in run_qa_audit(transcript, account_name, think_mode=think_mode):
            
            if event["type"] == "status":
                yield f"data: {json.dumps({'step': event['step'], 'message': event['message']})}\n\n"
            
            elif event["type"] == "token":
                # Pushing the raw LLM token to the frontend instantly
                yield f"data: {json.dumps({'step': 'stream', 'chunk': event['content']})}\n\n"
            
            elif event["type"] == "complete":
                final_result = event['result']
                final_result["cloud_audio_uri"] = saved_audio_path
                final_result["llm_prompt"] = prompt_signature

                yield f"data: {json.dumps({'step': 'complete', 'result': final_result})}\n\n"
                
            elif event["type"] == "error":
                yield f"data: {json.dumps({'step': 'error', 'message': event['message']})}\n\n"

    # Return the stream with the correct SSE media type
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/save", response_model=SaveAuditResponse)
async def save_audit_result(
    payload: SaveAuditRequest,
    db = Depends(get_db_connection),
):
    """Persists a completed audit result to call_logs."""
    try:
        cursor = db.cursor()
        if hasattr(payload.result, "model_dump"):
            res = payload.result.model_dump() #for pydantic v2
        else:
            res = payload.result.dict() #for pydantic v1

        passed = 1 if res.get("compliance_passed", False) else 0
        score = res.get("performance_score", 0)
        reasoning = res.get("reasoning", "")
        transcript = res.get("transcript", "")

        cloud_audio_uri = res.get("cloud_audio_uri", "")
        llm_prompt = res.get("llm_prompt", "")
        
        # Parse arrays to JSON strings for SQLite
        violations = json.dumps(res.get("violations_found", []))
        retrieved_rules = json.dumps(res.get("retrieved_rules", []))
        verification_notes = res.get("verification_notes", "")
        sql_facts = res.get("sql_facts", "")

        utc_now = datetime.now(timezone.utc).isoformat()
        
        auditor_id = 1 #defaulting the user(auditor) until logins and auth is finalized
        cursor.execute("""
            INSERT INTO call_logs (
                debtor_id, agent_id, auditor_id, transcript, compliance_passed, 
                ai_performance_score, reasoning, violations, verification_notes, 
                retrieved_rules, sql_facts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.debtor_id, 
            payload.agent_id, 
            auditor_id, 
            transcript, 
            passed, 
            score, 
            reasoning,
            violations,
            verification_notes,
            retrieved_rules,
            sql_facts
        ))
        db.commit()
        return SaveAuditResponse(log_id=cursor.lastrowid, message="Audit saved successfully.")

    except Exception as e:
        print(f"Database Save Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))