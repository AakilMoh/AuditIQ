from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from app.database.connection import get_db_connection
from app.core.schemas import DebtorOut

router = APIRouter()

@router.get("", response_model=List[DebtorOut])
async def list_debtors(
    status: Optional[str] = None,
    db = Depends(get_db_connection),
):
    """Returns all debtor records, optionally filtered by status."""
    cursor = db.cursor()
    if status:
        cursor.execute(
            "SELECT debtor_id, account_number, name, balance, status "
            "FROM debtors WHERE status = ?",
            (status,)
        )
    else:
        cursor.execute(
            "SELECT debtor_id, account_number, name, balance, status FROM debtors"
        )
    
    rows = cursor.fetchall()
    return [DebtorOut(**dict(row)) for row in rows]

@router.get("/{debtor_id}", response_model=DebtorOut)
async def get_debtor(
    debtor_id: int,
    db = Depends(get_db_connection),
):
    """Returns a single debtor by ID."""
    cursor = db.cursor()
    cursor.execute(
        "SELECT debtor_id, account_number, name, balance, status "
        "FROM debtors WHERE debtor_id = ?",
        (debtor_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Debtor {debtor_id} not found.")
    return DebtorOut(**dict(row))