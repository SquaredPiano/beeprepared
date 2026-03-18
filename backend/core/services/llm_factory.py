"""
LLM provider selection.

Resolution order:

1. ``LLM_PROVIDER`` names a provider explicitly (openrouter | gemini | vertex |
   offline). A named provider that fails to construct falls through rather than
   crashing the worker, because a bad key should degrade the product, not stop it.
2. Otherwise the first provider whose credentials are present wins.
3. If nothing is configured, the offline heuristic provider is used so the
   pipeline still runs end to end.

The chosen provider is cached: constructing one opens HTTP clients and reads
service-account files, and every generator would otherwise build its own.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from backend.core.config import get_settings
from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER: Optional[LLMProvider] = None
_LOCK = threading.Lock()


def _construct(name: str) -> LLMProvider:
    if name == "openrouter":
        from backend.core.services.llm_openrouter import OpenRouterLLM

        return OpenRouterLLM()
    if name == "gemini":
        from backend.core.services.llm_gemini import GeminiLLM

        return GeminiLLM()
    if name == "vertex":
        from backend.core.services.llm_vertex import VertexLLM

        return VertexLLM()
    if name == "offline":
        from backend.core.services.llm_offline import OfflineLLM

        return OfflineLLM()
    raise ValueError(f"Unknown LLM provider: {name}")


def _candidates() -> list[str]:
    """Providers to try, most-preferred first, based on what is configured."""
    settings = get_settings()
    ordered: list[str] = []

    requested = settings.llm_provider
    if requested and requested != "auto":
        ordered.append(requested)

    if settings.openrouter_api_key:
        ordered.append("openrouter")
    if settings.gemini_api_key:
        ordered.append("gemini")
    if settings.vertex_project_id:
        ordered.append("vertex")
    ordered.append("offline")

    seen: set[str] = set()
    return [name for name in ordered if not (name in seen or seen.add(name))]


class LLMFactory:
    @staticmethod
    def get_provider() -> LLMProvider:
        """The process-wide provider. Built once, then reused."""
        global _PROVIDER
        if _PROVIDER is None:
            with _LOCK:
                if _PROVIDER is None:
                    _PROVIDER = LLMFactory.build()
        return _PROVIDER

    @staticmethod
    def build() -> LLMProvider:
        errors: list[str] = []
        for name in _candidates():
            try:
                provider = _construct(name)
                logger.info("LLM provider: %s", name)
                return provider
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("LLM provider '%s' unavailable: %s", name, exc)

        raise RuntimeError("No LLM provider could be constructed: " + "; ".join(errors))

    @staticmethod
    def reset() -> None:
        """Drop the cached provider. Used by tests and config reloads."""
        global _PROVIDER
        with _LOCK:
            _PROVIDER = None

    @staticmethod
    def is_offline() -> bool:
        return getattr(LLMFactory.get_provider(), "is_offline", False)
