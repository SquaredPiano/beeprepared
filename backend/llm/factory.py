"""Selects and caches the language-model provider for this process."""

from __future__ import annotations

import logging
import threading

from backend.core.config import get_settings
from backend.llm.base import LLMProvider
from backend.llm.offline import OfflineProvider
from backend.llm.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

_provider: LLMProvider | None = None
_lock = threading.Lock()


def build_provider() -> LLMProvider:
    """Return OpenRouter when a key is configured, otherwise the offline provider."""
    if not get_settings().has_llm_key:
        return OfflineProvider()

    try:
        return OpenRouterProvider()
    except Exception as error:
        logger.warning("OpenRouter unavailable (%s). Falling back to the offline provider.", error)
        return OfflineProvider()


def get_provider() -> LLMProvider:
    """The shared provider, constructed on first use."""
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                _provider = build_provider()
                logger.info("LLM provider: %s", _provider.name)
    return _provider


def reset_provider() -> None:
    """Discard the cached provider so the next call rebuilds it."""
    global _provider
    with _lock:
        _provider = None
