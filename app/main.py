from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.api.v1.router import router as api_v1_router

app = FastAPI(
    title="Mini CollectIQ API",
    description="Auditing Engine for Debt Collection",
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

app.include_router(api_v1_router, prefix="/api/v1", tags=["Audit Pipeline"])

@app.get("/")
def health_check():
    return {"status": "online", "system": "Mini CollectIQ Core Pipeline"}

if __name__ == "__main__":
    print("Booting Mini CollectIQ API Server")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)