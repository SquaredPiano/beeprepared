"""Audio normalisation and speech-to-text."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

import ffmpeg

from backend.llm.base import SpeechToText
from backend.llm.factory import build_transcriber

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

    Media is normalised first so the speech service always receives the same
    encoding, whatever the user uploaded.

    Which service that is comes from `build_transcriber`, so this class never
    has to know whether the words came from Deepgram or from a language model.
    """

    def __init__(self, speech: Optional[SpeechToText] = None) -> None:
        self._speech = speech or build_transcriber()

    @property
    def available(self) -> bool:
        return self._speech.supports_audio

    async def transcribe(self, media_path: str) -> str:
        """
        Return the spoken words in an audio or video file.

        ffmpeg runs off the event loop: a lecture-length recording takes it
        minutes, and the local worker pool shares its loop with the API.
        """
        if not self.available:
            raise MediaError(
                "Transcription needs a speech service or a language model that accepts "
                "audio. Set DEEPGRAM_KEY or OPENROUTER_API_KEY to enable it."
            )

        with tempfile.TemporaryDirectory() as workspace:
            wav_path = await asyncio.to_thread(
                to_wav, media_path, os.path.join(workspace, "audio.wav")
            )
            transcript = await self._speech.transcribe(wav_path)

        if not transcript.strip():
            raise MediaError("The recording produced an empty transcript")

        logger.info("Transcribed %d characters", len(transcript))
        return transcript.strip()
