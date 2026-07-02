"""OpenRouter provider: one key, any hosted model, plus audio transcription."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
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


class TruncatedResponse(LLMError):
    """The model ran out of output budget mid-document."""


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
        self._limiters: Dict[int, asyncio.Semaphore] = {}
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
        return await self._send(self._audio_request(audio_path))

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
        last_error: Optional[Exception] = None

        async with self._limiter():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for attempt in range(self._max_retries):
                    try:
                        response = await client.post(self._url, headers=self._headers, json=body)
                        return self._content_of(self._checked(response))
                    except Exception as error:
                        last_error = error
                        if attempt == self._max_retries - 1:
                            break
                        delay = self._backoff(attempt)
                        logger.warning(
                            "OpenRouter attempt %d/%d failed (%s); retrying in %.1fs",
                            attempt + 1, self._max_retries, error, delay,
                        )
                        await asyncio.sleep(delay)

        raise LLMError(f"OpenRouter failed after {self._max_retries} attempts: {last_error}")

    def _limiter(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._limiters:
            self._limiters[loop_id] = asyncio.Semaphore(self._concurrency)
        return self._limiters[loop_id]

    @staticmethod
    def _checked(response: httpx.Response) -> Dict[str, Any]:
        if response.status_code in RETRYABLE_STATUS:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:400]}")
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
    def _backoff(attempt: int) -> float:
        return min(2 ** attempt, 16) + random.uniform(0, 0.75)
