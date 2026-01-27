import os
import httpx
from fastapi import Header, HTTPException, Depends
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Minimal Supabase Client using HTTPX to avoid binary dependencies (cryptography)
class SupabaseQueryBuilder:
    def __init__(self, url: str, headers: Dict[str, str]):
        self.url = url
        self.headers = headers
        self.params = {}
        self.method = "GET"
        self.json_body = None

    def select(self, columns: str = "*") -> 'SupabaseQueryBuilder':
        self.method = "GET"
        self.params["select"] = columns
        return self

    def insert(self, data: Dict[str, Any]) -> 'SupabaseQueryBuilder':
        self.method = "POST"
        self.headers["Prefer"] = "return=representation"
        self.json_body = data
        return self

    def update(self, data: Dict[str, Any]) -> 'SupabaseQueryBuilder':
        self.method = "PATCH"
        self.headers["Prefer"] = "return=representation"
        self.json_body = data
        return self

    def delete(self) -> 'SupabaseQueryBuilder':
        self.method = "DELETE"
        return self

    def order(self, column: str, desc: bool = False) -> 'SupabaseQueryBuilder':
        direction = "desc" if desc else "asc"
        self.params["order"] = f"{column}.{direction}"
        return self

    def limit(self, count: int) -> 'SupabaseQueryBuilder':
        self.params["limit"] = str(count)
        return self

    def eq(self, column: str, value: Any) -> 'SupabaseQueryBuilder':
        self.params[column] = f"eq.{value}"
        return self

    def execute(self):
        try:
            if self.method == "GET":
                resp = httpx.get(self.url, headers=self.headers, params=self.params)
            elif self.method == "PATCH":
                resp = httpx.patch(self.url, headers=self.headers, params=self.params, json=self.json_body)
            elif self.method == "POST":
                resp = httpx.post(self.url, headers=self.headers, params=self.params, json=self.json_body)
            elif self.method == "DELETE":
                resp = httpx.delete(self.url, headers=self.headers, params=self.params)
            else:
                raise NotImplementedError(f"Method {self.method} not implemented")
            
            # Return object with data attribute to match SDK
            class Response:
                def __init__(self, data): self.data = data
            
            if resp.status_code >= 400:
                print(f"Supabase Error ({self.method} {self.url}): {resp.text}")
                return Response(None)
            
            # For DELETE, sometimes it returns empty 204
            if resp.status_code == 204:
                return Response([])
                
            return Response(resp.json())
        except Exception as e:
            print(f"Supabase Request Failed: {e}")
            return Response(None)

class SupabaseAuth:
    def __init__(self, url: str, key: str):
        self.auth_url = f"{url}/auth/v1"
        self.key = key

    def get_user(self, token: str):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {token}"
        }
        try:
            resp = httpx.get(f"{self.auth_url}/user", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # SDK returns object with .user
                class UserResponse:
                    def __init__(self, user_data): 
                        class User:
                            def __init__(self, uid): self.id = uid
                        self.user = User(user_data.get('id'))
                return UserResponse(data)
            return None
        except:
            return None

class SupabaseClient:
    def __init__(self, url: str, key: str):
        self.rest_url = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        self.auth = SupabaseAuth(url, key)

    def table(self, name: str) -> SupabaseQueryBuilder:
        return SupabaseQueryBuilder(f"{self.rest_url}/{name}", self.headers.copy())

# Initialize Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Fallback to avoid crash during import if env not set
    supabase = None
else:
    supabase = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)

def get_current_user(authorization: str = Header(None)):
    """
    Validates the Bearer Token sent by the Frontend.
    Returns the User ID if valid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Token")

    try:
        token = authorization.split(" ")[1]
        if not supabase:
             raise HTTPException(status_code=500, detail="DB Config Error")
             
        user = supabase.auth.get_user(token)
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid Token")
            
        return user.user.id

    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
