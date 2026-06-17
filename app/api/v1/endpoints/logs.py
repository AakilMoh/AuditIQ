from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.database.connection import get_db_connection
from app.core.schemas import (
    CallLogSummary, CallLogDetail, HumanOverrideRequest, 
    HumanOverrideResponse, StatsSummary
)

router = APIRouter()

@router.get("", response_model=List[CallLogSummary])
async def list_call_logs(
    compliance_passed: Optional[bool] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db = Depends(get_db_connection),
):
    """Returns paginated call log summaries for the History screen."""
    base_query = """
        SELECT 
            cl.log_id, cl.debtor_id, cl.agent_id, 
            d.name AS account_name, 
            a.name AS agent_name, 
            cl.compliance_passed, cl.ai_performance_score, 
            cl.human_override_score, cl.timestamp 
        FROM call_logs cl 
        LEFT JOIN debtors d ON cl.debtor_id = d.debtor_id 
        LEFT JOIN agents a ON cl.agent_id = a.agent_id 
    """
    filters, params = [], []
    
    if compliance_passed is not None:
        filters.append("cl.compliance_passed = ?")
        params.append(int(compliance_passed))
        
    if filters:
        base_query += " WHERE " + " AND ".join(filters)
        
    base_query += " ORDER BY cl.timestamp DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    
    cursor = db.cursor()
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    return [CallLogSummary(**dict(row)) for row in rows]


@router.get("/stats/summary", response_model=StatsSummary)
async def get_stats_summary(db = Depends(get_db_connection)):
    """Returns aggregate metrics for the Dashboard screen."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT 
            COUNT(*) AS total_audits, 
            SUM(date(timestamp) = date('now')) AS audits_today, 
            AVG(CAST(compliance_passed AS REAL)) AS compliance_rate, 
            AVG(ai_performance_score) AS average_score, 
            SUM(compliance_passed = 0 AND date(timestamp) = date('now')) AS violations_today 
        FROM call_logs 
    """)
    row = cursor.fetchone()
    return StatsSummary(
        total_audits=row["total_audits"] or 0,
        audits_today=row["audits_today"] or 0,
        compliance_rate=round(row["compliance_rate"] or 0.0, 2),
        average_score=round(row["average_score"] or 0.0, 1),
        violations_today=row["violations_today"] or 0,
    )


@router.get("/{log_id}", response_model=CallLogDetail)
async def get_call_log(log_id: int, db = Depends(get_db_connection)):
    """Returns the full call log record including transcript and reasoning."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT 
            cl.log_id, cl.debtor_id, cl.agent_id, 
            d.name AS account_name, 
            a.name AS agent_name, 
            cl.compliance_passed, cl.ai_performance_score, 
            cl.human_override_score, cl.transcript, cl.reasoning, cl.timestamp 
        FROM call_logs cl 
        LEFT JOIN debtors d ON cl.debtor_id = d.debtor_id 
        LEFT JOIN agents a ON cl.agent_id = a.agent_id 
        WHERE cl.log_id = ? 
    """, (log_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Log {log_id} not found.")
    return CallLogDetail(**dict(row))


@router.patch("/{log_id}/override", response_model=HumanOverrideResponse)
async def human_override(
    log_id: int, 
    payload: HumanOverrideRequest, 
    db = Depends(get_db_connection)
):
    """Sets a manual reviewer score on a completed audit."""
    cursor = db.cursor()
    cursor.execute(
        "UPDATE call_logs SET human_override_score = ? WHERE log_id = ?", 
        (payload.human_override_score, log_id)
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Log {log_id} not found.")
    db.commit()
    return HumanOverrideResponse(log_id=log_id, message="Override saved.")