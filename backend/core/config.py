"""Process configuration, resolved once from the environment."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from backend.env import load_environment

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent

PUBLISHED_SECRETS = frozenset({"beeprepared-dev-secret", "change-me-in-production"})


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


class LocalSigningSecret:
    """
    A per-installation HMAC key for a deployment that never configured one.

    A download link is unforgeable only while its key is private, and this
    repository published two: `beeprepared-dev-secret` as this module's default
    and `change-me-in-production` in `.env.example` and `docker-compose.yml`.
    Against either, anyone who has read the project can mint a valid link for
    any object in the store with no session at all, so neither is used and
    there is no default value here any more.

    Refusing to run a fresh clone would be worse than the hole it closes, so the
    first process that needs a key mints one and persists it next to the data it
    protects. Later processes, including the Celery workers sharing that volume,
    read the same file, which is what keeps outstanding links valid across a
    restart. Creation is exclusive, so two processes starting together cannot
    each install a different key.
    """

    FILENAME = "signing_secret.key"
    RANDOM_BYTES = 32

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / self.FILENAME

    def read_or_create(self) -> str:
        """The persisted key for this installation, minting it on first use."""
        return self._read() or self._create()

    def _read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _create(self) -> str:
        minted = secrets.token_hex(self.RANDOM_BYTES)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        try:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self._read() or minted

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(minted)

        logger.info("Minted a private signing key at %s", self._path)
        return minted


def _signing_secret(data_dir: Path) -> str:
    """
    The key download links are signed with, never a value published in the repo.

    A configured value is honoured unless it is one of those published values,
    which is the same as having configured nothing at all.
    """
    configured = _text("SIGNING_SECRET")
    if configured and configured not in PUBLISHED_SECRETS:
        return configured

    logger.warning(
        "SIGNING_SECRET is unset or still a published default; signing links with the "
        "private key kept under %s instead. Set SIGNING_SECRET to a private random "
        "value to share links across installations.",
        data_dir,
    )
    return LocalSigningSecret(data_dir).read_or_create()


@dataclass(frozen=True)
class Settings:
    """
    Everything the backend needs to run, with a working default for each.

    `signing_secret` is the exception: it has no default because a published one
    is a forgeable one. `get_settings` resolves it to a private value.
    """

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_max_concurrency: int = 6
    llm_max_output_tokens: int = 16384
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 3

    deepgram_key: str = ""
    deepgram_model: str = "nova-2"
    deepgram_timeout_seconds: int = 600

    data_dir: Path = field(default_factory=lambda: BACKEND_DIR / ".storage")
    signing_secret: str = ""

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
    def has_deepgram_key(self) -> bool:
        """
        Whether recordings can go to Deepgram.

        Deepgram only transcribes, so this is separate from `has_llm_key`: a
        deployment can have either key, both, or neither, and each combination
        has to work.
        """
        return bool(self.deepgram_key)

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

    data_dir = Path(
        _text("BEE_DATA_DIR") or _text("BEE_STORAGE_DIR") or str(BACKEND_DIR / ".storage")
    ).expanduser()

    return Settings(
        openrouter_api_key=_text("OPENROUTER_API_KEY"),
        openrouter_model=_text("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        openrouter_base_url=_text("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_max_concurrency=_number("LLM_MAX_CONCURRENCY", 6),
        llm_max_output_tokens=_number("LLM_MAX_OUTPUT_TOKENS", 16384),
        llm_timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 180),
        llm_max_retries=_number("LLM_MAX_RETRIES", 3),
        deepgram_key=_text("DEEPGRAM_KEY"),
        deepgram_model=_text("DEEPGRAM_MODEL", "nova-2"),
        deepgram_timeout_seconds=_number("DEEPGRAM_TIMEOUT_SECONDS", 600),
        data_dir=data_dir,
        signing_secret=_signing_secret(data_dir),
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
