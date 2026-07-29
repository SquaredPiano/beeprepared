"""Selects the language-model provider and the transcriber for this process."""

from __future__ import annotations

import logging
import threading

from backend.core.config import get_settings
from backend.llm.base import LLMProvider, SpeechToText
from backend.llm.deepgram import DeepgramTranscriber
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


class FallbackTranscriber:
    """
    Hands a recording to a second transcriber when the first one cannot do it.

    A key that stops working, or a bad ten minutes at a speech service, should
    not cost somebody the lecture they just uploaded while there is another
    transcriber configured. So a failure in the preferred one is a warning and a
    second attempt elsewhere rather than the end of the job.
    """

    supports_audio = True

    def __init__(self, preferred: SpeechToText, backup: SpeechToText) -> None:
        self._preferred = preferred
        self._backup = backup

    @property
    def name(self) -> str:
        return f"{self._preferred.name} then {self._backup.name}"

    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words, from whichever transcriber manages it."""
        try:
            return await self._preferred.transcribe(audio_path)
        except Exception as preferred_error:
            logger.warning(
                "%s could not transcribe the recording (%s). Trying %s instead.",
                self._preferred.name, preferred_error, self._backup.name,
            )
            return await self._backup_attempt(audio_path, preferred_error)

    async def _backup_attempt(self, audio_path: str, preferred_error: Exception) -> str:
        """
        Transcribe with the backup, reporting the first failure if it fails too.

        The first error is the one that reaches the job, for two reasons. It
        says why the transcriber we meant to use did not work, and the job
        runner reads it to decide whether trying again is worth anything. The
        backup is often the offline provider, whose only answer is that it
        cannot do audio at all, and a job that failed on a Deepgram timeout
        would then look permanent and never be retried.
        """
        try:
            return await self._backup.transcribe(audio_path)
        except Exception as backup_error:
            logger.warning(
                "%s could not transcribe it either (%s)", self._backup.name, backup_error
            )
            raise preferred_error


def build_transcriber() -> SpeechToText:
    """
    Return the transcriber recordings should go to.

    Deepgram comes first whenever a key is configured, because it is built for
    speech and does a better job on a long lecture than a general model does.
    The language model stays behind it as the fallback, so either key on its own
    is enough to transcribe with, and with both a bad day at Deepgram doesn't
    stop the job. With neither, this is the offline provider, which is what
    raises the error saying transcription isn't configured.

    Nothing is cached here. The provider behind it already is, and building this
    is a couple of objects, so the alternative is a second piece of process
    state that every test and every worker has to remember to reset.
    """
    if not get_settings().has_deepgram_key:
        return get_provider()

    return FallbackTranscriber(DeepgramTranscriber(), get_provider())
