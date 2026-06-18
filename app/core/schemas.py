from pydantic import BaseModel, Field, validator
from typing import List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────────────────────────────────────

class AuditResult(BaseModel):
    compliance_passed:  bool
    performance_score:  int             = Field(..., ge=1, le=10)
    violations_found:   List[str]       = []
    reasoning:          str
    verification_notes: str             = ""
    retrieved_rules:    List[str]       = []
    sql_facts:          str             = ""
    account_name:       str             = ""
    transcript:         str             = ""

    @validator("reasoning")
    def flag_verifier_rejection(cls, v):
        return v

    @property
    def verifier_rejected(self) -> bool:
        return self.reasoning.startswith("[REJECTED BY VERIFIER]:")

    @property
    def clean_reasoning(self) -> str:
        if self.verifier_rejected:
            return self.reasoning.replace("[REJECTED BY VERIFIER]:", "").strip()
        return self.reasoning

class SaveAuditRequest(BaseModel):
    debtor_id:          int
    agent_id:           int
    result:             AuditResult

class SaveAuditResponse(BaseModel):
    log_id:  int
    message: str = "Audit saved successfully."

# ─────────────────────────────────────────────────────────────────────────────
# DEBTORS & AGENTS
# ─────────────────────────────────────────────────────────────────────────────

class DebtorOut(BaseModel):
    debtor_id:      int
    account_number: str
    name:           str
    balance:        float
    status:         str   

class AgentOut(BaseModel):
    agent_id:   int
    name:       str
    department: str

# ─────────────────────────────────────────────────────────────────────────────
# CALL LOGS & STATS & HEALTH
# ─────────────────────────────────────────────────────────────────────────────

class CallLogSummary(BaseModel):
    log_id:               int
    debtor_id:            int
    agent_id:             Optional[int]
    account_name:         Optional[str]
    agent_name:           Optional[str]
    compliance_passed:    bool
    ai_performance_score: int
    human_override_score: Optional[int]
    timestamp:            str

class CallLogDetail(CallLogSummary):
    transcript:  str
    reasoning:   str

class HumanOverrideRequest(BaseModel):
    human_override_score: int = Field(..., ge=1, le=10)

class HumanOverrideResponse(BaseModel):
    log_id:  int
    message: str = "Override saved."

class StatsSummary(BaseModel):
    total_audits:     int
    audits_today:     int
    compliance_rate:  float  
    average_score:    float  
    violations_today: int

class HealthResponse(BaseModel):
    status:   str  
    database: str  
    message:  str