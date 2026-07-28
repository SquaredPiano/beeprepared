"""OpenRouter provider: one key, any hosted model, plus audio transcription."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import httpx

from backend.core.config import get_settings
from backend.llm.base import LLMError, LLMProvider, Schema
from backend.llm.schema import parse_as, strict_schema

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

SYSTEM_PROMPT = (
    "You are a precise academic content engine. Follow the user's instructions "
    "exactly and never pad your answer with commentary."
)

SCHEMA_PROMPT = (
    " Respond with a single JSON document that validates against the provided "
    "schema. Emit no prose, no explanation and no code fences."
)

TRANSCRIBE_PROMPT = (
    "Transcribe this recording verbatim. Output only the transcript: no speaker "
    "labels, no timestamps, no commentary."
)


class PermanentFailure(LLMError):
    """The request would fail identically however many times it is repeated."""


class TruncatedResponse(PermanentFailure):
    """The model ran out of output budget mid-document."""


class TransientFailure(LLMError, ConnectionError):
    """
    Every attempt failed on a fault a later attempt could still survive.

    Only retryable faults reach this class: `PermanentFailure` leaves the send
    loop untouched, so anything that exhausts the retries is by construction a
    failure to complete the exchange with OpenRouter at all.

    The base classes are the payload. `backend.services.job_runner.is_transient`
    classifies by exception type first and only then falls back to matching the
    message, and the message is worthless here: `str(httpx.ConnectTimeout(""))`
    is empty, and a refused connection reads "[Errno 61] Connection refused",
    which no transient phrase covers. Timeouts and refusals are the two most
    common real failures, so a wrapper that kept only the text would have every
    job give up on the very errors retrying exists for.
    """


class OpenRouterProvider(LLMProvider):
    """Talks to OpenRouter's OpenAI-compatible endpoint."""

    name = "openrouter"
    supports_audio = True

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY is not set")

        self._url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        self._model = settings.openrouter_model
        self._timeout = settings.llm_timeout_seconds
        self._max_retries = settings.llm_max_retries
        self._max_output_tokens = settings.llm_max_output_tokens
        self._concurrency = settings.llm_max_concurrency
        self._limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
            weakref.WeakKeyDictionary()
        )
        self._headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://beeprepared.app",
            "X-Title": "BeePrepared",
        }

        logger.info("OpenRouter ready (model=%s)", self._model)

    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        return await self._send(self._text_request(prompt, context))

    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        raw = await self._send(self._schema_request(prompt, schema, context))
        try:
            return parse_as(raw, schema)
        except Exception as error:
            preview = raw[:300].replace("\n", " ")
            raise LLMError(f"Response did not match {schema.__name__}: {error}. Got: {preview}") from error

    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words in an audio file."""
        return await self._send(await asyncio.to_thread(self._audio_request, audio_path))

    def _text_request(self, prompt: str, context: Optional[str]) -> Dict[str, Any]:
        return self._request(SYSTEM_PROMPT, self._user_text(prompt, context), temperature=0.7)

    def _schema_request(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str],
    ) -> Dict[str, Any]:
        contract = strict_schema(schema)
        content = (
            f"{self._user_text(prompt, context)}\n\n"
            f"--- REQUIRED JSON SCHEMA ---\n{json.dumps(contract, indent=2)}"
        )
        body = self._request(SYSTEM_PROMPT + SCHEMA_PROMPT, content, temperature=0.4)
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": True, "schema": contract},
        }
        return body

    def _audio_request(self, audio_path: str) -> Dict[str, Any]:
        path = Path(audio_path)
        if not path.exists():
            raise LLMError(f"Audio file not found: {audio_path}")

        encoded = base64.b64encode(path.read_bytes()).decode()
        audio_format = path.suffix.lstrip(".").lower() or "wav"

        body = self._request(
            "You are a transcription engine. Return only the spoken words.",
            TRANSCRIBE_PROMPT,
            temperature=0.0,
        )
        body["messages"][-1]["content"] = [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "input_audio", "input_audio": {"data": encoded, "format": audio_format}},
        ]
        return body

    def _request(self, system: str, user: str, *, temperature: float) -> Dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self._max_output_tokens,
        }

    @staticmethod
    def _user_text(prompt: str, context: Optional[str]) -> str:
        if not context:
            return prompt
        return f"{prompt}\n\n--- SOURCE MATERIAL ---\n{context}"

    async def _send(self, body: Dict[str, Any]) -> str:
        """
        Post one request, retrying only what a retry could fix.

        A rejected key, a malformed request and a truncated document all fail
        the same way on every attempt, so they surface immediately instead of
        spending the whole output budget twice more to say so again.
        """
        last_error: Optional[Exception] = None

        async with self._limiter():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for attempt in range(self._max_retries):
                    try:
                        response = await client.post(self._url, headers=self._headers, json=body)
                        return self._content_of(self._checked(response))
                    except PermanentFailure:
                        raise
                    except Exception as error:
                        last_error = error
                        if attempt == self._max_retries - 1:
                            break
                        delay = self._backoff(attempt)
                        logger.warning(
                            "OpenRouter attempt %d/%d failed (%s); retrying in %.1fs",
                            attempt + 1, self._max_retries, self._describe(error), delay,
                        )
                        await asyncio.sleep(delay)

        raise TransientFailure(
            f"OpenRouter failed after {self._max_retries} attempts: {self._describe(last_error)}"
        ) from last_error

    def _limiter(self) -> asyncio.Semaphore:
        """
        The semaphore belonging to the caller's event loop.

        A semaphore binds itself to the first loop that contends on it and
        refuses every other one, so the provider keeps one per loop. The loop
        itself is the key: `id()` is recycled once a loop is collected, which
        would hand a fresh loop the dead loop's semaphore, and holding the loop
        weakly keeps the table from growing for the life of the process.
        """
        loop = asyncio.get_running_loop()
        limiter = self._limiters.get(loop)
        if limiter is None:
            limiter = asyncio.Semaphore(self._concurrency)
            self._limiters[loop] = limiter
        return limiter

    @staticmethod
    def _checked(response: httpx.Response) -> Dict[str, Any]:
        if response.status_code in RETRYABLE_STATUS:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise PermanentFailure(f"HTTP {response.status_code}: {response.text[:400]}")
        return response.json()

    @staticmethod
    def _content_of(payload: Dict[str, Any]) -> str:
        choices: List[Dict[str, Any]] = payload.get("choices") or []
        if not choices:
            raise LLMError(f"OpenRouter returned no choices: {json.dumps(payload)[:300]}")

        choice = choices[0]
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            raise LLMError("OpenRouter returned an empty completion")

        if choice.get("finish_reason") == "length":
            raise TruncatedResponse(
                f"The model hit its output limit after {len(content)} characters. "
                "Raise LLM_MAX_OUTPUT_TOKENS or request a smaller artifact."
            )
        return content

    @staticmethod
    def _describe(error: Optional[BaseException]) -> str:
        """
        Name a failure for the operator reading the job's error column.

        Several httpx transport errors stringify to nothing at all, so the class
        name has to stand in or the record says only how many attempts were made.
        """
        if error is None:
            return "no attempt was made"
        detail = str(error)
        name = type(error).__name__
        return f"{name}: {detail}" if detail else name

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2 ** attempt, 16) + random.uniform(0, 0.75)
