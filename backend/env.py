"""Deterministic environment loading for the backend."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

_LOADED = False


def _set_if_missing(name: str, value: str | None) -> None:
    if value and not os.environ.get(name):
        os.environ[name] = value


def _normalize_google_credentials() -> None:
    raw_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not raw_path:
        return

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return

    for base in (PROJECT_ROOT, BACKEND_DIR):
        candidate = (base / path).resolve()
        if candidate.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(candidate)
            return


def load_environment() -> None:
    """
    Load root and backend env files in a predictable order.

    The project-level .env is the deployment contract used by docker-compose.
    backend/.env can fill local-only gaps, but should not override values that
    were already injected by the shell, Docker, or the project .env.
    """
    global _LOADED
    if _LOADED:
        return

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)

    _set_if_missing("SUPABASE_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    _set_if_missing("SUPABASE_KEY", os.environ.get("SUPABASE_ANON_KEY"))
    _set_if_missing("SUPABASE_KEY", os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"))
    _set_if_missing("SUPABASE_ANON_KEY", os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"))
    _set_if_missing("NEXT_PUBLIC_SUPABASE_URL", os.environ.get("SUPABASE_URL"))
    _set_if_missing("NEXT_PUBLIC_SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY"))

    _set_if_missing("GOOGLE_CLOUD_PROJECT", os.environ.get("VERTEX_PROJECT_ID"))
    _set_if_missing("VERTEX_PROJECT_ID", os.environ.get("GOOGLE_CLOUD_PROJECT"))
    _set_if_missing("GOOGLE_CLOUD_LOCATION", os.environ.get("VERTEX_LOCATION"))
    _set_if_missing("VERTEX_LOCATION", os.environ.get("GOOGLE_CLOUD_LOCATION"))

    _normalize_google_credentials()
    _LOADED = True
