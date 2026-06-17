from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.api.v1.router import api_router
app = FastAPI(
    title="AuditIQ API",
    description="FDCPA Auditing Engine for Debt Collection",
    version="1.0.0"
)

# Allow the future Next.js frontend to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def root_check():
    return {"status": "online", "system": "AuditIQ Core Backend", "version": "1.0.0"}

if __name__ == "__main__":
    print("Booting AuditIQ API Server")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)