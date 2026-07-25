"""Audio normalisation and speech-to-text."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

import ffmpeg

from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1


class MediaError(RuntimeError):
    """Audio could not be converted or transcribed."""


def to_wav(source_path: str, target_path: str) -> str:
    """Convert any audio or video file to 16 kHz mono PCM WAV."""
    logger.info("Normalising audio: %s", os.path.basename(source_path))
    try:
        (
            ffmpeg
            .input(source_path)
            .output(target_path, acodec="pcm_s16le", ac=CHANNELS, ar=str(SAMPLE_RATE))
            .overwrite_output()
            .run(quiet=True, capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as error:
        detail = error.stderr.decode() if error.stderr else str(error)
        raise MediaError(f"ffmpeg could not convert {source_path}: {detail}") from error

    return target_path


class Transcriber:
    """
    Turns recordings into text.

    Media is normalised first so the model always receives the same encoding,
    whatever the user uploaded.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    @property
    def available(self) -> bool:
        return self._provider.supports_audio

    async def transcribe(self, media_path: str) -> str:
        """
        Return the spoken words in an audio or video file.

        ffmpeg runs off the event loop: a lecture-length recording takes it
        minutes, and the local worker pool shares its loop with the API.
        """
        if not self.available:
            raise MediaError(
                "Transcription needs a language model that accepts audio. "
                "Set OPENROUTER_API_KEY to enable it."
            )

        with tempfile.TemporaryDirectory() as workspace:
            wav_path = await asyncio.to_thread(
                to_wav, media_path, os.path.join(workspace, "audio.wav")
            )
            transcript = await self._provider.transcribe(wav_path)

        if not transcript.strip():
            raise MediaError("The recording produced an empty transcript")

        logger.info("Transcribed %d characters", len(transcript))
        return transcript.strip()
