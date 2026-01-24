from fastapi import FastAPI, Depends
from dependencies import get_current_user

app = FastAPI()

@app.post("/ingest")
def ingest_file(file_url: str, user_id: str = Depends(get_current_user)):
    # If the token is fake, this function NEVER runs.
    # If valid, you have the real user_id.
    return {"message": f"Processing file for user {user_id}"}