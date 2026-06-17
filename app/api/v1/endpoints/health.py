from fastapi import APIRouter, Depends
from app.database.connection import get_db_connection
from app.core.schemas import HealthResponse

router = APIRouter()

@router.get("", response_model=HealthResponse)
async def health_check(db = Depends(get_db_connection)):
    """
    Returns the current health of the API and its SQLite dependency.
    """
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        db_status = "error"
    
    overall = "ok" if db_status == "ok" else "degraded"
    msg     = "All systems operational." if overall == "ok" else "Database unreachable."
    
    return HealthResponse(status=overall, database=db_status, message=msg)