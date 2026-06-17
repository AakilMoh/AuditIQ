import os
import json
import shutil
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, Depends
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

        #stripping out any incoming folder paths from the client for security and path safety
        safe_filename = os.path.basename(audio_file.filename)

        #ensure the base upload directory exists
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)

        #combining them
        temp_path = os.path.join(temp_dir, safe_filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)

        # Step 2: Database Cross-Reference
        yield f"data: {json.dumps({'step': 'database', 'message': 'Fetching debtor profile from SQLite vault'})}\n\n"
        cursor = db.cursor()
        cursor.execute("SELECT name FROM debtors WHERE debtor_id = ?", (debtor_id,))
        row = cursor.fetchone()
        if not row:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            yield f"data: {json.dumps({'step': 'error', 'message': 'Debtor ID not found.'})}\n\n"
            return
        account_name = row[0]
        await asyncio.sleep(0.2)

        # Step 3: Audio Transcription
        yield f"data: {json.dumps({'step': 'transcribing', 'message': 'Passing audio to Whisper API'})}\n\n"
        transcript = transcribe_call(temp_path)
        if "Error" in transcript:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            yield f"data: {json.dumps({'step': 'error', 'message': 'Transcription failed.'})}\n\n"
            return
        
        # Send the transcript to the frontend immediately so the user can read it while the AI thinks!
        yield f"data: {json.dumps({'step': 'transcript_ready', 'transcript': transcript})}\n\n"

        # Step 4: Multi-Agent AI Audit
        #Will be looping through the generator built in auditor.py
        for event in run_qa_audit(transcript, account_name, think_mode=think_mode):
            
            if event["type"] == "status":
                yield f"data: {json.dumps({'step': event['step'], 'message': event['message']})}\n\n"
            
            elif event["type"] == "token":
                # Pushing the raw LLM token to the frontend instantly
                yield f"data: {json.dumps({'step': 'stream', 'chunk': event['content']})}\n\n"
            
            elif event["type"] == "complete":
                # Final cleanup and return
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                yield f"data: {json.dumps({'step': 'complete', 'result': event['result']})}\n\n"
                
            elif event["type"] == "error":
                # Handle any deep pipeline errors gracefully
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                yield f"data: {json.dumps({'step': 'error', 'message': event['message']})}\n\n"

    # Return the stream with the correct SSE media type
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/save", response_model=SaveAuditResponse)
async def save_audit_result(
    payload: SaveAuditRequest,
    db = Depends(get_db_connection),
):
    """Persists a completed audit result to call_logs."""
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO call_logs (
            debtor_id, agent_id, transcript, compliance_passed, 
            ai_performance_score, reasoning, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        payload.debtor_id, 
        payload.agent_id, 
        payload.result.transcript, 
        payload.result.compliance_passed, 
        payload.result.performance_score, 
        payload.result.reasoning
    ))
    db.commit()
    return SaveAuditResponse(log_id=cursor.lastrowid, message="Audit saved successfully.")