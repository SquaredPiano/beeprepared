"""Deepgram: speech recognition for the transcription step, and nothing else."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

import httpx

from backend.core.config import get_settings
from backend.llm.base import LLMError

logger = logging.getLogger(__name__)

LISTEN_URL = "https://api.deepgram.com/v1/listen"

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class DeepgramTranscriber:
    """
    Sends a recording to Deepgram and returns what it heard.

    Deepgram is built for speech, and it does a much better job on a two-hour
    lecture than a general model reading audio does. So when there's a key for
    it, this is the transcriber we want.

    It can't write text, so it isn't an `LLMProvider`. All it implements is
    `SpeechToText`, which keeps the rest of the pipeline from reaching for it by
    mistake.

    Nothing here retries. A request either works or comes back with a reason,
    and two things already cover the reasons worth another go: the transcriber
    behind this one, and the job runner, which reads the error and requeues the
    job when trying again could help.
    """

    name = "deepgram"
    supports_audio = True

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.has_deepgram_key:
            raise LLMError("DEEPGRAM_KEY is not set")

        self._model = settings.deepgram_model
        self._timeout = settings.deepgram_timeout_seconds
        self._headers = {"Authorization": f"Token {settings.deepgram_key}"}

        logger.info("Deepgram ready (model=%s)", self._model)

    async def transcribe(self, audio_path: str) -> str:
        """
        Return the spoken words in an audio file.

        The bytes go up as the body of the request, with no content type on
        them: Deepgram works the format out from the audio itself, so this
        keeps working whatever ffmpeg handed us. Reading the file happens in a
        thread, because an hour of PCM is hundreds of megabytes and the local
        worker pool shares its event loop with the API.
        """
        audio = await asyncio.to_thread(self._read, audio_path)
        logger.info("Sending %d bytes to Deepgram", len(audio))

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                LISTEN_URL, headers=self._headers, params=self._params(), content=audio
            )

        return self._transcript_of(self._checked(response))

    def _params(self) -> Dict[str, str]:
        return {"model": self._model, "smart_format": "true", "punctuate": "true"}

    @staticmethod
    def _read(audio_path: str) -> bytes:
        path = Path(audio_path)
        if not path.exists():
            raise LLMError(f"Audio file not found: {audio_path}")
        return path.read_bytes()

    @staticmethod
    def _checked(response: httpx.Response) -> Dict[str, Any]:
        """
        Turn a refused request into an error the job runner can classify.

        A busy or broken Deepgram is worth another attempt, so its status code
        goes in the message, which is where
        `backend.services.job_runner.is_transient` looks for one. A rejected key
        or a request Deepgram can't parse would fail the same way every time, so
        those messages say nothing that reads as retryable and the job fails
        once instead of three times.

        Deepgram's own words are quoted back, because they name the fault, like
        `INVALID_AUTH`. They never include the key.
        """
        if response.status_code in RETRYABLE_STATUS:
            raise LLMError(f"Deepgram is busy or down: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise LLMError(f"Deepgram refused the request: {response.text[:200]}")
        return response.json()

    @staticmethod
    def _transcript_of(payload: Dict[str, Any]) -> str:
        """
        Pull the transcript out of the response.

        Deepgram nests it under the channel, and then under the reading it liked
        best. There is only ever one channel here, because the pipeline converts
        everything to mono first.

        An empty transcript raises instead of returning nothing. A recording
        that came back with no words in it is a failure worth seeing, and worth
        handing to the transcriber behind this one.
        """
        try:
            transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Deepgram returned a response of an unexpected shape: {error}") from error

        if not transcript.strip():
            raise LLMError("Deepgram returned an empty transcript")

        logger.info("Deepgram transcribed %d characters", len(transcript))
        return transcript
