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

TRANSCRIBED_SOURCE_TYPES = frozenset({"audio", "video", "youtube"})

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
REPEATED_PERIODS = re.compile(r"\.{2,}")
WHITESPACE = re.compile(r"\s+")

INVISIBLE_CHARACTERS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b\ufeff]")
HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
LINE_PADDING = re.compile(r" ?\n ?")
BLANK_LINES = re.compile(r"\n{3,}")
SPACE_BEFORE_PUNCTUATION = re.compile(r"[^\S\n]+([.,!?;:])")

MARKDOWN_MARKS = (
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"\*([^*]+)\*"), r"\1"),
    (re.compile(r"__([^_]+)__"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
)


class TextCleaner:
    """
    Cleans text with the rules the source it came from can survive.

    Transcribed speech is prose and nothing else, so it can afford the
    destructive rules: parentheses and brackets there hold `(laughs)` and
    `[inaudible]`, line breaks hold nothing, and a model pass is worth its risk
    because transcription really does produce broken grammar.

    A document is not prose alone. Parentheses and brackets carry meaning
    (`f(x)`, `[0,1]`, `O(n log n)`, bracketed citations), a colon follows words
    like `NOTE` and numbers like `3:14`, and the page and slide markers the
    readers insert are structure the material is navigated by. Documents
    therefore get whitespace normalisation and nothing that can delete a
    character the author typed.

    `clean` is the conservative path and holds the plain name on purpose: a
    caller that does not know which kind of source it is holding must not be
    able to destroy notation by accident, so the transcript rules have to be
    asked for by name.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def clean(self, text: str) -> str:
        """
        Return the cleaned form of text that was read out of a document.

        Awaitable but modelless, and deliberately so. The repair pass rewrites
        prose and rejoins its chunks as one line, which would flatten the page
        markers and let a model reword mathematics it was never asked to touch.
        A typed document has no transcription errors to repair, so the whole
        risk would buy nothing.
        """
        return self.strip_document_noise(text)

    async def clean_transcript(self, text: str, *, use_model: bool = True) -> str:
        """Return the cleaned form of text that came out of transcription."""
        cleaned = self.strip_transcript_noise(text)
        if use_model and cleaned:
            cleaned = await self._repair(cleaned)
        return cleaned

    @staticmethod
    def strip_document_noise(text: str) -> str:
        """
        Normalise whitespace and drop characters that carry no text at all.

        Everything a reader emitted deliberately survives: notation, brackets,
        punctuation and the `--- Page N ---` and `--- Slide N ---` markers,
        which is why line breaks are preserved rather than collapsed. Only
        extraction artefacts go: form feeds, soft hyphens, zero-width spaces,
        ragged spacing and the run of blank lines a page break leaves behind.
        """
        if not text:
            return ""

        text = INVISIBLE_CHARACTERS.sub("", text)
        text = HORIZONTAL_WHITESPACE.sub(" ", text)
        text = LINE_PADDING.sub("\n", text)
        text = SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
        return BLANK_LINES.sub("\n\n", text).strip()

    @staticmethod
    def strip_transcript_noise(text: str) -> str:
        """
        Delete every parenthesised and bracketed span, plus timestamps, shouted
        speaker labels and fillers, then flatten the layout.

        Safe only on transcribed speech. The same four rules that remove
        `(laughs)`, `[inaudible]`, `SPEAKER:` and `12:34` will remove `f(x)`,
        `[0,1]`, `NOTE:` and `3:14`, so a document must never reach them.
        """
        if not text:
            return ""

        for pattern in TRANSCRIPT_NOISE:
            text = pattern.sub("", text)

        text = FILLERS.sub("", text)
        text = WHITESPACE.sub(" ", text)
        text = SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
        return REPEATED_PERIODS.sub(".", text).strip()

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
