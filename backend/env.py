"""Environment file loading."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

_loaded = False


def load_environment() -> None:
    """Load the project and backend env files, once, without overriding the shell."""
    global _loaded
    if _loaded:
        return

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)
    _loaded = True
