import os
from fastapi import Header, HTTPException, Depends
from supabase import create_client, Client

# Initialize Supabase Client (Backend side)
SUPABASE_URL = os.getenv("SUPABASE_URL") # Same as frontend
SUPABASE_KEY = os.getenv("SUPABASE_KEY") # Get this from Dashboard -> Settings -> API (Service Role, NOT Anon)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_current_user(authorization: str = Header(None)):
    """
    Validates the Bearer Token sent by the Frontend.
    Returns the User ID if valid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Token")

    try:
        # Extract "Bearer <token>"
        token = authorization.split(" ")[1]
        
        # Verify with Supabase
        user = supabase.auth.get_user(token)
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid Token")
            
        return user.user.id

    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))