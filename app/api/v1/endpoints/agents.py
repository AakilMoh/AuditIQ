from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.database.connection import get_db_connection
from app.core.schemas import AgentOut

router = APIRouter()

@router.get("", response_model=List[AgentOut])
async def list_agents(
    db = Depends(get_db_connection),
):
    """Returns all agent records."""
    cursor = db.cursor()
    cursor.execute("SELECT agent_id, name, department FROM agents")
    rows = cursor.fetchall()
    return [AgentOut(**dict(row)) for row in rows]

@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int,
    db = Depends(get_db_connection),
):
    """Returns a single agent by ID."""
    cursor = db.cursor()
    cursor.execute(
        "SELECT agent_id, name, department FROM agents WHERE agent_id = ?",
        (agent_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found.")
    return AgentOut(**dict(row))