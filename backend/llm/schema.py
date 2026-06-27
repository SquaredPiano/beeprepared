"""Conversion of Pydantic models into strict JSON Schema for structured output."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Type

from pydantic import BaseModel

_FENCED_JSON = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def strict_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Inline every `$ref` and close every object so strict mode can enforce the shape.

    Providers accept `$defs`/`$ref` but cannot police them, and a model given a
    reference-heavy schema stops treating field bounds as binding.
    """
    root = model.model_json_schema()
    definitions = root.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            target = copy.deepcopy(definitions.get(reference.rsplit("/", 1)[-1], {}))
            target.update({key: value for key, value in node.items() if key != "$ref"})
            return resolve(target)

        resolved = {key: resolve(value) for key, value in node.items()}
        if resolved.get("type") == "object" and "properties" in resolved:
            resolved["additionalProperties"] = False
            resolved["required"] = list(resolved["properties"])
        return resolved

    return resolve(root)


def extract_json(text: str) -> str:
    """Pull the JSON document out of a response that may be fenced or prefaced."""
    cleaned = text.strip()

    fenced = _FENCED_JSON.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    if cleaned.startswith(("{", "[")):
        return cleaned

    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            return cleaned[start : end + 1]

    return cleaned


def parse_as(text: str, model: Type[BaseModel]) -> BaseModel:
    """Validate a raw response against `model`, repairing common wrappers first."""
    candidate = extract_json(text)
    try:
        return model.model_validate_json(candidate)
    except Exception:
        return model.model_validate(json.loads(candidate))
