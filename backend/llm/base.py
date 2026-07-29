"""The interface every language-model provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

Schema = TypeVar("Schema", bound=BaseModel)


class LLMError(RuntimeError):
    """The model could not produce a usable response."""


class SpeechToText(Protocol):
    """
    Anything that can turn a recording into text.

    Transcription is a different job from writing text, and the two don't have
    to come from the same vendor. Keeping it in its own protocol lets a speech
    service stand in without pretending to be a language model, and any
    `LLMProvider` already satisfies it.

    `supports_audio` is how a transcriber says it can't actually do the work.
    The pipeline reads it so it can explain why instead of trying anyway.
    """

    name: str
    supports_audio: bool

    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words in an audio file."""


class LLMProvider(ABC):
    """
    Generates text or a validated Pydantic model from a prompt.

    Callers depend on this interface rather than on any particular vendor, so
    swapping providers never reaches beyond this package.
    """

    name: str = "unknown"
    supports_audio: bool = False

    @abstractmethod
    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        """Return free-form text."""

    @abstractmethod
    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        """Return a response validated against `schema`."""

    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words in an audio file."""
        raise LLMError(f"{self.name} cannot transcribe audio")
