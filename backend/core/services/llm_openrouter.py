"""
OpenRouter LLM provider.

OpenRouter exposes an OpenAI-compatible ``/chat/completions`` endpoint in front
of most hosted models, which makes it a good default here: one key, one HTTP
contract, and the model can be swapped with an environment variable instead of
a code change.

What this provider adds on top of a raw HTTP call:

- **Structured output.** Pydantic schemas are sent as ``response_format`` JSON
  schema. Models that ignore it still get the schema in the prompt, and the
  response is repaired and re-validated before it reaches a caller.
- **Bounded concurrency.** A semaphore caps in-flight requests so a fan-out of
  twenty generator nodes cannot open twenty upstream sockets at once.
- **Retries with backoff.** 429 and 5xx are transient; they are retried rather
  than surfaced as a failed job.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from backend.core.config import get_settings
from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Raised when the model could not produce a usable response."""


class TruncatedResponse(LLMError):
    """The model ran out of output budget mid-document."""


def _strict_schema(schema: Type[BaseModel]) -> Dict[str, Any]:
    """
    Rewrite a Pydantic JSON Schema into the shape strict structured output wants.

    Pydantic emits nested models as ``$defs`` plus ``$ref`` pointers. Providers
    accept that but cannot enforce it strictly, and in practice a model handed a
    ``$ref``-heavy schema drifts: it stops treating the field bounds as binding
    and runs a single string field until it hits the output limit. Inlining the
    definitions and marking every object closed and fully-required lets strict
    mode do its job - which is the difference between a mind map that returns in
    two seconds and one that burns 100k characters and fails.
    """
    root = schema.model_json_schema()
    definitions = root.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = copy.deepcopy(definitions.get(ref.rsplit("/", 1)[-1], {}))
            # Keep any sibling keys (description, default) that sat next to $ref.
            target.update({k: v for k, v in node.items() if k != "$ref"})
            return resolve(target)

        resolved = {key: resolve(value) for key, value in node.items()}
        if resolved.get("type") == "object" and "properties" in resolved:
            resolved["additionalProperties"] = False
            resolved["required"] = list(resolved["properties"])
        return resolved

    return resolve(root)


def _extract_json(text: str) -> str:
    """
    Pull a JSON document out of a model response.

    Models wrap JSON in prose or code fences often enough that failing on the
    first parse error would be the single largest source of failed jobs.
    """
    cleaned = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    if cleaned.startswith(("{", "[")):
        return cleaned

    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            return cleaned[start : end + 1]

    return cleaned


class OpenRouterLLM(LLMProvider):
    """OpenAI-compatible chat provider pointed at OpenRouter."""

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.openrouter_api_key
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.model_name = settings.openrouter_model
        self.timeout = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries
        self.max_output_tokens = settings.llm_max_output_tokens

        # One semaphore per event loop: the async limiter cannot be shared with
        # the sync path, and a loop-bound primitive must not outlive its loop.
        self._async_limits: Dict[int, asyncio.Semaphore] = {}
        self._sync_limit = threading.Semaphore(settings.llm_max_concurrency)
        self._max_concurrency = settings.llm_max_concurrency

        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these for attribution on its dashboard.
            "HTTP-Referer": "https://beeprepared.app",
            "X-Title": "BeePrepared",
        }
        logger.info("OpenRouter provider ready (model=%s)", self.model_name)

    # -- request construction ----------------------------------------------

    def _messages(self, prompt: str, context: Optional[str], schema: Optional[Type[BaseModel]]) -> List[Dict[str, str]]:
        system = (
            "You are a precise academic content engine. Follow the user's "
            "instructions exactly and never pad your answer with commentary."
        )
        if schema is not None:
            system += (
                " Respond with a single JSON document that validates against the "
                "provided schema. Emit no prose, no explanation and no code fences."
            )

        user = prompt
        if context:
            user = f"{prompt}\n\n--- SOURCE MATERIAL ---\n{context}"
        if schema is not None:
            # Repeated in the prompt as well as in `response_format`: providers
            # that silently ignore structured output still get the contract.
            user += (
                "\n\n--- REQUIRED JSON SCHEMA ---\n"
                f"{json.dumps(_strict_schema(schema), indent=2)}"
            )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _body(
        self,
        prompt: str,
        context: Optional[str],
        schema: Optional[Type[BaseModel]],
        model_name: Optional[str],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model_name or self.model_name,
            "messages": self._messages(prompt, context, schema),
            "temperature": 0.7 if schema is None else 0.4,
            "max_tokens": self.max_output_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": _strict_schema(schema),
                },
            }
        return body

    # -- response handling --------------------------------------------------

    @staticmethod
    def _content_of(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError(f"OpenRouter returned no choices: {json.dumps(payload)[:400]}")

        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some models return content as a list of typed parts.
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            raise LLMError("OpenRouter returned an empty completion")

        # Truncation produces JSON that fails to parse for a reason that has
        # nothing to do with the schema. Say so, rather than reporting a
        # confusing "unterminated string" three retries later.
        if choice.get("finish_reason") == "length":
            raise TruncatedResponse(
                f"The model hit its output limit ({len(content)} characters returned). "
                "Raise LLM_MAX_OUTPUT_TOKENS or ask for a smaller artifact."
            )
        return content

    def _parse(self, raw: str, schema: Optional[Type[BaseModel]]) -> Union[str, BaseModel]:
        if schema is None:
            return raw.strip()
        candidate = _extract_json(raw)
        try:
            return schema.model_validate_json(candidate)
        except Exception:
            pass
        try:
            return schema.model_validate(json.loads(candidate))
        except Exception as exc:
            preview = candidate[:400].replace("\n", " ")
            raise LLMError(f"Response did not match {schema.__name__}: {exc}. Got: {preview}") from exc

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff with jitter, so retries do not synchronise."""
        return min(2 ** attempt, 16) + random.uniform(0, 0.75)

    # -- LLMProvider --------------------------------------------------------

    def generate_content(
        self,
        prompt: str,
        context: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None,
    ) -> Union[str, BaseModel, Any]:
        body = self._body(prompt, context, schema, model_name)
        last_error: Optional[Exception] = None

        with self._sync_limit:
            with httpx.Client(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = client.post(
                            f"{self.base_url}/chat/completions", headers=self._headers, json=body
                        )
                        if response.status_code in RETRYABLE_STATUS:
                            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
                        if response.status_code >= 400:
                            raise LLMError(f"HTTP {response.status_code}: {response.text[:400]}")
                        return self._parse(self._content_of(response.json()), schema)
                    except Exception as exc:
                        last_error = exc
                        if attempt == self.max_retries - 1:
                            break
                        delay = self._backoff(attempt)
                        logger.warning(
                            "OpenRouter call failed (attempt %d/%d): %s. Retrying in %.1fs",
                            attempt + 1, self.max_retries, exc, delay,
                        )
                        time.sleep(delay)

        raise LLMError(f"OpenRouter generation failed after {self.max_retries} attempts: {last_error}")

    def _async_limiter(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        limiter = self._async_limits.get(loop_id)
        if limiter is None:
            limiter = asyncio.Semaphore(self._max_concurrency)
            self._async_limits[loop_id] = limiter
        return limiter

    async def generate_content_async(
        self,
        prompt: str,
        context: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None,
    ) -> Union[str, BaseModel, Any]:
        body = self._body(prompt, context, schema, model_name)
        last_error: Optional[Exception] = None

        async with self._async_limiter():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.post(
                            f"{self.base_url}/chat/completions", headers=self._headers, json=body
                        )
                        if response.status_code in RETRYABLE_STATUS:
                            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
                        if response.status_code >= 400:
                            raise LLMError(f"HTTP {response.status_code}: {response.text[:400]}")
                        return self._parse(self._content_of(response.json()), schema)
                    except Exception as exc:
                        last_error = exc
                        if attempt == self.max_retries - 1:
                            break
                        delay = self._backoff(attempt)
                        logger.warning(
                            "OpenRouter async call failed (attempt %d/%d): %s. Retrying in %.1fs",
                            attempt + 1, self.max_retries, exc, delay,
                        )
                        await asyncio.sleep(delay)

        raise LLMError(f"OpenRouter generation failed after {self.max_retries} attempts: {last_error}")
