from fastapi import APIRouter

from app.api.v1.endpoints.audit   import router as audit_router
from app.api.v1.endpoints.debtors import router as debtors_router
from app.api.v1.endpoints.agents  import router as agents_router
from app.api.v1.endpoints.logs    import router as logs_router
from app.api.v1.endpoints.health  import router as health_router

api_router = APIRouter()

#Mounting endpoints
api_router.include_router(audit_router,   prefix="/audit",   tags=["Audit"])
api_router.include_router(debtors_router, prefix="/debtors", tags=["Debtors"])
api_router.include_router(agents_router,  prefix="/agents",  tags=["Agents"])
api_router.include_router(logs_router,    prefix="/logs",    tags=["Call Logs"])
api_router.include_router(health_router,  prefix="/health",  tags=["Health"])