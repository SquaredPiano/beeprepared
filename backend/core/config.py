"""Process configuration, resolved once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from backend.env import load_environment

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool) -> bool:
    raw = _text(name).lower()
    return raw in {"1", "true", "yes", "on"} if raw else default


def _number(name: str, default: int) -> int:
    try:
        return int(_text(name) or default)
    except ValueError:
        return default


def _list(name: str, default: List[str]) -> List[str]:
    raw = _text(name)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else list(default)


@dataclass(frozen=True)
class Settings:
    """Everything the backend needs to run, with a working default for each."""

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_max_concurrency: int = 6
    llm_max_output_tokens: int = 16384
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 3

    data_dir: Path = field(default_factory=lambda: BACKEND_DIR / ".storage")
    signing_secret: str = "beeprepared-dev-secret"

    redis_url: str = ""
    celery_enabled: bool = True
    worker_concurrency: int = 4
    job_timeout_seconds: int = 900
    job_max_attempts: int = 3
    stale_job_seconds: int = 1800

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000"])
    upload_max_mb: int = 200

    @property
    def has_llm_key(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_redis(self) -> bool:
        return bool(self.redis_url)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "beeprepared.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build the settings snapshot for this process, once."""
    load_environment()

    data_dir = _text("BEE_DATA_DIR") or _text("BEE_STORAGE_DIR") or str(BACKEND_DIR / ".storage")

    return Settings(
        openrouter_api_key=_text("OPENROUTER_API_KEY"),
        openrouter_model=_text("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        openrouter_base_url=_text("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_max_concurrency=_number("LLM_MAX_CONCURRENCY", 6),
        llm_max_output_tokens=_number("LLM_MAX_OUTPUT_TOKENS", 16384),
        llm_timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 180),
        llm_max_retries=_number("LLM_MAX_RETRIES", 3),
        data_dir=Path(data_dir).expanduser(),
        signing_secret=_text("SIGNING_SECRET", "beeprepared-dev-secret"),
        redis_url=_text("REDIS_URL"),
        celery_enabled=_flag("CELERY_ENABLED", True),
        worker_concurrency=_number("WORKER_CONCURRENCY", 4),
        job_timeout_seconds=_number("JOB_TIMEOUT_SECONDS", 900),
        job_max_attempts=_number("JOB_MAX_ATTEMPTS", 3),
        stale_job_seconds=_number("STALE_JOB_SECONDS", 1800),
        api_host=_text("API_HOST", "0.0.0.0"),
        api_port=_number("API_PORT", 8000),
        cors_origins=_list("CORS_ORIGINS", ["http://localhost:3000"]),
        upload_max_mb=_number("MAX_FILE_SIZE_MB", 200),
    )
