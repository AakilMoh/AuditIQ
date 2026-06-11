from fastapi import Header, HTTPException

# Placeholder for future Enterprise Auth
async def verify_api_token(x_api_key: str = Header(None)):
    if x_api_key != "minicollectiq-secret-token":
        raise HTTPException(status_code=401, detail="Unauthorized API Key")
    return x_api_key