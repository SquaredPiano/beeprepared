"""
Central configuration for the BeePrepared backend.

Everything that reads an environment variable should read it from here, so that
there is exactly one place that documents what the service needs to run and one
place that decides what "configured" means.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from backend.env import load_environment

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = _env(name)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the process configuration."""

    # --- Database -----------------------------------------------------------
    database_backend: str = "auto"  # auto | local | supabase
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_anon_key: str = ""

    # --- LLM ----------------------------------------------------------------
    llm_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    llm_max_concurrency: int = 6
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 3
    llm_max_output_tokens: int = 16384

    # --- Storage ------------------------------------------------------------
    storage_backend: str = "auto"  # auto | local | r2
    storage_dir: Path = field(default_factory=lambda: BACKEND_DIR / ".storage")
    storage_signing_secret: str = "beeprepared-dev-secret"
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""

    # --- Queue / workers ----------------------------------------------------
    redis_url: str = ""
    celery_enabled: bool = True
    worker_concurrency: int = 4
    job_timeout_seconds: int = 900
    job_max_attempts: int = 3
    stale_job_seconds: int = 1800

    # --- HTTP ---------------------------------------------------------------
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000"])
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    allow_mock_auth: bool = False
    upload_max_mb: int = 200

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def has_r2(self) -> bool:
        return bool(
            self.r2_endpoint_url
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket_name
        )

    @property
    def has_redis(self) -> bool:
        return bool(self.redis_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (once) the settings snapshot for this process."""
    load_environment()

    storage_dir = _env("BEE_STORAGE_DIR") or str(BACKEND_DIR / ".storage")

    return Settings(
        database_backend=_env("DATABASE_BACKEND", "auto").lower(),
        supabase_url=_env("SUPABASE_URL"),
        supabase_key=_env("SUPABASE_KEY"),
        supabase_anon_key=_env("SUPABASE_ANON_KEY"),
        llm_provider=_env("LLM_PROVIDER", "openrouter").lower(),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_model=_env("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        gemini_api_key=_env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
        vertex_project_id=_env("VERTEX_PROJECT_ID") or _env("GOOGLE_CLOUD_PROJECT"),
        vertex_location=_env("VERTEX_LOCATION") or _env("GOOGLE_CLOUD_LOCATION", "us-central1"),
        llm_max_concurrency=_env_int("LLM_MAX_CONCURRENCY", 6),
        llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", 180),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 3),
        llm_max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", 16384),
        storage_backend=_env("STORAGE_BACKEND", "auto").lower(),
        storage_dir=Path(storage_dir).expanduser(),
        storage_signing_secret=_env("STORAGE_SIGNING_SECRET", "beeprepared-dev-secret"),
        r2_endpoint_url=_env("R2_ENDPOINT_URL"),
        r2_access_key_id=_env("R2_ACCESS_KEY_ID"),
        r2_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
        r2_bucket_name=_env("R2_BUCKET_NAME"),
        redis_url=_env("REDIS_URL"),
        celery_enabled=_env_bool("CELERY_ENABLED", True),
        worker_concurrency=_env_int("WORKER_CONCURRENCY", 4),
        job_timeout_seconds=_env_int("JOB_TIMEOUT_SECONDS", 900),
        job_max_attempts=_env_int("JOB_MAX_ATTEMPTS", 3),
        stale_job_seconds=_env_int("STALE_JOB_SECONDS", 1800),
        cors_origins=_env_list("CORS_ORIGINS", ["http://localhost:3000"]),
        api_host=_env("API_HOST", "0.0.0.0"),
        api_port=_env_int("API_PORT", 8000),
        allow_mock_auth=_env_bool("ALLOW_MOCK_AUTH", False),
        upload_max_mb=_env_int("MAX_FILE_SIZE_MB", 200),
    )
