"""Turns raw extracted text into clean prose."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider

logger = logging.getLogger(__name__)

CHUNK_SIZE = 4_000

REPAIR_PROMPT = """
You are an expert editor working on a lecture transcript.

Fix grammar, punctuation and transcription errors, and standardise terminology.
Keep the meaning identical and preserve every idea. Do NOT summarise, shorten or
reorder the content. Output plain text only.
"""

TRANSCRIPT_NOISE = (
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b"),
    re.compile(r"\b[A-Z]{2,}:\s*"),
    re.compile(r"\([^)]*\)"),
    re.compile(r"\[[^\]]*\]"),
)

FILLERS = re.compile(r"\b(um|uh|ah|er|hmm)\b", re.IGNORECASE)
SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,!?;:])")
REPEATED_PERIODS = re.compile(r"\.{2,}")
WHITESPACE = re.compile(r"\s+")

MARKDOWN_MARKS = (
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"\*([^*]+)\*"), r"\1"),
    (re.compile(r"__([^_]+)__"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
)


class TextCleaner:
    """
    Cleans text in two passes.

    Rules strip the mechanical noise that regular expressions handle well, then
    a model repairs grammar across chunks that are processed concurrently.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def clean(self, text: str, *, use_model: bool = True) -> str:
        """Return the cleaned form of `text`."""
        cleaned = self.strip_noise(text)
        if use_model and cleaned:
            cleaned = await self._repair(cleaned)
        return cleaned

    @staticmethod
    def strip_noise(text: str) -> str:
        """Remove timestamps, speaker labels, asides and filler words."""
        if not text:
            return ""

        for pattern in TRANSCRIPT_NOISE:
            text = pattern.sub("", text)

        text = FILLERS.sub("", text)
        text = SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
        text = REPEATED_PERIODS.sub(".", text)
        return WHITESPACE.sub(" ", text).strip()

    async def _repair(self, text: str) -> str:
        """
        Rewrite every chunk concurrently, keeping the original where one fails.

        `gather` reports failures as values rather than raising, and a cancelled
        chunk arrives as a `BaseException` that `Exception` would not catch,
        which would put an exception object into the joined text.
        """
        chunks = self._chunks(text)
        logger.info("Repairing %d chunk(s) of transcript", len(chunks))

        results = await asyncio.gather(
            *(self._repair_chunk(chunk) for chunk in chunks),
            return_exceptions=True,
        )

        repaired = [
            chunk if isinstance(result, BaseException) else result
            for chunk, result in zip(chunks, results)
        ]
        failures = sum(1 for result in results if isinstance(result, BaseException))
        if failures:
            logger.warning("%d/%d chunks kept their original text", failures, len(chunks))

        return WHITESPACE.sub(" ", " ".join(repaired)).strip()

    async def _repair_chunk(self, chunk: str) -> str:
        response = await self._provider.complete(REPAIR_PROMPT, context=chunk)
        return self.strip_markdown(response.strip()) if response else chunk

    @staticmethod
    def _chunks(text: str) -> List[str]:
        return [text[index : index + CHUNK_SIZE] for index in range(0, len(text), CHUNK_SIZE)]

    @staticmethod
    def strip_markdown(text: str) -> str:
        """Remove Markdown emphasis a model may have added to plain prose."""
        for pattern, replacement in MARKDOWN_MARKS:
            text = pattern.sub(replacement, text)
        return WHITESPACE.sub(" ", text).strip()
