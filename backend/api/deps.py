"""
Shared request dependencies: authentication and ownership checks.

Authentication has two modes, decided by which database backend is active:

- **Supabase**: the bearer token is a Supabase JWT, verified against the auth
  API. Verified tokens are cached briefly, because the previous implementation
  made a blocking HTTPS round trip to Supabase on *every* API call - including
  the two-second job polling loop.
- **Local**: tokens are HMAC-signed by this backend and carry the user id
  directly, so a local install needs no hosted auth service at all.

The old code accepted any header containing the string ``mock-token`` and
returned a fixed user id. That was an unauthenticated login for anyone who
guessed the string, in every deployment. It is now gated behind an explicit
setting and refused outright when Supabase is the active backend.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import Depends, Header, HTTPException, Query

from backend.core.config import get_settings
from backend.services.db_interface import DBInterface, active_backend

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local-user"
LOCAL_USER_EMAIL = "you@localhost"

# Verified tokens are cached for this long. Short enough that a revoked session
# stops working quickly, long enough to take Supabase off the hot path.
TOKEN_CACHE_TTL = 60.0

_token_cache: Dict[str, Tuple[str, float]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Local tokens
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_local_token(user_id: str, ttl_seconds: int = 7 * 24 * 3600) -> str:
    """Mint a signed local session token: ``<payload>.<signature>``."""
    secret = get_settings().storage_signing_secret.encode()
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + ttl_seconds}).encode())
    signature = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_local_token(token: str) -> Optional[str]:
    """Return the user id encoded in a local token, or ``None`` if invalid."""
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError:
        return None

    secret = get_settings().storage_signing_secret.encode()
    expected = _b64(hmac.new(secret, payload_part.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        payload = json.loads(_unb64(payload_part))
    except (ValueError, json.JSONDecodeError):
        return None

    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("sub")


# ---------------------------------------------------------------------------
# Supabase tokens
# ---------------------------------------------------------------------------

def _verify_supabase_token(token: str) -> str:
    """Resolve a Supabase JWT to a user id, using a short-lived cache."""
    now = time.time()
    with _cache_lock:
        cached = _token_cache.get(token)
        if cached and cached[1] > now:
            return cached[0]

    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={"apikey": settings.supabase_key, "Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.error("Supabase auth request failed: %s", exc)
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = (response.json() or {}).get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token did not resolve to a user")

    with _cache_lock:
        _token_cache[token] = (user_id, now + TOKEN_CACHE_TTL)
        # Bound the cache; tokens rotate and stale entries are dead weight.
        if len(_token_cache) > 1000:
            for key, (_, expiry) in list(_token_cache.items()):
                if expiry <= now:
                    _token_cache.pop(key, None)

    return user_id


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _mock_auth_allowed() -> bool:
    """
    Legacy ``mock-token`` support.

    Only ever enabled when there is no hosted database behind this instance, or
    when an operator has explicitly opted in.
    """
    return get_settings().allow_mock_auth or active_backend() == "local"


def resolve_user(authorization: Optional[str]) -> str:
    """Resolve an Authorization header to a user id, or raise 401."""
    token = ""
    if authorization:
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()

    if active_backend() == "local":
        # A local install is single-user by definition; there is no tenant to
        # isolate from. Any token (or none) maps to the local user, unless it is
        # a signed token naming someone else.
        if token:
            user_id = verify_local_token(token)
            if user_id:
                return user_id
        return LOCAL_USER_ID

    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if token == "mock-token":
        if not _mock_auth_allowed():
            raise HTTPException(status_code=401, detail="Mock authentication is disabled")
        return LOCAL_USER_ID

    local_user = verify_local_token(token)
    if local_user:
        return local_user

    return _verify_supabase_token(token)


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: the authenticated user's id."""
    return resolve_user(authorization)


def get_ws_user(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    WebSocket variant.

    Browsers cannot set headers on a WebSocket handshake, so the token arrives
    as a query parameter. Same verification either way.
    """
    return resolve_user(authorization or (f"Bearer {token}" if token else None))


def get_db() -> DBInterface:
    """FastAPI dependency: a data-access handle."""
    return DBInterface()


def require_project(
    project_id: str,
    user_id: str,
    db: Optional[DBInterface] = None,
) -> Dict[str, Any]:
    """
    Load a project and assert the caller owns it.

    Every route that touches project-scoped data goes through here, so the
    ownership rule lives in one place instead of being re-implemented (and
    occasionally forgotten) per endpoint.
    """
    db = db or DBInterface()
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    owner = project.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def require_artifact(
    artifact_id: str,
    user_id: str,
    db: Optional[DBInterface] = None,
) -> Dict[str, Any]:
    """Load an artifact and assert the caller owns the project it belongs to."""
    db = db or DBInterface()
    artifact = db.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    require_project(artifact["project_id"], user_id, db)
    return artifact


CurrentUser = Depends(get_current_user)
