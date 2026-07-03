# ─────────────────────────────────────────────────────────────────────────────
# AUDITIQ — AUDIT ENDPOINTS  v2.0
# ─────────────────────────────────────────────────────────────────────────────
#
# CHANGES FROM v1:
#   1. run_qa_audit() now returns the new event types — consumer updated
#   2. transcribe_call() wrapped in run_in_executor (async-safe, no event loop block)
#   3. File size limit (50MB) + extension whitelist
#   4. Filename sanitized before disk write
#   5. NEW: GET /audit/report/{log_id} → streams PDF from saved call_log
#   6. NEW: POST /audit/report/preview → generates PDF from result payload
#      (called by frontend immediately after stream completes, before save)
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import shutil
import asyncio
import re
import time
from datetime import datetime, timezone

from fastapi           import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import StreamingResponse, Response
from app.database.connection import get_db_connection
from app.core.schemas        import SaveAuditRequest, SaveAuditResponse
from app.services.auditor    import run_qa_audit
from app.services.transcriber import transcribe_call
from app.services.pdf_reporter import generate_audit_pdf

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

MAX_FILE_BYTES     = 50 * 1024 * 1024   # 50 MB
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}
VAULT_DIR          = "local_audio_vault"
os.makedirs(VAULT_DIR, exist_ok=True)


def _sanitize(name: str) -> str:
    return re.sub(r"[^\w\-_\.]", "_", os.path.basename(name or "upload"))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/audit/stream
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/stream")
async def stream_audit(
    audio_file: UploadFile = File(...),
    debtor_id:  int        = Form(...),
    agent_id:   int        = Form(...),
    think_mode: bool       = Form(False),
    db                     = Depends(get_db_connection),
):
    """
    SSE streaming audit endpoint.

    Accepts multipart form: audio_file + debtor_id + agent_id + think_mode.
    Streams pipeline progress and final result as Server-Sent Events.

    SSE event sequence:
        init → database (×3) → transcribing → transcript_ready →
        auditing → stream (N) → verifying → complete | error

    complete.result shape (v2 additions):
        formatted_transcript: str          — [AGENT]/[DEBTOR] labeled transcript
        pre_detection: {
            mini_miranda_detected, confirmed_violations,
            suspicious_patterns, risk_score
        }
        grade_report: {
            rubric_scores, total_grade,
            prompt_improvement_suggestion, hallucinations_found
        }
        speaker_segmentation: { confidence, agent_turns, debtor_turns }
    """

    async def event_generator():

        # ── Validation ────────────────────────────────────────────────────────
        yield _sse({"step": "init", "message": f"Received {audio_file.filename}. Validating payload"})
        await asyncio.sleep(0.1)

        filename = _sanitize(audio_file.filename)
        ext      = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            yield _sse({"step": "error",
                        "message": f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"})
            return

        # Read with size guard
        content = await audio_file.read()
        if len(content) > MAX_FILE_BYTES:
            yield _sse({"step": "error",
                        "message": f"File too large ({len(content)//1024//1024}MB). Max is 50MB."})
            return

        # ── Save to vault ─────────────────────────────────────────────────────
        safe_name       = f"{int(time.time())}_{filename}"
        saved_path      = os.path.join(VAULT_DIR, safe_name)
        with open(saved_path, "wb") as f:
            f.write(content)

        # ── Debtor lookup ─────────────────────────────────────────────────────
        yield _sse({"step": "database", "message": "Fetching debtor profile from SQLite vault"})

        cursor = db.cursor()
        cursor.execute("SELECT name FROM debtors WHERE debtor_id = ?", (debtor_id,))
        row = cursor.fetchone()
        if not row:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            yield _sse({"step": "error", "message": f"Debtor ID {debtor_id} not found."})
            return

        account_name = row[0]
        await asyncio.sleep(0.1)

        # ── Transcription (async-safe) ─────────────────────────────────────────
        yield _sse({"step": "transcribing", "message": "Passing audio to Whisper API"})

        loop = asyncio.get_running_loop()
        try:
            transcript = await loop.run_in_executor(None, transcribe_call, saved_path)
        except Exception as e:
            yield _sse({"step": "error", "message": f"Transcription exception: {e}"})
            return

        if not transcript or transcript.startswith("Error"):
            yield _sse({"step": "error", "message": f"Transcription failed: {transcript}"})
            return

        yield _sse({"step": "transcript_ready", "transcript": transcript})

        # Prompt signature for call_logs
        prompt_signature = (
            f"SYSTEM_ROLE: FDCPA Compliance Auditor v2.0 | "
            f"TARGET_ACCOUNT: {account_name} | "
            f"TRANSCRIPT_LENGTH: {len(transcript)} chars | "
            f"THINK_MODE: {think_mode}"
        )

        # ── Multi-agent audit pipeline ─────────────────────────────────────────
        # run_qa_audit is synchronous generator — wrap in executor for async safety
        # We iterate it in a thread and re-yield events back to the SSE stream.

        event_queue = asyncio.Queue()

        def _run_pipeline():
            """Runs the synchronous generator in a thread, puts events on queue."""
            try:
                for event in run_qa_audit(
                    transcript   = transcript,
                    account_name = account_name,
                    think_mode   = think_mode,
                    debug        = True,
                ):
                    # Map internal event types to SSE step format
                    if event["type"] == "status":
                        asyncio.run_coroutine_threadsafe(
                            event_queue.put({"step": event["step"], "message": event["message"]}),
                            loop
                        )
                    elif event["type"] == "token":
                        asyncio.run_coroutine_threadsafe(
                            event_queue.put({"step": "stream", "chunk": event["content"]}),
                            loop
                        )
                    elif event["type"] == "complete":
                        final = event["result"]
                        final["cloud_audio_uri"] = saved_path
                        final["llm_prompt"]      = prompt_signature
                        asyncio.run_coroutine_threadsafe(
                            event_queue.put({"step": "complete", "result": final}),
                            loop
                        )
                    elif event["type"] == "error":
                        asyncio.run_coroutine_threadsafe(
                            event_queue.put({"step": "error", "message": event["message"]}),
                            loop
                        )
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    event_queue.put({"step": "error", "message": f"Pipeline crash: {str(e)}"}),
                    loop
                )
            finally:
                # Sentinel — tells the consumer the pipeline is done
                asyncio.run_coroutine_threadsafe(
                    event_queue.put(None),
                    loop
                )

        # Start pipeline in thread pool
        loop.run_in_executor(None, _run_pipeline)

        # Consume queue and yield SSE events
        while True:
            event = await event_queue.get()
            if event is None:
                break  # pipeline finished
            yield _sse(event)
            if event.get("step") in ("complete", "error"):
                break

    return StreamingResponse(
        event_generator(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/audit/save
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/save", response_model=SaveAuditResponse)
async def save_audit_result(
    payload: SaveAuditRequest,
    db = Depends(get_db_connection),
):
    """
    Persists a completed audit result to call_logs.
    Called by the frontend after receiving the SSE complete event.
    """
    try:
        cursor = db.cursor()

        if hasattr(payload.result, "model_dump"):
            res = payload.result.model_dump()
        else:
            res = payload.result.dict()

        passed             = 1 if res.get("compliance_passed", False) else 0
        score              = res.get("performance_score", 0)
        reasoning          = res.get("reasoning", "")
        transcript         = res.get("transcript", "")
        cloud_audio_uri    = res.get("cloud_audio_uri", "")
        llm_prompt         = res.get("llm_prompt", "")
        violations         = json.dumps(res.get("violations_found", []))
        retrieved_rules    = json.dumps(res.get("retrieved_rules", []))
        verification_notes = res.get("verification_notes", "")
        sql_facts          = res.get("sql_facts", "")
        auditor_id         = 1   # hardcoded until auth is implemented

        agent_id = payload.agent_id or 1  # default to 1 if not provided

        cursor.execute("""
            INSERT INTO call_logs (
                debtor_id, agent_id, auditor_id,
                cloud_audio_uri, transcript, llm_prompt,
                compliance_passed, ai_performance_score, reasoning,
                violations, verification_notes, retrieved_rules, sql_facts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.debtor_id,
            agent_id,
            auditor_id,
            cloud_audio_uri,
            transcript,
            llm_prompt,
            passed,
            score,
            reasoning,
            violations,
            verification_notes,
            retrieved_rules,
            sql_facts,
        ))
        db.commit()
        log_id = cursor.lastrowid

        return SaveAuditResponse(log_id=log_id, message="Audit saved successfully.")

    except Exception as e:
        print(f"Database Save Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/audit/report/preview
# ─────────────────────────────────────────────────────────────────────────────
# Called by the frontend immediately after stream completes.
# Takes the full result JSON, generates PDF, streams it back.
# The user gets the PDF download without needing a saved log_id first.

@router.post("/report/preview")
async def preview_report(payload: dict):
    """
    Generates a PDF from a result payload and streams it as a download.

    Request body: the full result object from the SSE complete event.

    Response: application/pdf — triggers browser download.

    Frontend usage:
        const res = await fetch('/api/v1/audit/report/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(completeResult),
        });
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `audit_${accountName}.pdf`;
        a.click();
    """
    try:
        loop      = asyncio.get_running_loop()
        pdf_bytes = await loop.run_in_executor(None, generate_audit_pdf, payload)

        account   = payload.get("account_name", "report").replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename  = f"AuditIQ_{account}_{timestamp}.pdf"
        filename = re.sub(r"[^\w\-_\.]", "_", filename)

        return Response(
            content      = pdf_bytes,
            media_type   = "application/pdf",
            headers      = {
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length":      str(len(pdf_bytes)),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/audit/report/{log_id}
# ─────────────────────────────────────────────────────────────────────────────
# Regenerates a PDF from a previously saved call_log.
# Used by the History screen — "Download Report" button next to each log entry.

@router.get("/report/{log_id}")
async def download_report(
    log_id: int,
    db = Depends(get_db_connection),
):
    """
    Fetches a saved call_log by ID and generates its PDF report.

    Path param:
        log_id (int) — primary key in call_logs

    Response: application/pdf download.

    Errors:
        404 — log_id not found
        500 — PDF generation failed
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT
                cl.log_id, cl.debtor_id, cl.transcript,
                cl.compliance_passed, cl.ai_performance_score,
                cl.reasoning, cl.violations, cl.verification_notes,
                cl.retrieved_rules, cl.sql_facts, cl.timestamp,
                d.name AS account_name
            FROM call_logs cl
            LEFT JOIN debtors d ON cl.debtor_id = d.debtor_id
            WHERE cl.log_id = ?
        """, (log_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Log {log_id} not found.")

        # Reconstruct a result dict from the stored fields
        result = {
            "account_name":       row[11] or f"Debtor #{row[1]}",
            "transcript":         row[2]  or "",
            "formatted_transcript": row[2] or "",  # raw transcript fallback
            "compliance_passed":  bool(row[3]),
            "performance_score":  row[4],
            "reasoning":          row[5] or "",
            "violations_found":   json.loads(row[6])  if row[6]  else [],
            "verification_notes": row[7] or "",
            "retrieved_rules":    json.loads(row[8])  if row[8]  else [],
            "sql_facts":          row[9] or "",
            "pre_detection":      {},   # not stored — omitted from PDF gracefully
            "grade_report":       {},
            "speaker_segmentation": {},
        }

        loop      = asyncio.get_running_loop()
        pdf_bytes = await loop.run_in_executor(None, generate_audit_pdf, result)

        account   = result["account_name"].replace(" ", "_")
        timestamp = (row[10] or "").replace(" ", "_").replace(":", "")[:15]
        filename  = f"AuditIQ_{account}_{timestamp}.pdf"
        filename = re.sub(r"[^\w\-_\.]", "_", filename)

        return Response(
            content      = pdf_bytes,
            media_type   = "application/pdf",
            headers      = {
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length":      str(len(pdf_bytes)),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")