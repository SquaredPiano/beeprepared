# 05 — `backend/llm/`

## What this package is for

Everything in BeePrepared that needs a language model goes through this package and nothing else. The cleaning pass, the knowledge-core extraction, the eight artifact generators, the refine flow and the chat assistant all hold a `LLMProvider` and call two or three methods on it. None of them knows that OpenRouter exists, what the base URL is, how retries work, or what a JSON schema looks like on the wire.

There are six files and they fall into three groups.

`base.py` is the contract. It declares the abstract class `LLMProvider` with three methods and two class attributes, and it declares `LLMError`, the one exception type callers are expected to catch. Everything else in the codebase depends on this file and on nothing below it.

`openrouter.py` and `offline.py` are the two implementations. OpenRouter is the real one: it posts to OpenRouter's OpenAI-compatible chat-completions endpoint using `google/gemini-2.5-flash`, and it also does audio transcription through the same endpoint. Offline is a deterministic fake that derives plausible-shaped artifacts from the source text using word-frequency analysis. Offline exists so that a missing API key degrades the product instead of breaking it, and it is what the entire test suite runs against. That is what makes the Liskov substitution story in this project real rather than decorative: the tests do not mock out the handlers, they run the actual handlers unmodified against a different subclass.

`schema.py` and `factory.py` are support. `schema.py` converts a Pydantic model into a JSON Schema that a provider's strict structured-output mode can actually enforce, and parses the response back. `factory.py` picks which provider this process gets and caches it. `__init__.py` decides what the rest of the codebase is allowed to import.

Read them in that order. `schema.py` is the one with the most content per line, and it is the file you have said you will put on screen.

---

# `backend/llm/base.py`

Forty-three lines, and every consumer in the codebase is typed against it.

```python
"""The interface every language-model provider implements."""
```

`base.py:1`. Module docstring, states the job.

```python
from __future__ import annotations
```

`base.py:3`. This makes every annotation in the file a string that is not evaluated at import time. In this file it buys very little, because there are no forward references, but it is applied uniformly across the backend so that annotations never cost import time or create circular-import problems. The venv is Python 3.10, where `list[str]` and `X | None` in annotations still need this import to be safe in all positions.

```python
from abc import ABC, abstractmethod
from typing import Optional, Type, TypeVar

from pydantic import BaseModel
```

`base.py:5-8`. Boring imports. `ABC` and `abstractmethod` are what make an incomplete subclass fail at instantiation rather than at first call.

```python
Schema = TypeVar("Schema", bound=BaseModel)
```

`base.py:10`. This is the piece that makes the typed generation method useful. `Schema` is a type variable bound to `BaseModel`, so it can only ever stand for a Pydantic model class. It appears twice in `complete_as`: once as `schema: Type[Schema]` and once as the return type `-> Schema`. That pairing is what lets a caller write

```python
quiz = await provider.complete_as(prompt, QuizModel, context=core)
```

and have a type checker know that `quiz` is a `QuizModel`, not a `BaseModel`. Without the TypeVar the return type would be `BaseModel` and every caller would need a cast. This is the difference between an interface that documents itself and one that needs comments.

```python
class LLMError(RuntimeError):
    """The model could not produce a usable response."""
```

`base.py:13-14`. One exception type for the whole package. It inherits from `RuntimeError` rather than `Exception` directly, which is a small politeness: code that catches `RuntimeError` broadly still catches it. Everything the package raises is either this or a subclass of it (`PermanentFailure`, `TruncatedResponse` and `TransientFailure` in `openrouter.py`), so a caller can write one `except LLMError` and be complete.

```python
class LLMProvider(ABC):
    """
    Generates text or a validated Pydantic model from a prompt.

    Callers depend on this interface rather than on any particular vendor, so
    swapping providers never reaches beyond this package.
    """
```

`base.py:17-23`. The dependency-inversion statement, written as a docstring so it is visible at the point where it is enforced. The concrete claim is testable: Deepgram used to be a second provider for transcription, its key was revoked, and it was removed. That removal touched this package and nothing above it, because `pipeline/media.py` only ever knew about `LLMProvider.transcribe` and `LLMProvider.supports_audio`.

```python
    name: str = "unknown"
    supports_audio: bool = False
```

`base.py:25-26`. Two class attributes with defaults, deliberately not abstract properties.

`name` is used for logging (`factory.py:38`), for the health endpoint (`main.py:174`) and for the capabilities endpoint (`main.py:191`, where `provider.name == "offline"` tells the frontend to show a degraded-mode banner). Making it a plain class attribute rather than an abstract property means a subclass that forgets to set it gets `"unknown"` in a log line instead of a `TypeError` at construction. That is the right trade for a diagnostic field.

`supports_audio` is a capability flag, and it defaults to `False` — the conservative direction. A new provider that does not think about audio is correctly reported as not supporting it. `openrouter.py:70` sets it `True`, `offline.py:42` sets it `False`. `pipeline/media.py:57` exposes it as `available` and `media.py:68-72` refuses with a readable message rather than letting the call fail deep inside a provider.

```python
    @abstractmethod
    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        """Return free-form text."""
```

`base.py:28-30`. The first required method. Note two things.

It is `async`. This matters more than it looks — see the note at the end of the OpenRouter section. Concurrency in this project was effectively 1 for a while because the pipeline was calling a synchronous HTTP client from inside async handlers, which blocks the event loop for the entire model call. A ninety-second generation held the loop for ninety seconds, so raising the worker count changed nothing. The interface being `async` is what forces every implementation to be genuinely awaitable, and `openrouter.py` uses `httpx.AsyncClient` accordingly.

The `context` parameter is separate from `prompt` rather than being concatenated by the caller. That separation is what lets each provider decide how to present source material. OpenRouter joins them under a `--- SOURCE MATERIAL ---` header (`openrouter.py:166-170`); the offline provider parses the context as a knowledge core if it can (`offline.py:92-110`). If callers concatenated the strings themselves, neither of those would be possible.

```python
    @abstractmethod
    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        """Return a response validated against `schema`."""
```

`base.py:32-39`. The second required method, and the one that carries most of the product. Every structured artifact goes through here. The contract is stronger than "return JSON": it returns an instance of `schema`, already validated. A caller never sees a dict and never calls `model_validate` itself. If the model returns something that does not fit, that is an `LLMError` raised inside the provider, not a malformed object handed upward.

```python
    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words in an audio file."""
        raise LLMError(f"{self.name} cannot transcribe audio")
```

`base.py:41-43`. This is the interface-segregation point, and it is worth being precise about, because "I applied ISP" is exactly the kind of claim an interviewer will push on.

Note what is *not* here: no `@abstractmethod`. `transcribe` has a concrete default that raises. The consequence is that a provider which only does text is a complete, instantiable `LLMProvider` without writing a transcription method at all. The offline provider is exactly that — it defines `complete`, `complete_as`, and never mentions `transcribe`, so it inherits this line.

The reason this is interface segregation rather than laziness is the pairing with `supports_audio`. The flag is the question you ask; this method is what happens if you ask anyway. `pipeline/media.py:57` checks the flag and `media.py:68` raises a user-facing `MediaError` before ever reaching this line. This line is the backstop for a caller who skipped the check.

The honest counter-argument, and you should have it ready: a purist would say the correct segregation is two interfaces, `TextProvider` and `AudioProvider`, and that a default method which raises is a Liskov violation because a subclass narrows the contract. The answer is that the contract here is "`transcribe` works if and only if `supports_audio`", the flag is part of the same interface, and every caller honours it. It is a runtime-checked capability rather than a compile-time-checked one. That is a deliberate trade for a two-provider system where splitting the interface would double the type surface for one method.

**Worth knowing.** `f"{self.name} cannot transcribe audio"` reads `self.name`, so the message names the actual provider — "offline cannot transcribe audio". If a subclass forgets to set `name` the message says "unknown cannot transcribe audio", which is still more useful than a bare `NotImplementedError`.

---

# `backend/llm/schema.py`

Ninety-one lines. Four functions. This file exists because of a specific failure, and it is the one to be able to narrate cold.

## The failure this file fixes

Pydantic's `model_json_schema()` does not inline nested models. When `MindMapModel` contains a `MindMapRoot` which contains a list of `MindMapBranch` which contains a list of `MindMapLeaf`, Pydantic emits the three inner models once each into a top-level `$defs` block and refers to them by `$ref: "#/$defs/MindMapBranch"`. That is correct, standard JSON Schema, and it is what you want if a human or a validator is reading it.

It is not what you want on the wire to a model provider in strict structured-output mode. Providers accept a schema containing `$defs` and `$ref` — the request does not fail — but they cannot enforce it strictly. What happens instead is that the schema degrades from a hard constraint into a suggestion, and the field-level bounds stop being treated as binding. The observed failure mode was a mind map where the model started filling a single string field and simply kept going until it hit the output-token ceiling. It failed, it was retried, it failed the same way, three times. The character count burned across those attempts ran to six figures. `LLM_MAX_OUTPUT_TOKENS` is 16384 (`core/config.py:127`), which is roughly sixty thousand characters, so three attempts at the ceiling is where a number like a hundred thousand comes from.

The fix is this file. Inline every `$ref` so there are no references left, mark every object closed with `additionalProperties: false`, and mark every property required. The identical model tree then came back in about two seconds. Nothing about the Pydantic models changed; only the JSON Schema handed to the provider changed.

You can reproduce the before and after in one line each:

```python
MindMapModel.model_json_schema()          # top-level keys include "$defs"
strict_schema(MindMapModel)               # no "$defs", no "$ref" anywhere
```

## The code

```python
"""Conversion of Pydantic models into strict JSON Schema for structured output."""
```

`schema.py:1`. Docstring.

```python
import copy
import json
import re
from typing import Any, Dict, Type

from pydantic import BaseModel
```

`schema.py:5-10`. `copy` is here for exactly one line (`schema.py:33`) and that line is load-bearing; see below.

````python
_FENCED_JSON = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_OUTERMOST_FENCED_JSON = re.compile(r"```(?:json)?\s*(.+)\s*```", re.DOTALL)
````

`schema.py:12-13`. Two module-level compiled patterns for a Markdown code fence, used by `extract_json`. Compiled once at import rather than on every call. `(?:json)?` makes the language tag optional so it matches both a bare fence and a ```` ```json ```` fence. `re.DOTALL` makes `.` match newlines, which it must, because a JSON document spans lines.

The only difference between them is `(.+?)` against `(.+)`. The first is non-greedy and stops at the *first* closing fence; the second is greedy and runs to the *last*. Neither is right on its own: the non-greedy one returns a fragment when the document contains its own fence, and the greedy one swallows trailing prose when a response has a fence followed by commentary. `extract_json` tries both and keeps whichever parses.

Hold onto the non-greedy detail. It is correct for the job that pattern was written for, and it is exactly what destroyed valid responses when the pattern was allowed to run on text that was already JSON. That is the subject of the sharpest note in this document.

### `strict_schema`

```python
def strict_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Inline every `$ref` and close every object so strict mode can enforce the shape.

    Providers accept `$defs`/`$ref` but cannot police them, and a model given a
    reference-heavy schema stops treating field bounds as binding.
    """
```

`schema.py:15-21`. Signature and the docstring that records the reason. Takes a model *class*, not an instance.

```python
    root = model.model_json_schema()
    definitions = root.pop("$defs", {})
```

`schema.py:22-23`. Ask Pydantic for the standard schema, then remove the `$defs` block from it and keep it in a local variable.

Two things to say about `pop`. First, it mutates `root`, and that is safe because Pydantic v2 builds a fresh dictionary on each `model_json_schema()` call — you are not scribbling on a shared cached object. Second, popping rather than reading is what guarantees the returned schema has no `$defs` key left. If you had read it with `get` and left it in place, the output would contain a `$defs` block that nothing references — harmless but confusing, and it would go over the wire on every request.

The `{}` default means a flat model with no nested types works fine and `definitions` is just empty.

```python
    def resolve(node: Any) -> Any:
```

`schema.py:25`. A closure, defined inside `strict_schema` so it can read `definitions` from the enclosing scope without passing it down through every recursive call. That is the whole reason it is nested rather than a module-level helper.

The recursion is over the *shape of the JSON document*, not over the Pydantic model. A JSON Schema is a tree of dicts, lists and scalars, so `resolve` has three cases and they are the three JSON container kinds.

```python
        if isinstance(node, list):
            return [resolve(item) for item in node]
```

`schema.py:26-27`. Case one: a list. Recurse into every element and rebuild the list. Lists appear in a schema as the value of `anyOf`, `allOf`, `oneOf`, `enum`, and `required`. For `anyOf` the elements are subschemas that need resolving; for `enum` and `required` they are plain strings, and `resolve` on a string falls through to the next case and returns it unchanged. So one branch covers both without needing to know which key it came from.

```python
        if not isinstance(node, dict):
            return node
```

`schema.py:28-29`. Case two: anything that is not a list and not a dict — a string, an integer, a boolean, `None`. Nothing to do, hand it back. This is the recursion's base case, and it is what makes the whole function total: every leaf of the JSON tree terminates here.

```python
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
```

`schema.py:31-32`. Case three: a dict. First question, is this dict a reference?

Two guards, both deliberate. `isinstance(reference, str)` handles a dict where a *field is literally named* `$ref` — improbable, but the check costs nothing and the failure it prevents is silent. `startswith("#/$defs/")` restricts the inlining to local Pydantic-style references. A `$ref` pointing at an external URL, or at `#/definitions/` (the JSON Schema draft-7 spelling that Pydantic v1 used), is not touched — it falls through and is preserved as-is rather than being silently resolved to nothing.

```python
            target = copy.deepcopy(definitions.get(reference.rsplit("/", 1)[-1], {}))
```

`schema.py:33`. The resolution itself. Three things happen in one line.

`reference.rsplit("/", 1)[-1]` turns `"#/$defs/MindMapBranch"` into `"MindMapBranch"`. `rsplit` with a maxsplit of 1 splits from the right and only once, so it is the cheapest correct way to take the last path segment.

`definitions.get(name, {})` looks it up.

`copy.deepcopy` is the load-bearing part. The same definition gets referenced from several places — `MindMapLeaf` is referenced once from `MindMapBranch`, but in a wider model a shared sub-model can be referenced a dozen times. Every one of those sites gets its own inlined copy. Without the deep copy, all of them would be *the same dict object*, and the very next line mutates it with `target.update(...)`. One reference site carrying a `description` would write that description into the shared definition and it would appear at every other site too. A shallow `copy.copy` would fix the top level and leave the nested `properties` dict shared, so the mutation on `schema.py:39-40` — setting `additionalProperties` and `required` — would still leak. It has to be deep.

```python
            target.update({key: value for key, value in node.items() if key != "$ref"})
```

`schema.py:34`. Sibling keys. Pydantic will sometimes emit a reference with keys alongside it, most often a `description` or a `default` carried down from the `Field(...)` on the referring model. Those keys belong to the reference site, not to the definition, so they are merged in on top of the inlined copy and the referring site wins on any collision. `$ref` itself is filtered out, which is what stops this from being an infinite loop: the dict handed to `resolve` on the next line no longer has a `$ref` key, so it takes the normal object path.

```python
            return resolve(target)
```

`schema.py:35`. Recurse on the inlined result. This is what handles a definition that itself contains references — `MindMapRoot` refers to `MindMapBranch`, which refers to `MindMapLeaf`. Each level is resolved as it is inlined. The closure still sees the full `definitions` table, so depth does not matter.

**Worth knowing — the recursion has no cycle guard.** If a Pydantic model refers to itself, directly or through a cycle, `resolve` inlines the definition, finds the reference to itself inside it, inlines again, and never terminates. It raises `RecursionError`. This is verifiable in a few lines:

```python
class Node(BaseModel):
    label: str
    children: List["Node"] = []
strict_schema(Node)      # RecursionError
```

It never fires in this codebase, and not by accident. `models/artifacts.py:125-131` says so explicitly:

```python
class MindMapModel(BaseModel):
    """
    A concept map fixed at three levels.

    Depth is expressed with distinct types rather than a self-referencing node,
    because a recursive schema gives the model no bound to stop at.
    """
```

`MindMapLeaf`, `MindMapBranch` and `MindMapRoot` are three separate classes precisely so the tree has a fixed depth. That was a modelling decision made for the language model's benefit — an unbounded self-referencing node gives it no reason to stop nesting — and it happens to be the same decision that keeps `strict_schema` safe. If an interviewer asks "what happens with a recursive model", the answer is: it blows the stack, we know, and the reason it never happens is that the schema design forbids recursive models for an independent and better reason.

```python
        resolved = {key: resolve(value) for key, value in node.items()}
```

`schema.py:37`. Not a reference, so it is an ordinary dict. Rebuild it with every value resolved. Note this is a fresh dict rather than an in-place mutation, so `root` and the `definitions` entries are never modified beyond the `pop` on line 23.

This also walks into the `properties` dict, which is a dict keyed by *field names* rather than by schema keywords. That is fine — `resolve` does not care what the keys mean, only what the values are shaped like.

```python
        if resolved.get("type") == "object" and "properties" in resolved:
            resolved["additionalProperties"] = False
            resolved["required"] = list(resolved["properties"])
        return resolved
```

`schema.py:38-41`. The strictness itself, applied on the way back up the recursion.

The condition needs both halves. `type == "object"` alone is not enough, because a `Dict[str, Any]` field produces an object schema with no `properties` at all — closing that would say "this object may have no keys", which is the opposite of what is meant. Requiring `properties` to be present restricts the treatment to objects that are actual models with a known field list. And `"properties" in resolved` alone is not enough either, because the `properties` dict of a model that happens to contain a field named `type` would look superficially similar; the value there is a dict rather than the string `"object"`, so the first half of the condition rules it out.

`additionalProperties = False` says: this object has exactly these keys and no others. Strict mode on the provider side generally *requires* this to be present and false before it will enforce anything at all — an open object is not a shape it can constrain.

`required = list(resolved["properties"])` is the fully-required part, and it is the line most likely to be questioned. It discards whatever Pydantic put in `required` and replaces it with every property name.

What that means for optional fields is the interesting bit, and it works because of how Pydantic renders them. `MindMapLeaf.detail` is `Optional[str] = Field(None, ...)`, and Pydantic emits it as:

```json
"detail": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}
```

The optionality is expressed in the *type* — the value may be a string or it may be null. It is not expressed by being absent from `required`. So forcing it into `required` does not make the field mandatory in any way Pydantic will reject; it makes the *key* mandatory while leaving `null` a legal value. The model must write `"detail": null` instead of omitting the key. Pydantic validates that identically to an omitted key, because `null` is exactly what the default is.

Comparing the two schemas for `MindMapLeaf` makes it concrete. Pydantic emits `"required": ["label"]`; `strict_schema` emits `"required": ["label", "detail"]`, and `detail` still has its nullable `anyOf`. Same accepted set of documents, expressed in the form strict mode can police.

The reason to do this at all rather than preserving Pydantic's `required` list is that partial requirement lists are the other thing that makes providers give up on strict enforcement. "Every key present, some of them nullable" is a shape a provider can check mechanically. "These four required, these three optional" is not.

The one real consequence is for a field with a non-null default, like `NotesModel.format: str = "markdown"`. Making it required means the model has to emit `"format": "markdown"` rather than letting Pydantic fill it in. That costs a few tokens and no correctness.

```python
    return resolve(root)
```

`schema.py:43`. Kick off the recursion at the top of the tree.

### `_is_json_document`

```python
def _is_json_document(text: str) -> bool:
    """Whether `text` already parses in full and so needs no repair."""
    try:
        json.loads(text)
    except ValueError:
        return False
    return True
```

`schema.py:47-53`. A predicate with exactly one job: answer whether the text needs repairing at all. It exists because of the bug described below, and its shape is the interesting part.

The question is answered by *parsing*, not by looking at the text. A cheaper version — does this start with a brace — would be a guess about the shape of the document. `json.loads` is the same judgement `parse_as` is about to make, made early and made properly. If it comes back `True`, the text is by definition already the thing the caller wants, and every line below can only damage it.

`except ValueError` rather than `except json.JSONDecodeError` is deliberate and covers strictly more: `JSONDecodeError` is a subclass of `ValueError`, and `json.loads` raises a plain `ValueError` for some inputs before it gets as far as building a decode error. The parsed result is thrown away — only success or failure matters — which costs one extra parse of a document that is about to be parsed again anyway. Against a model call that took thirty seconds, that is free.

### `extract_json`

```python
def extract_json(text: str) -> str:
    """
    Pull the JSON document out of a response that may be fenced or prefaced.

    An intact document is returned untouched before any repair is attempted,
    because the fence pattern happily matches a fence that lives *inside* a
    string value and would hand back its contents instead of the document. Any
    model whose schema carries a Markdown field, such as a study guide body,
    can legitimately emit one.
    """
    cleaned = text.strip()
```

`schema.py:56-71`. This is the repair layer. Even with strict structured output and a system prompt that says "no code fences" (`openrouter.py:29-32`), models sometimes wrap the document in a fence or preface it with a sentence. Rather than failing the whole generation for a cosmetic wrapper, this pulls the document out.

The docstring is long for a short function, and that is on purpose. It records the failure that the first branch prevents, so that nobody reorders the branches back into the state that caused it.

```python
    if _is_json_document(cleaned):
        return cleaned
```

`schema.py:74-75`. The first branch, and the one that used to be missing. If the text already parses, hand it back and run none of the repairs. Everything below this line exists for text that is *not* a JSON document, which is the only text a repair can help.

```python
    for pattern in (_FENCED_JSON, _OUTERMOST_FENCED_JSON):
        fenced = pattern.search(cleaned)
        if fenced and _is_json_document(fenced.group(1).strip()):
            return fenced.group(1).strip()
```

`schema.py:77-80`. First repair, and it closes the case the guard above cannot reach. The text genuinely is fenced here, so `_is_json_document` has already failed on the leading backticks and cannot help.

Two patterns are tried in order. `_FENCED_JSON` is non-greedy and stops at the *first* closing fence, which is right for the ordinary case. `_OUTERMOST_FENCED_JSON` is the same pattern with `(.+)` instead of `(.+?)`, so it runs to the *last* closing fence. A fenced document whose body contains its own fence needs the second one, because the first stops early and returns a fragment.

Rather than reason about which pattern is correct for a given response, the code asks each candidate the same question the guard asks: does this parse as a whole document? Whichever does, wins. That is the useful shape here — the two patterns disagree only when one of them is wrong, and parsing is a cheap and exact way to find out which.

```python
    fenced = _FENCED_JSON.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
```

`schema.py:82-84`. The fallback, unchanged. If neither pattern produced something that parses, take what is inside the first fence and let the brace-slice repairs below have a go at it. A response that is fenced *and* truncated mid-document lands here.

```python
    if cleaned.startswith(("{", "[")):
        return cleaned
```

`schema.py:86-87`. If what we now have opens with a brace or a bracket, it is plausibly a JSON document, so return it. `startswith` accepts a tuple, which is the idiomatic way to test several prefixes in one call.

Note that this check survives the fix and is not made redundant by it. It catches text that opens like JSON but does not parse — a document that was truncated mid-string, or one with a trailing comma — and hands it to `parse_as` so that the error the caller sees is about the actual document rather than about a slice of it.

```python
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            return cleaned[start : end + 1]
```

`schema.py:89-92`. Second repair, for a response with prose around it: `Here you go: {...} Hope that helps`. Find the first opening brace and the *last* closing brace — `find` from the left, `rfind` from the right — and take everything between them inclusive. Objects are tried before arrays because objects are what nearly every schema in this project produces at the top level. `end > start` rather than `end != -1` guards the case where the closer appears before the opener, which would produce a negative-length slice.

```python
    return cleaned
```

`schema.py:94`. Nothing recognisable. Return what we have and let `parse_as` produce the error, so the failure message contains the actual text rather than a message from here.

**Worth knowing — this was the subtlest bug in the package, and the two lines at 67-68 are the whole of the fix.**

The fence search used to run *first*, before anything asked whether the text was already JSON. So a response that was a perfectly clean, unfenced JSON document had the fence regex applied to it anyway. If any string value inside that document contained a Markdown code fence, the regex matched the fence *inside the JSON string* — the non-greedy `(.+?)` stopping at the first closing fence, which was the one in the string — `group(1)` returned the contents of that inner fence, and the real document was thrown away.

This was not hypothetical. Reproduced against the real function:

````python
body = "Run it:\n\n```python\nprint(quorum)\n```\n\nThen read the output."
payload = json.dumps({"title": "Quorums", "estimated_minutes": 30,
                      "objectives": ["..."], "body": body, "checklist": ["..."]})
extract_json(payload)      # -> 'python\\nprint(quorum)\\n'
parse_as(payload, StudyGuideModel)
# -> JSONDecodeError
````

Read what came back. The whole study guide was replaced by the contents of the fence that
lived inside its `body` field — and by the *escaped* contents at that, because inside a
JSON string the newlines are the two characters `\n` rather than real line breaks. Not a
document, not a fragment of one: a fenced code sample, lifted out of a string value.

The response was valid. It was destroyed on the way in.

Three things bounded how badly this bit, and you should know all three because they are what an interviewer will ask next.

It only affected the OpenRouter path. The offline provider never touches `extract_json` — `offline.py:74` calls `schema.model_validate(builder(...))` on a dict it built itself. That is precisely why the test suite could not catch it: every test runs against the offline provider, and the offline provider never reaches this function.

It only affected schemas with a free-text field where the model might reasonably write a code fence. `NotesModel` has a Markdown `body`, but notes are not generated through `complete_as` at all — `generators.py:237` calls `complete()` and wraps the result with `_as_notes`, so notes never go through this function. The live exposure was `StudyGuideModel`, which *is* a `complete_as` schema (`generators.py:146`) and whose `body` field is documented as `"Markdown, ordered by dependency"` (`artifacts.py:92`). A study guide generated from a programming lecture is the case that broke.

And it failed loudly rather than silently. `parse_as` raises, `complete_as` at `openrouter.py:107-109` turns that into an `LLMError` with a 300-character preview of the raw response, so the log shows what came back. It was a failed generation, not a corrupted one — which is the important distinction against the offline locale bug further down, where the failure was silent.

The fix is the `_is_json_document` guard on lines 74-75: an intact document is returned before any repair runs. Note what the fix did *not* touch. The fence pattern is unchanged, the fence branch is unchanged, and the brace-slice fallback is unchanged, because all three are still correct for the text they now see — text that failed to parse. The only thing that changed is that they are no longer shown text that never needed them.

Two tests hold it down, at `tests/test_pipeline.py:143` and `:152`. The first sends a study guide whose `body` contains a ```` ```python ```` block through `parse_as` and asserts the body comes back byte-identical. The second sends a genuinely fenced response and asserts it is still unwrapped, which is the regression that a careless fix would cause: if you had guarded with "return early whenever there is no fence" you would have broken the case the function was written for.

**The second half of the same bug, and it is worth telling as one story.** The guard above fires only on an intact *unfenced* document. When the first fix landed, a response that was both wrapped in a fence *and* carried a fence inside one of its string values was still shredded, because `_is_json_document` fails on the leading backticks and control fell through to the fence pattern, which still stopped at the inner fence:

````python
extract_json("```json\n" + payload + "\n```")
# -> '{"title": "Quorums", ... "body": "Run it:\\n\\n'      truncated at the inner fence
````

That is the same defect as the original, reached by a different route — the guard fixed the unfenced case and left the fenced one, in exactly the way the fifth security hole was a fix that covered one door out of three. It is now closed by trying the greedy pattern as well and keeping whichever candidate parses as a whole document, which is the fix described above at `schema.py:77-80`.

The reason it is worth volunteering is not the bug, which is small. It is that the first fix looked complete and was not, and the way to find that out was to ask what *else* reaches this code — the same question that turned four security holes into five.

### `parse_as`

```python
def parse_as(text: str, model: Type[BaseModel]) -> BaseModel:
    """Validate a raw response against `model`, repairing common wrappers first."""
    candidate = extract_json(text)
    try:
        return model.model_validate_json(candidate)
    except Exception:
        return model.model_validate(json.loads(candidate))
```

`schema.py:97-103`. Repair, then validate, with a second attempt.

The first attempt is `model_validate_json`, which parses and validates in one pass inside Pydantic's Rust core. It is the fast path and it is what succeeds nearly always.

The fallback parses with the standard library's `json.loads` first and then validates the resulting Python object. The reason this is worth having is that the two parsers are not identical: `json.loads` accepts a few things Pydantic's stricter JSON parser rejects, notably the non-standard literals `NaN`, `Infinity` and `-Infinity`, which a model will occasionally emit inside a numeric field. Going through `json.loads` turns those into Python floats and Pydantic then validates the object form.

If the fallback also fails, its exception propagates — a `json.JSONDecodeError` or a `ValidationError` — and `openrouter.py:107-109` catches it and rewraps it with the response preview.

**Worth knowing.** The return annotation is `BaseModel`, not the `Schema` TypeVar from `base.py:10`. `complete_as` declares `-> Schema` and returns this call's result directly (`openrouter.py:106`), so a strict type checker would flag the narrowing. It is a typing gap, not a runtime one — the object really is an instance of `model`. Worth being the one to point it out rather than being told.

**Worth knowing.** The bare `except Exception` on line 90 swallows the first failure entirely. If the second attempt also fails, the error you see is the one from the *second* path, and Python's implicit exception chaining will attach the first as `__context__`, so the traceback shows both. That is acceptable, but the message that reaches the user is the second one, which is `json.loads`' complaint rather than Pydantic's — usually less informative about which field was wrong.

---

# `backend/llm/openrouter.py`

266 lines. The only live provider.

```python
"""OpenRouter provider: one key, any hosted model, plus audio transcription."""
```

`openrouter.py:1`. The one-key point is the actual architectural reason OpenRouter is here. It is an OpenAI-compatible gateway in front of many vendors, so `google/gemini-2.5-flash` is a configuration string rather than a client library, and swapping to a Claude or Llama model is an environment-variable change with no code change. It also does audio, which is what made removing Deepgram possible when its key was revoked — transcription moved from a second SDK and a second key to the same endpoint and the same key.

```python
import asyncio
import base64
import json
import logging
import random
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import httpx
```

`openrouter.py:5-14`. `random` is for jitter in the backoff, `weakref` is for the semaphore table, `base64` is for the audio payload. `httpx` rather than `requests` because the interface is async and a synchronous client would block the loop.

```python
from backend.core.config import get_settings
from backend.llm.base import LLMError, LLMProvider, Schema
from backend.llm.schema import parse_as, strict_schema
```

`openrouter.py:16-18`. Note the direction: this file imports from `base`, never the reverse. Nothing outside `backend/llm/` is imported except configuration.

```python
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
```

`openrouter.py:22`. The HTTP statuses worth trying again. 408 request timeout, 409 conflict, 425 too early, 429 rate limited, and the 5xx family. A `frozenset` rather than a set or a tuple: constant-time membership, and immutable so it cannot be modified by accident at runtime.

Everything else at 400 or above is permanent — 401 (bad key), 403, 404, 422 (malformed request). Retrying those spends the timeout budget three times to receive the same rejection.

This set is duplicated as a regex alternation in `services/job_runner.py:54`. That duplication is deliberate and it is worth understanding: this file decides whether to retry a single HTTP request, and `job_runner` decides whether to requeue an entire job. They are different decisions at different layers, and the second one only ever sees an error *message*, never an exception type.

```python
SYSTEM_PROMPT = (
    "You are a precise academic content engine. Follow the user's instructions "
    "exactly and never pad your answer with commentary."
)
```

`openrouter.py:24-27`. The system message for every request. "Never pad your answer with commentary" is the instruction that stops responses arriving as "Sure! Here's your quiz: ...". `extract_json` exists because that instruction is not perfectly reliable.

```python
SCHEMA_PROMPT = (
    " Respond with a single JSON document that validates against the provided "
    "schema. Emit no prose, no explanation and no code fences."
)
```

`openrouter.py:29-32`. Appended to the system prompt for structured requests only (`openrouter.py:129`). Note the leading space — it is concatenated directly onto `SYSTEM_PROMPT`, so the space is what keeps the sentences apart. That is easy to delete by accident.

This is belt and braces. The request already carries a `response_format` with `strict: True`, which should make prose impossible. The prompt says it again in words because strict mode's coverage varies by underlying model and OpenRouter routes across many.

```python
TRANSCRIBE_PROMPT = (
    "Transcribe this recording verbatim. Output only the transcript: no speaker "
    "labels, no timestamps, no commentary."
)
```

`openrouter.py:34-37`. The word "verbatim" here is not incidental — it is the first entry in `PASS_THROUGH_MARKERS` at `offline.py:25`. See the locale bug below.

The three exclusions match what `pipeline/cleaning.py` would otherwise have to strip: `TRANSCRIPT_NOISE` at `cleaning.py:27-32` removes timestamps, speaker labels and bracketed asides with regexes, and those rules are now allowed to run on transcribed speech and nothing else. Asking the model not to produce them is cheaper and more reliable than removing them afterwards.

```python
class PermanentFailure(LLMError):
    """The request would fail identically however many times it is repeated."""


class TruncatedResponse(PermanentFailure):
    """The model ran out of output budget mid-document."""
```

`openrouter.py:40-45`. The first two of the three exception types this file declares, and the hierarchy is the whole point.

Both inherit from `LLMError`, so a caller's `except LLMError` still catches them and nothing outside this package needs to learn new types. Inside this file, the distinction drives the retry loop: `_send` catches `PermanentFailure` and re-raises immediately (`openrouter.py:188-189`) while treating everything else as worth another attempt.

`TruncatedResponse` inheriting from `PermanentFailure` rather than from `LLMError` directly is the classification decision. Truncation is not a transient fault. The model did not fail — it produced output until it ran out of budget. Given the same prompt and the same ceiling it will do exactly the same thing again, and each repeat costs a full output budget. Making it a subclass of `PermanentFailure` means the existing `except PermanentFailure: raise` handles it with no extra branch. That is the class hierarchy doing the work rather than an `if`.

```python
class TransientFailure(LLMError, ConnectionError):
    """
    Every attempt failed on a fault a later attempt could still survive.

    Only retryable faults reach this class: `PermanentFailure` leaves the send
    loop untouched, so anything that exhausts the retries is by construction a
    failure to complete the exchange with OpenRouter at all.
    ...
    """
```

`openrouter.py:48-63`. The third type, and the one with the most reasoning behind it. This is bug number five and it is worth narrating in full, because it is a case where the retry machinery appeared to work and was in fact working by accident.

**What was wrong.** `_send`'s final line used to raise a plain `LLMError`. Every failure that exhausted the retries — a connect timeout, a refused connection, an HTTP 503, an empty completion — came out of this provider as the same flat type with the original exception discarded. One layer up, `services/job_runner.py` decides whether to requeue an entire job, and `is_transient` asks two questions in order: is this exception one of `TRANSIENT_EXCEPTIONS` (`job_runner.py:34-42`, which includes `httpx.TimeoutException`, `httpx.ConnectError` and `ConnectionError`), and if not, does its message look transient. The first question could never be answered yes for anything from this provider, because the type had been thrown away. So the classifier fell through to string matching on a message that had also lost most of its information.

**Why that was worse than it sounds.** `str(httpx.ConnectTimeout(""))` is the empty string. httpx raises several of its transport errors with no message at all. So the wrapped message read `"OpenRouter failed after 3 attempts: "` — a colon with nothing after it — and there was nothing in it to match. Measured on the three cases that matter:

```
wrapped ConnectTimeout("")                      -> PERMANENT   (empty message)
wrapped ConnectError("[Errno 61] Connection refused") -> PERMANENT   (no phrase matches)
wrapped LLMError("HTTP 429: rate limited")      -> transient  (the status is in the text)
```

A connect timeout and a refused connection are the two most common real failures a hosted model call has, and neither was ever retried at the job level. The only reason the machinery looked like it worked is that the HTTP status errors happen to embed their code in the message text, and the status regex found it there.

**The fix, and the reasoning worth explaining.** `TransientFailure` inherits from `LLMError` *and* from `ConnectionError`. `ConnectionError` is already in `TRANSIENT_EXCEPTIONS`, so `isinstance(error, TRANSIENT_EXCEPTIONS)` at `job_runner.py:68` now fires on the type and never has to look at the message at all. `LLMError` is kept first so nothing outside this package has to learn a new type and every existing `except LLMError` still catches it.

The claim that everything reaching this class is genuinely transient is not a hope — it is guaranteed by the shape of the loop. `PermanentFailure` is re-raised out of the loop untouched at `openrouter.py:188-189` and never reaches the final line. So the only failures that can exhaust the retries are ones the loop already judged retryable, three times, with backoff between them. Calling them transient at the boundary is restating a decision that was already made rather than making a new one. That is the sentence to say out loud: *only retryable faults can reach the wrap at all, so everything that exhausts the retries is transient by construction.*

Three tests pin it, at `tests/test_pipeline.py:160-190`. Two of them drive `_send` against a transport that always raises `httpx.ConnectTimeout("")`, `httpx.ReadTimeout("")` or `httpx.ConnectError("[Errno 61] Connection refused")` and assert the result classifies transient. The third is the one that matters more: it feeds a malformed response through `complete_as` and asserts the resulting error is *not* transient, so that rescuing network faults did not quietly make every provider failure retryable.

```python
class OpenRouterProvider(LLMProvider):
    """Talks to OpenRouter's OpenAI-compatible endpoint."""

    name = "openrouter"
    supports_audio = True
```

`openrouter.py:66-70`. Subclass, and the two class attributes from `base.py:25-26` overridden.

```python
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY is not set")
```

`openrouter.py:72-75`. Fail at construction, not at first request. This is what makes the fallback in `factory.py:24-28` work: the factory tries to build an OpenRouter provider inside a `try`, and a missing key surfaces there, in one place at startup, rather than as a mysterious failure inside a background job an hour later.

```python
        self._url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
```

`openrouter.py:77`. The `rstrip('/')` is small and worth noticing. The default base URL is `https://openrouter.ai/api/v1` with no trailing slash (`config.py:125`), but a user setting `OPENROUTER_BASE_URL` in a `.env` file will very often add one, and `https://.../v1//chat/completions` is a 404 that costs an evening to find.

```python
        self._model = settings.openrouter_model
        self._timeout = settings.llm_timeout_seconds
        self._max_retries = settings.llm_max_retries
        self._max_output_tokens = settings.llm_max_output_tokens
        self._concurrency = settings.llm_max_concurrency
```

`openrouter.py:78-82`. Snapshot the settings onto the instance. Defaults are in `config.py:123-129`: model `google/gemini-2.5-flash`, timeout 180 seconds, 3 retries, 16384 output tokens, concurrency 6.

The 180-second timeout is long by HTTP standards and correct here — a full knowledge-core extraction over a long chunk genuinely takes over a minute, and a shorter timeout would abandon work that was about to succeed.

Reading settings once at construction rather than per request means the provider is a consistent object for its lifetime. The consequence is that changing an environment variable requires `reset_provider()` (`factory.py:42-46`), which is exactly what `tests/conftest.py:72` calls between tests.

```python
        self._limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
            weakref.WeakKeyDictionary()
        )
```

`openrouter.py:83-85`. The semaphore table. The annotation is a string because `WeakKeyDictionary` is not subscriptable at runtime on Python 3.10, and `from __future__ import annotations` does not cover an annotated assignment's evaluation in every position — quoting it is the safe form.

The full explanation is in the `_limiter` docstring; the important thing here is that the key type is `asyncio.AbstractEventLoop` — the loop object itself.

```python
        self._headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://beeprepared.app",
            "X-Title": "BeePrepared",
        }
```

`openrouter.py:86-91`. Built once and reused. `HTTP-Referer` and `X-Title` are OpenRouter-specific attribution headers that identify the app on their dashboard; they are optional and cost nothing. Note the header is spelled `HTTP-Referer` with the historical single-r misspelling, which is what the HTTP standard actually uses.

```python
        logger.info("OpenRouter ready (model=%s)", self._model)
```

`openrouter.py:93`. Startup confirmation, with the model name so a misconfigured model is visible in the first lines of the log. Uses `%s` lazy formatting rather than an f-string, which is the right habit for logging even at info level.

```python
    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        return await self._send(self._text_request(prompt, context))
```

`openrouter.py:95-96`. The first interface method, one line. The pattern for all three is the same: a `_*_request` method builds a body, `_send` posts it. That separation is what lets the retry, concurrency and error-handling logic live in exactly one place regardless of request type.

```python
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
```

`openrouter.py:98-109`. Send, then parse.

The `_send` call is deliberately *outside* the `try`. That matters. If `_send` raises `TruncatedResponse`, it propagates unchanged and stays classified as a permanent failure. If it were inside the `try`, the `except Exception` would catch it and rewrap it as a plain `LLMError`, and the truncation classification would be lost on its way out of the method. One line of placement carrying the whole distinction.

`preview = raw[:300].replace("\n", " ")` collapses newlines so the failure lands as a single log line rather than a wall. Three hundred characters is enough to see whether the model returned prose, a fence, a truncated document or something else entirely — which is usually all you need to know what went wrong.

`raise ... from error` sets `__cause__` explicitly, so the traceback reads "the above exception was the direct cause of" rather than "during handling of". Small, correct.

```python
    async def transcribe(self, audio_path: str) -> str:
        """Return the spoken words in an audio file."""
        return await self._send(await asyncio.to_thread(self._audio_request, audio_path))
```

`openrouter.py:111-113`. Overrides the raising default from `base.py:41-43`.

The `asyncio.to_thread` is the piece to explain. `_audio_request` reads the whole file off disk and base64-encodes it (`openrouter.py:141`). For a lecture-length recording that is tens of megabytes of blocking file I/O plus CPU-bound encoding. Doing that inline on the event loop would freeze every other coroutine in the process for the duration — the API's request handlers included, because in local dispatch mode the worker pool shares the loop with FastAPI. `to_thread` moves it to the default thread pool executor and the loop stays responsive.

The same reasoning appears in `pipeline/media.py:59-63`, where `ffmpeg` conversion is wrapped the same way with a docstring that says why.

```python
    def _text_request(self, prompt: str, context: Optional[str]) -> Dict[str, Any]:
        return self._request(SYSTEM_PROMPT, self._user_text(prompt, context), temperature=0.7)
```

`openrouter.py:115-116`. Temperature 0.7 for free text. Notes and prose want some variation; a study guide written at temperature 0 reads mechanically.

```python
    def _schema_request(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str],
    ) -> Dict[str, Any]:
        contract = strict_schema(schema)
```

`openrouter.py:118-124`. Build the strict schema once and reuse it twice.

```python
        content = (
            f"{self._user_text(prompt, context)}\n\n"
            f"--- REQUIRED JSON SCHEMA ---\n{json.dumps(contract, indent=2)}"
        )
```

`openrouter.py:125-128`. The schema goes into the user message *as text*, in addition to going into `response_format` below. That looks redundant and is not. The `response_format` field constrains the decoder; the text in the prompt is what the model reads while planning its answer, and it is where the `description` strings from `Field(...)` do their work — "At most six words", "One sentence under 140 characters", "Zero-based index into options". A constraint the decoder enforces produces valid JSON; a constraint the model has read produces *good* JSON.

`indent=2` costs tokens and buys legibility for the model. Fine at this scale.

```python
        body = self._request(SYSTEM_PROMPT + SCHEMA_PROMPT, content, temperature=0.4)
```

`openrouter.py:129`. Temperature 0.4, lower than the 0.7 for free text. Structured output wants consistency more than variety, but not zero — quiz distractors generated at temperature 0 come out repetitive.

```python
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": True, "schema": contract},
        }
        return body
```

`openrouter.py:130-134`. The structured-output declaration, in OpenAI's format because OpenRouter is OpenAI-compatible. `strict: True` is what asks the provider to enforce rather than suggest — and it is exactly this flag that cannot be honoured when the schema contains `$defs`/`$ref`, which is the entire reason `strict_schema` exists. `name` is taken from the Python class name, so the schema is self-identifying in any provider-side logging.

```python
    def _audio_request(self, audio_path: str) -> Dict[str, Any]:
        path = Path(audio_path)
        if not path.exists():
            raise LLMError(f"Audio file not found: {audio_path}")
```

`openrouter.py:136-139`. Check before reading, so a missing file gives a clear message rather than a `FileNotFoundError` from inside an encoder.

```python
        encoded = base64.b64encode(path.read_bytes()).decode()
        audio_format = path.suffix.lstrip(".").lower() or "wav"
```

`openrouter.py:141-142`. Read, encode, and derive the format from the extension. `lstrip(".")` turns `.wav` into `wav`, `.lower()` normalises `.WAV`, and `or "wav"` covers a file with no extension. In practice this is always `wav`, because `pipeline/media.py:73-75` converts everything through ffmpeg to a single normalised wav first — that is what the media pipeline's docstring means by "the model always receives the same encoding, whatever the user uploaded". The fallback here is for a caller who bypasses that.

```python
        body = self._request(
            "You are a transcription engine. Return only the spoken words.",
            TRANSCRIBE_PROMPT,
            temperature=0.0,
        )
```

`openrouter.py:144-148`. Temperature 0.0. Transcription is the one call where creativity is purely harmful — you want the most likely token every time, because a "creative" transcript is a wrong transcript.

The system prompt here is a literal string rather than `SYSTEM_PROMPT`, because "precise academic content engine" is the wrong framing for a transcription job.

```python
        body["messages"][-1]["content"] = [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "input_audio", "input_audio": {"data": encoded, "format": audio_format}},
        ]
        return body
```

`openrouter.py:149-153`. Replace the user message's content with a multi-part array. `_request` built it as a plain string; multimodal messages need a list of typed parts. Indexing with `[-1]` reaches the last message, which `_request` guarantees is the user message.

Building the body through `_request` and then patching one field is slightly awkward, but it means the model name, the timeout-relevant `max_tokens` and the message skeleton all come from one place. If a fourth request type is added, the skeleton stays in one place.

```python
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
```

`openrouter.py:155-164`. The common request skeleton. `temperature` is keyword-only — the `*` in the signature — so no call site can pass it positionally and accidentally swap it with something else. Three call sites all pass a different value, which is why it is a parameter at all.

`max_tokens` is the output ceiling that `TruncatedResponse` reports on. 16384 by default.

```python
    @staticmethod
    def _user_text(prompt: str, context: Optional[str]) -> str:
        if not context:
            return prompt
        return f"{prompt}\n\n--- SOURCE MATERIAL ---\n{context}"
```

`openrouter.py:166-170`. Join the instruction and the material with an explicit delimiter, so the model can tell which part is the instruction and which is the data. Without the header, a lecture transcript that itself contains imperative sentences blurs into the instruction. `if not context` rather than `if context is None` also treats an empty string as absent, which is what you want.

`@staticmethod` because it uses no instance state.

### `_send`

```python
    async def _send(self, body: Dict[str, Any]) -> str:
        """
        Post one request, retrying only what a retry could fix.

        A rejected key, a malformed request and a truncated document all fail
        the same way on every attempt, so they surface immediately instead of
        spending the whole output budget twice more to say so again.
        """
```

`openrouter.py:172-179`. The retry loop and the concurrency limit, in one method for all three request types.

```python
        last_error: Optional[Exception] = None
```

`openrouter.py:180`. Held so the final message can name the actual cause rather than saying "all attempts failed".

```python
        async with self._limiter():
```

`openrouter.py:182`. Acquire the concurrency semaphore for this event loop. Six in flight at once by default. The limit exists because the pipeline fans out aggressively — `cleaning.py:149` gathers one call per 4,000-character chunk and `knowledge.py:115` does the same for extraction, so a long lecture can produce dozens of simultaneous calls. Without a ceiling they all leave at once and the provider returns 429s, which then get retried, which produces more 429s.

```python
            async with httpx.AsyncClient(timeout=self._timeout) as client:
```

`openrouter.py:183`. A client per call, created inside the semaphore, closed by the context manager on the way out. So at most `_concurrency` clients exist at any moment and none leak.

**Worth knowing.** Because the client is per-call rather than per-provider, there is no connection reuse between requests — each call pays a fresh TCP and TLS handshake. Against a call that takes tens of seconds that overhead is negligible, and the benefit is that there is no long-lived client to bind to a dead event loop, which is the same class of problem the semaphore keying below solves. It is a defensible trade, but be ready to say it was a trade.

```python
                for attempt in range(self._max_retries):
                    try:
                        response = await client.post(self._url, headers=self._headers, json=body)
                        return self._content_of(self._checked(response))
```

`openrouter.py:184-187`. Post, check the status, extract the content, return. `_checked` raises on a bad status; `_content_of` raises on empty or truncated content. Both raise from inside the `try`, so both are subject to the classification below.

```python
                    except PermanentFailure:
                        raise
```

`openrouter.py:188-189`. The classification, and the ordering is what makes it work. `PermanentFailure` is a subclass of `LLMError` which is a subclass of `RuntimeError` which is a subclass of `Exception`, so the broad handler on the next line would catch it too. Python takes the first matching `except` clause in source order, so this one has to come first. Reverse these two blocks and every permanent failure — bad key, malformed request, truncated document — gets retried three times.

`raise` with no argument re-raises the current exception with its original traceback intact.

```python
                    except Exception as error:
                        last_error = error
                        if attempt == self._max_retries - 1:
                            break
```

`openrouter.py:190-193`. Everything else is a candidate for retry. `except Exception` and not `except BaseException`, which is correct here and is the opposite of the choice made in `cleaning.py:155`. The difference is that this is a `try/except` around code we are executing, where catching `asyncio.CancelledError` would defeat cancellation and keep a torn-down job running; whereas `cleaning.py` is inspecting *results* from `gather(return_exceptions=True)`, where a `CancelledError` arrives as a value and `Exception` would fail to recognise it as a failure at all.

The `break` on the last attempt exits without sleeping. Without it you would wait sixteen seconds after the final failure for no reason.

```python
                        delay = self._backoff(attempt)
                        logger.warning(
                            "OpenRouter attempt %d/%d failed (%s); retrying in %.1fs",
                            attempt + 1, self._max_retries, self._describe(error), delay,
                        )
                        await asyncio.sleep(delay)
```

`openrouter.py:194-199`. Log and wait. `attempt + 1` so the log reads 1/3 rather than 0/3. `await asyncio.sleep` rather than `time.sleep` — the latter would block the whole event loop for up to sixteen seconds while holding the semaphore.

The failure is written through `self._describe(error)` rather than interpolated directly, for the reason given under `_describe` below: several httpx transport errors stringify to the empty string, and `failed ()` in a log line tells you nothing about what went wrong.

```python
        raise TransientFailure(
            f"OpenRouter failed after {self._max_retries} attempts: {self._describe(last_error)}"
        ) from last_error
```

`openrouter.py:201-203`. Out of attempts. Note the dedent — this is outside both context managers, so the semaphore and the client are released before the exception is constructed.

Three things are happening on these three lines and each one was a fix.

`TransientFailure` rather than `LLMError` is the type fix, described in full under the class itself above. It is what lets `is_transient` classify on the exception type at `job_runner.py:68` instead of guessing from the message.

`self._describe(last_error)` rather than `{last_error}` is the message fix. Before it, a job that died on a connect timeout wrote `OpenRouter failed after 3 attempts: ` into its `error_message` column — a colon with nothing after it — because `str(httpx.ConnectTimeout(""))` is the empty string.

`from last_error` sets `__cause__`, so the original transport exception is still in the traceback with its own stack. Without it the traceback stops at this line and the actual fault is gone.

### `_limiter`

```python
    def _limiter(self) -> asyncio.Semaphore:
        """
        The semaphore belonging to the caller's event loop.

        A semaphore binds itself to the first loop that contends on it and
        refuses every other one, so the provider keeps one per loop. The loop
        itself is the key: `id()` is recycled once a loop is collected, which
        would hand a fresh loop the dead loop's semaphore, and holding the loop
        weakly keeps the table from growing for the life of the process.
        """
```

`openrouter.py:205-214`. This is bug number four, and the docstring is the answer.

The situation is that the provider is a process-wide singleton (`factory.py:15`) but there is more than one event loop in a process's life. FastAPI runs on one. Every Celery task builds a fresh one. So the provider outlives loops.

An `asyncio.Semaphore` cannot be shared across loops. On Python 3.10 it binds itself to a loop the first time it actually has to make a coroutine wait, and from then on raises `RuntimeError: ... is bound to a different event loop` if a different loop touches it. So one semaphore per loop is required, not merely tidy.

The original code kept them in a plain dict keyed by `id(loop)`. That is the bug. CPython's `id()` is the object's memory address, and addresses are reused as soon as an object is freed. A Celery task builds a loop, uses it, closes it, the loop is collected, and the *next* loop allocated in that freed memory gets the same `id`. The dict lookup then hits, and the new loop is handed the previous loop's semaphore — a semaphore already bound to a loop that no longer exists. The symptom is a `RuntimeError` about a different event loop, appearing occasionally in Celery workers and never once locally.

The fix is to key by the loop object itself, so identity is real identity rather than an address that happens to be free.

```python
        loop = asyncio.get_running_loop()
```

`openrouter.py:215`. `get_running_loop`, not `get_event_loop`. The former raises if there is no running loop; the latter would create one, or return a stale one, and is deprecated for this use. In this method the running loop is exactly what we want and there is always one, because `_limiter` is only called from `_send`, which is `async`.

```python
        limiter = self._limiters.get(loop)
        if limiter is None:
            limiter = asyncio.Semaphore(self._concurrency)
            self._limiters[loop] = limiter
        return limiter
```

`openrouter.py:216-220`. Get-or-create. No lock, and it does not need one: there is no `await` anywhere between the lookup and the store, so within a single event loop this cannot be interleaved. Two different threads running two different loops would be storing under two different keys, so they cannot collide either.

`WeakKeyDictionary` rather than a plain dict is the second half. A plain dict keyed by loop objects would keep every loop it has ever seen alive forever — one leaked event loop per Celery task, with all its selectors and handles. The weak keys mean an entry disappears when the loop is collected.

**Worth knowing — the weak keying does not actually reclaim, in the case that matters.** A `WeakKeyDictionary` only helps if the value does not strongly reference the key, and here it does. On Python 3.10, `asyncio.Semaphore` stores `self._loop = loop` the first time it has to make a waiter wait. So once concurrency genuinely reaches the ceiling of six, the semaphore holds a strong reference to the loop, the value keeps the key alive, and the entry can never be collected. Verified on this venv's 3.10.6:

```
uncontended (2 tasks, cap 6): semaphore never binds -> table size 0, loop collected
contended (5 tasks, cap 2):   semaphore binds       -> table size 3 after 3 closed loops,
                                                       all 3 loops still alive
```

The important half of the fix — that a fresh loop can never inherit a dead loop's semaphore — is completely correct, and that was the actual bug. It is the "keeps the table from growing" clause of the docstring that only holds while no loop ever hits the concurrency ceiling. The growth is one small entry plus one loop object per Celery task, so it is slow, but it is not zero. Being the one who volunteers this is much better than being asked.

### The response handlers

```python
    @staticmethod
    def _checked(response: httpx.Response) -> Dict[str, Any]:
        if response.status_code in RETRYABLE_STATUS:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise PermanentFailure(f"HTTP {response.status_code}: {response.text[:400]}")
        return response.json()
```

`openrouter.py:222-228`. Status classification, ordered so the retryable set is tested first — otherwise 429 and 500 would both be caught by `>= 400` and classified permanent.

The message format `f"HTTP {code}: ..."` is not arbitrary. It is what `job_runner.py:54` matches against:

```python
TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")
```

That regex is bug number two. The original version matched a bare three-digit number anywhere in the error text. The consequence was that an error reading `Source artifacts not found: 429e4567-e89b-12d3-a456-426614174000` was classified as transient and requeued, because the first four characters of a UUID happened to be `429e`. It surfaced as roughly one flaky test run in six — a job that should have failed permanently instead retried, changed state, and broke an assertion downstream.

The anchoring has three parts and it is worth being able to point at each. The alternation `(?:http|status|code)` requires the number to be *labelled* — a status code has to be introduced by one of those three words. `\s*[:=]?\s*` allows the label and the number to be separated by a colon, an equals sign, whitespace, or nothing, so `HTTP 503`, `status: 429`, `code=500` and `http429` all match. And the trailing `\b` is what defeats the UUID: a word boundary requires a non-word character after the digits, and in `429e4567` the character after `429` is `e`, which is a word character, so there is no boundary and no match. The leading `\b` before the alternation does the same job at the front.

The matching is done on `str(error).lower()` (`job_runner.py:71`), which is why the alternation is written in lowercase and still matches the uppercase `HTTP` this file emits.

`tests/test_pipeline.py:494-501` locks this down with the exact UUID from the original failure.

Note where this regex now sits in the order. Since `_send` raises `TransientFailure`, a provider failure that exhausted its retries is classified on its type at `job_runner.py:68` and never reaches the regex. The message matching is still the path for errors raised outside this package — a handler, a generator, a validator — where there is no useful type to test. It went from being the only mechanism to being the fallback, which is the right shape for it.

`response.text[:200]` for retryable and `[:400]` for permanent. The longer slice for permanent failures is deliberate: a permanent failure is one someone has to read and diagnose, so it gets more of the provider's explanation. A retryable one is usually a rate-limit notice and 200 characters is plenty.

```python
    @staticmethod
    def _content_of(payload: Dict[str, Any]) -> str:
        choices: List[Dict[str, Any]] = payload.get("choices") or []
        if not choices:
            raise LLMError(f"OpenRouter returned no choices: {json.dumps(payload)[:300]}")
```

`openrouter.py:230-234`. Pull the text out of the response envelope. `payload.get("choices") or []` handles both a missing key and an explicit `null`, which a gateway will sometimes send when an upstream provider errored — `.get("choices", [])` alone would return `None` in that case and the `if not choices` would still catch it, but the `or []` also keeps the type annotation honest.

This raises a plain `LLMError`, so it is retryable. That is right: an empty choices array is usually a momentary upstream fault.

The whole payload is dumped in the message, truncated to 300, because when there are no choices the interesting information is in the error object the gateway put there instead.

```python
        choice = choices[0]
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
```

`openrouter.py:236-239`. Take the first choice — only one is ever requested. `(choice.get("message") or {})` guards a null message the same way.

The list branch handles multimodal-style responses where the content arrives as an array of typed parts rather than a string. Concatenate the `text` of each part, skip anything that is not a dict, use `.get("text", "")` so a part with no text contributes nothing rather than raising. Defensive, and cheap.

```python
        if not content:
            raise LLMError("OpenRouter returned an empty completion")
```

`openrouter.py:240-241`. Empty is retryable. It catches both `None` and `""`.

```python
        if choice.get("finish_reason") == "length":
            raise TruncatedResponse(
                f"The model hit its output limit after {len(content)} characters. "
                "Raise LLM_MAX_OUTPUT_TOKENS or request a smaller artifact."
            )
        return content
```

`openrouter.py:243-248`. Explicit truncation detection, and this is the second half of the structured-output story.

The distinction to draw is between *detecting* truncation and *inferring* it. Before this check existed, a truncated JSON document was noticed only when `parse_as` failed to parse it — the document ended mid-string, `json.loads` complained about an unterminated string, and what surfaced was a generic parse error. That error is indistinguishable from the model having returned prose, or a fence, or a wrong shape.

Why the distinction matters is entirely about the retry decision. A parse failure is ambiguous, so the honest response to one is to retry — the model might do better next time. A truncation is not ambiguous: the model produced output until it ran out of budget, and given the same prompt and the same ceiling it will do exactly that again. Retrying costs a full output budget to learn nothing. During the mind-map incident, three attempts were spent this way, each one running to the ceiling before failing.

Reading `finish_reason` from the response envelope removes the ambiguity, because the provider is telling you directly. `"length"` means the output ceiling stopped it; `"stop"` means the model finished. Once you know which, the classification is free — `TruncatedResponse` is a `PermanentFailure`, and `_send`'s `except PermanentFailure: raise` on line 188 sends it straight out without a second attempt.

The message names `LLM_MAX_OUTPUT_TOKENS` because that is the actual lever, and includes the character count so the log records how close the ceiling was.

The order also matters slightly: the empty check comes first, so a response that produced nothing at all is reported as empty (retryable) rather than as truncated.

### `_describe`

```python
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
```

`openrouter.py:250-262`. Eight lines whose entire justification is one measurement: `str(httpx.ConnectTimeout(""))` is the empty string. So does `httpx.ReadTimeout("")`, and so do several of httpx's other transport errors, because httpx raises them with no message and relies on the type to carry the meaning.

That is fine while the exception object is in hand. It stops being fine the moment the failure is written down as text, which is exactly what happens to it: `_send`'s final message goes into the job row's `error_message` column, and that column is what the user sees and what an operator reads. Before this helper, a job that died on a connect timeout recorded

```
OpenRouter failed after 3 attempts:
```

and nothing after the colon. There was no way to tell a connect timeout from a read timeout from a refused connection, or indeed from a bug in the wrapping code.

The helper puts the class name in front, so the same failure now records `OpenRouter failed after 3 attempts: ConnectTimeout`. Where the exception does carry a message it is kept and the name is prefixed, giving `ConnectError: [Errno 61] Connection refused` — the name and the detail, which is strictly more than either alone.

`if detail else name` rather than always writing `f"{name}: {detail}"` is what avoids a trailing colon on the empty case. Small, and it is the difference between a line that reads as a fact and one that reads as a truncated string.

The `None` branch covers a case that cannot currently happen: `last_error` is only `None` if the loop never ran, which needs `LLM_MAX_RETRIES` set to zero. Returning `"no attempt was made"` rather than the string `"None"` means that if someone ever does set it to zero, the record says what actually happened.

`tests/test_pipeline.py:170` pins the behaviour directly: drive `_send` against a transport that always raises `httpx.ConnectTimeout("")` and assert that `"ConnectTimeout"` appears in the resulting message.

### `_backoff`

```python
    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2 ** attempt, 16) + random.uniform(0, 0.75)
```

`openrouter.py:264-266`. Exponential backoff with jitter and a cap. `2 ** attempt` gives 1, 2, 4 for the three attempts. `min(..., 16)` caps it, which is inert at three retries but keeps the function honest if `LLM_MAX_RETRIES` is raised — without the cap, six retries would end with a 32-second sleep.

`random.uniform(0, 0.75)` is the jitter, and it is the part with a reason. When a fan-out of six concurrent calls all hit a rate limit at the same moment, they all back off by the same amount and all retry at the same moment, reproducing the burst that caused the limit. A sub-second random offset spreads them out. It is small because the backoff intervals are small.

### On the async surface

Point seven from the history lands here. Concurrency in this project was effectively 1 for a period, and the cause was not the worker count — it was that async handlers were calling a synchronous HTTP client. A synchronous call inside a coroutine blocks the event loop entirely for its duration, so a ninety-second generation stopped every other coroutine in the process for ninety seconds. Raising `WORKER_CONCURRENCY` did nothing, because the loop those workers share was frozen.

The async surface is now the interface itself. `base.py:29`, `base.py:33` and `base.py:41` are all `async def`, so every implementation must be awaitable. In this file that is honoured with `httpx.AsyncClient` at `openrouter.py:183` and `await client.post` at `186`. The two remaining blocking operations are pushed off the loop deliberately with `asyncio.to_thread`: base64 encoding at `openrouter.py:113` and ffmpeg conversion at `media.py:73`. The concurrency ceiling is the semaphore at `openrouter.py:218`, which is a chosen number rather than an accident of blocking.

The visible payoff is `cleaning.py:149` and `knowledge.py:115` — both `asyncio.gather` over chunks. Those only mean anything if the calls are genuinely concurrent. Note that the cleaning one is now reached only on the transcript path, because `TextCleaner.clean` runs no model pass at all; the reasoning for that is in document 06.

---

# `backend/llm/offline.py`

322 lines. The fallback provider, and the file that carries the best story in the project.

```python
"""Deterministic provider used when no API key is configured."""
```

`offline.py:1`. "Deterministic" is the key word. Same input, same output, every time. That is what makes it usable as a test fixture as well as a degraded runtime mode.

```python
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type

from backend.llm.base import LLMError, LLMProvider, Schema
```

`offline.py:5-10`. No `httpx`, no network, no `asyncio`. That last absence is notable — the methods are `async def` because the interface requires it, but nothing inside them ever awaits.

```python
STOPWORDS = frozenset("""
about after again also because been before being between both could does during
each every from have having here into material more most must other over should
since some source such than that their them then there these they those through
under until using very were what when where which while will with would your
""".split())
```

`offline.py:14-19`. A hand-written stopword list, written as a triple-quoted block and split on whitespace so it stays readable in the source rather than being a hundred-element list literal. `frozenset` for constant-time membership.

Note "material" and "source" in there. Those are not English stopwords — they are *prompt* words. Because `_source_text` can fall back to returning the prompt itself when no context is supplied (`offline.py:94`), words from the instruction text would otherwise dominate the frequency count and every offline artifact would be titled "Material". Two entries that only make sense once you know how the fallback works.

```python
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
```

`offline.py:21`. What counts as a candidate term: starts with a letter, then at least three more characters from letters, digits, underscore or hyphen. So a minimum length of four. That filters out the short function words that survive the stopword list without needing to enumerate them.

```python
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
```

`offline.py:22`. Split on whitespace that follows sentence-ending punctuation. `(?<=...)` is a lookbehind, so the punctuation is a condition rather than part of the match — the sentences keep their full stops. Naive about "Dr." and "e.g.", which is fine for a fallback.

```python
PASS_THROUGH_MARKERS = (
    "verbatim",
    "do not summarise",
    "do not summarize",
    "keep the meaning identical",
    "preserve every idea",
)
```

`offline.py:24-30`. This is the fix for bug number three. The story is below at `_wants_the_source_back`.

```python
class OfflineProvider(LLMProvider):
    """
    Derives artifacts from the source material with frequency analysis.

    Output quality is far below a real model, but every pipeline stage runs, so
    a missing key degrades results instead of breaking the product.
    """

    name = "offline"
    supports_audio = False
```

`offline.py:33-42`. "Every pipeline stage runs" is the design claim and it is what the test suite depends on. `tests/conftest.py:58` sets `OPENROUTER_API_KEY` to the empty string, so every test runs against this class, and `tests/test_seams.py:98-112` asserts directly that the real `ArtifactGenerator` produces an artifact for *every* type in `GENERATED_TYPES` from it with no code changes anywhere. Note that it iterates the advertised set rather than a hand-written list, so adding a new artifact type without adding a fixture here fails that test rather than only failing on a machine with no key.

That is what makes the Liskov claim real. The generator is not mocked, the handlers are not stubbed — an actual different subclass is substituted and the production code path runs unaltered. `supports_audio = False` is the one place it declines a capability, and it declines it through the flag that the interface provides for exactly that, not by breaking a method contract.

```python
    def __init__(self) -> None:
        logger.warning("No OPENROUTER_API_KEY set. Using the offline provider.")
```

`offline.py:44-45`. `warning`, not `info`. Running in degraded mode without noticing is the failure this line prevents. It is reinforced at the HTTP layer by `main.py:191`, which exposes `offline_model: provider.name == "offline"` so the frontend can say so too.

```python
    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        source = self._source_text(prompt, context)
        if self._wants_the_source_back(prompt):
            return source
        return self._markdown(source)
```

`offline.py:47-51`. Three lines, and the middle one is the bug fix.

### The one-word locale bug

```python
    @staticmethod
    def _wants_the_source_back(prompt: str) -> bool:
        """
        Whether the prompt edits its input rather than deriving something new.

        A cleaning or transcription pass must get its text back unchanged; the
        heuristic rewrite would replace a whole lecture transcript with a
        synthetic study document and every later stage would build on that.
        """
        lowered = prompt.lower()
        return any(marker in lowered for marker in PASS_THROUGH_MARKERS)
```

`offline.py:53-63`. This is the best failure in the project because of how quietly it went wrong.

There are two fundamentally different kinds of `complete` call in this codebase. Most of them derive something new — "write study notes from this material" — and for those, generating a heuristic Markdown document is a reasonable degraded answer. But `pipeline/cleaning.py` calls `complete` to *edit its input*: fix the grammar in this transcript chunk and hand it back. For that kind of call the only sane offline behaviour is to return the text unchanged. That call now lives only on the transcript path — `TextCleaner.clean`, the document path, makes no model call at all — so the exposure today is narrower than it was, but the mechanism is unchanged.

So the provider needs to tell them apart from the prompt alone. The original check was a single condition:

```python
if "Do NOT summarize" in prompt:      # the original
```

American spelling, and case-sensitive. The prompt it was meant to match is at `cleaning.py:23-24`:

```
Keep the meaning identical and preserve every idea. Do NOT summarise, shorten or
reorder the content. Output plain text only.
```

British spelling. `summarise`, with an s.

The check never matched. Not once. So every cleaning call took the derive path, and the offline provider replaced each 4,000-character transcript chunk with a synthetic study document — a Markdown page with a `# Title`, a Summary section, a bulleted Key points section and five Review questions, all generated from word frequencies.

Follow what happens next. `cleaning.py:162` joins those chunks back together and returns them as the cleaned transcript. `pipeline/knowledge.py` builds the knowledge core from that. Every artifact — quiz, flashcards, slides, cheat sheet, mind map — is generated from the core. So every artifact in the product was built from a synthetic document instead of from the lecture.

And nothing raised. No exception, no warning, no failed test. The text was well-formed English of a plausible length. The knowledge core had a title, concepts, definitions and key facts. The quizzes had questions with four options each. The output looked right. It was simply about the wrong document.

That is the quality of the bug worth describing: silent corruption with plausible-looking output. A crash is cheap; this cost a debugging session that started from "the quiz answers feel oddly generic" and had to be traced backwards through four pipeline stages to a single letter.

The fix has two parts, and both matter.

`prompt.lower()` on `offline.py:62` removes case from the question entirely. `Do NOT summarise`, `do not summarise`, `DO NOT SUMMARISE` all reduce to the same string. Every marker in the tuple is already written in lowercase, so the comparison is symmetrical.

`any(marker in lowered for marker in PASS_THROUGH_MARKERS)` on `offline.py:63` makes it five independent chances instead of one. Check them against the actual repair prompt at `cleaning.py:19-25`:

- `"do not summarise"` — matches, British spelling.
- `"do not summarize"` — the American spelling, kept so that a future prompt written the other way also works.
- `"keep the meaning identical"` — matches, from the first sentence.
- `"preserve every idea"` — matches, from the first sentence.
- `"verbatim"` — does not match this prompt, but matches `TRANSCRIBE_PROMPT` at `openrouter.py:34`, which begins "Transcribe this recording verbatim".

So three of the five markers independently match the one prompt that matters. That is the reason the current form cannot fail the same way: the failure required a single exact string to be the only thing standing between the transcript and the rewrite. Now a spelling change, a rewording, or a case change would each have to defeat three separate phrases drawn from two different sentences before the passthrough would silently stop working. Localisation is handled explicitly by carrying both spellings rather than by hoping.

The remaining weakness, and it is the right thing to volunteer: this is still string matching against prompt text across a module boundary. A rewrite of `REPAIR_PROMPT` that dropped all three phrases would reintroduce the failure, silently, in exactly the original way. Five markers make the contract harder to break by accident; they do not make it impossible.

What closes the gap is a test rather than a code change, and it is worth knowing exactly where it is. `tests/test_pipeline.py:266` is the whole of it:

```python
assert OfflineProvider._wants_the_source_back(REPAIR_PROMPT) is True
```

That is an assertion across the module boundary itself: it imports `REPAIR_PROMPT` from `pipeline/cleaning.py` and `OfflineProvider` from `backend/llm/offline.py` and checks that the two still agree. Reword the prompt out of every marker and this test goes red, which is the whole point — the original failure had no other symptom. The lesson stated earlier, that a string comparison across a module boundary is an untested contract, is now the *tested* version of that contract.

Two more tests in the same class read the output rather than the recogniser, at `tests/test_pipeline.py:278` and `:296`: run the real `TextCleaner` with a real `OfflineProvider` over a real transcript, and assert that a sentence from the lecture survives, that the offline provider's own marker text does *not* appear, and that the cleaned text is at least 90 per cent of the length of the input. That is the property the recogniser exists to protect, checked directly. The second of those goes through `IngestHandler._clean` with `source_type="audio"`, which is the door the bug actually came through.

The structurally correct fix is still different and still larger: a flag on the call — `complete(prompt, context, passthrough=True)` — so the caller states its intent instead of the provider inferring it. That is an interface change affecting every provider, which is why it was not done for a fallback path. The five markers are the cheap version of the guarantee, and the test at line 266 is the cheap version of enforcing it. Know all three, and say them before you are asked.

```python
    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        builder = self._builders().get(schema.__name__)
        if builder is None:
            raise LLMError(f"The offline provider has no fixture for {schema.__name__}")
        return schema.model_validate(builder(prompt, self._source_text(prompt, context)))
```

`offline.py:65-74`. Structured generation by lookup table, keyed on the schema's class name.

Two details worth noticing. The failure for an unknown schema is an `LLMError` naming the class, which is a clear instruction to whoever added a model and forgot the fixture. And the builders return plain dicts which are then passed through `schema.model_validate` — so the offline fixtures are validated against the same Pydantic models as real responses. A fixture that drifts out of shape fails immediately rather than producing an object that is subtly wrong.

Note also what does *not* happen here: no `extract_json`, no `parse_as`. The offline path builds a dict and validates it directly, which is why the `extract_json` fence bug documented above is invisible to the test suite.

```python
    def _builders(self) -> Dict[str, Callable[[str, str], Dict[str, Any]]]:
        return {
            "KnowledgeCore": self._knowledge_core,
            "ExamSpec": self._exam_spec,
            "QuestionBatch": self._question_batch,
            "QuizModel": self._quiz,
            "FlashcardModel": self._flashcards,
            "SlidesModel": self._slides,
            "StudyGuideModel": self._study_guide,
            "CheatSheetModel": self._cheat_sheet,
            "MindMapModel": self._mind_map,
            "CoreSummary": self._core_summary,
            "CombinedContext": self._combined_context,
            "Intent": self._intent,
        }
```

`offline.py:76-90`. Twelve fixtures — every schema the pipeline can ask for. `KnowledgeCore` for extraction, `ExamSpec` and `QuestionBatch` for the two-stage exam build, eight artifact models, `CoreSummary` and `CombinedContext` for the multi-source merger, `Intent` for the chat assistant.

The method rebuilds the dict on every call rather than holding it as a class attribute. That costs a dozen dict insertions per generation, which is irrelevant, and it buys the ability to reference bound methods with `self.` in a simple literal. A class-level dict would need unbound functions and an explicit `self` at the call site.

Note there is no `NotesModel` entry, and none is needed: notes go through `complete()` and `_as_notes` (`generators.py:237`), never `complete_as`.

```python
    @staticmethod
    def _source_text(prompt: str, context: Optional[str]) -> str:
        if not context:
            return prompt
        try:
            parsed = json.loads(context)
        except (json.JSONDecodeError, TypeError):
            return context
        if not isinstance(parsed, dict):
            return context
```

`offline.py:92-101`. Work out what text to analyse.

No context: fall back to the prompt. That is the case the "material" and "source" stopwords exist for.

Then it tries to parse the context as JSON, because most `complete_as` calls in this codebase pass `core.model_dump_json()` as context (`generators.py:232`) — a serialised knowledge core. If it parses as a dict, the interesting text is inside specific fields; if it does not, the context is raw prose and is used as-is.

Both guards are needed. `JSONDecodeError` for prose that is not JSON, which is the common case — a 4,000-character transcript chunk. `TypeError` for a context that is not a string type at all. And the `isinstance(parsed, dict)` check on line 101 covers the case where the context is valid JSON but not an object — a chunk consisting of the single line `42` parses successfully to an integer, and without this check the field extraction below would raise `AttributeError`.

```python
        parts = [str(parsed.get("title") or ""), str(parsed.get("summary") or "")]
        for concept in (parsed.get("concepts") or [])[:12]:
            if isinstance(concept, dict):
                parts += [str(concept.get("name") or ""), str(concept.get("description") or "")]
        for fact in (parsed.get("key_facts") or [])[:12]:
            if isinstance(fact, dict):
                parts.append(str(fact.get("fact") or ""))
        return " ".join(part for part in parts if part) or context
```

`offline.py:103-110`. Flatten a knowledge core into one string.

Every access is `or ""` guarded and wrapped in `str()`, so a null field or an unexpected type never breaks the flattening. The `[:12]` slices bound the work — a core from a long lecture can carry many concepts, and twelve is enough for frequency analysis. The `isinstance(..., dict)` checks inside the loops guard a list containing something other than objects.

The final `or context` is the last fallback: if the JSON parsed as a dict but had none of the expected fields, use the raw text rather than returning an empty string, which would make every downstream method produce its placeholder.

**Worth knowing.** `complete()` at `offline.py:48-50` computes `source = self._source_text(prompt, context)` *before* the passthrough check, and the passthrough returns `source` rather than `context`. For every real cleaning call that is identical, because a transcript chunk is not JSON and `_source_text` returns it verbatim on line 99. But a chunk that happened to be a valid JSON object would be flattened rather than passed through. It cannot happen with a lecture transcript, and it is exactly the sort of thing a careful reader will spot and ask about.

```python
    @staticmethod
    def _terms(text: str, limit: int = 10) -> List[str]:
        counts: Dict[str, int] = {}
        display: Dict[str, str] = {}
        for word in WORD.findall(text):
            key = word.lower()
            if key in STOPWORDS:
                continue
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, word.strip("_-").title())
```

`offline.py:112-121`. Frequency count. Two parallel dictionaries: `counts` keyed by the lowercased word so that "Consensus" and "consensus" count as one term, and `display` holding a presentable form. `setdefault` means the *first* occurrence sets the display form and later ones do not overwrite it, so the output is stable. `strip("_-")` removes leading and trailing punctuation left by the `WORD` pattern, and `.title()` gives title case for headings.

```python
        ranked = sorted(counts, key=lambda key: (-counts[key], key))
        return [display[key] for key in ranked[:limit]] or ["Core Concept", "Key Idea", "Study Focus"]
```

`offline.py:123-124`. Sort by the tuple `(-count, key)`: descending frequency, then alphabetically as a tiebreak. The alphabetical tiebreak is what makes the provider deterministic — without it, two terms with the same count would order by dictionary insertion, which is stable in CPython but not something to rely on for test assertions.

The `or [...]` fallback covers text with no qualifying words at all, so no downstream method ever indexes into an empty list.

```python
    @staticmethod
    def _sentences(text: str, limit: int = 12) -> List[str]:
        found = [s.strip() for s in SENTENCE_BREAK.split(text) if len(s.strip()) > 25]
        return found[:limit] or [text.strip()[:220] or "This material introduces the main ideas."]
```

`offline.py:126-129`. Split into sentences, discard anything under 26 characters as a fragment, cap at twelve. Two layers of fallback: if no sentence qualifies, take the first 220 characters of the raw text; if that is empty too, a fixed string. The same defensive pattern as `_terms` — the fixtures below index into these lists freely, so they must never be empty.

```python
    def _parts(self, text: str) -> tuple[List[str], List[str], Callable[[int], str]]:
        terms, sentences = self._terms(text), self._sentences(text)
        return terms, sentences, lambda index: sentences[index % len(sentences)]
```

`offline.py:131-133`. The shared preamble for every fixture. Returns the terms, the sentences, and a closure that indexes into the sentences with wraparound.

That third value is what lets the fixtures be written without bounds checks. `_quiz` builds twelve questions and `_flashcards` builds fifteen cards, from a sentence list capped at twelve — `sentence(index)` wraps with `%` rather than raising `IndexError`. It is the reason the fixtures read as clean list comprehensions rather than as loops full of `min()` calls.

Note `tuple[...]` in lowercase in the annotation. That is a 3.9+ builtin generic and it works here because of `from __future__ import annotations` on line 3, which stops the annotation being evaluated.

```python
    def _knowledge_core(self, _prompt: str, text: str) -> Dict[str, Any]:
```

`offline.py:135`. The most important fixture, because everything downstream is built from a knowledge core. The `_prompt` parameter is prefixed with an underscore to say it is deliberately unused — the signature is fixed by the `Callable[[str, str], Dict[str, Any]]` type in `_builders`, so it has to accept it.

`offline.py:136-165` builds the full core: a title from the top term, a summary from the first three sentences, six concepts with descending `importance_score` via `max(5, 10 - index)`, a one-level section hierarchy, a notes block, four definitions, two examples and five key facts. Every field the real `KnowledgeCore` model declares, populated with something shaped correctly. The descending importance score exists so that any downstream code sorting by importance has a meaningful order to sort by.

`offline.py:167-174`, `_exam_spec`: entirely static. No analysis, because an exam specification is about assessment style, not about content, and there is nothing in word frequencies that could inform it.

`offline.py:176-193`, `_question_batch`: two pieces of prompt parsing.

```python
        kind = next((c for c in ("MCQ", "Short Answer", "Problem Set") if c in prompt), "Short Answer")
        match = re.search(r"EXACTLY\s+(\d+)", prompt)
        count = int(match.group(1)) if match else 5
```

`offline.py:178-180`. The exam generator asks for batches of a specific type and a specific size, and the offline provider has to honour both or the generator's own validation will reject the result. `next(generator, default)` is the compact way to take the first match with a fallback. The `EXACTLY\s+(\d+)` pattern reads the requested count out of the prompt, with `\s+` so any whitespace works. If neither is found, sensible defaults.

This is a small but real point about the offline provider: it is not just returning fixed data, it is reading the prompt closely enough to satisfy the same contract checks a real model has to satisfy. `generators.py` validates minimum item counts (`tests/test_seams.py:119-133` exercises the rejection path), so a fixture that ignored the requested count would fail those checks.

`offline.py:195-210`, `_quiz`: twelve MCQ questions, `correct_answer_index: 0` always, with the correct option being a real sentence from the source and the three distractors being fixed negative statements. Deterministic and structurally valid.

`offline.py:212-219`, `_flashcards`: fifteen cards from `(terms * 3)[:15]` — repeat the term list three times and slice, so fifteen cards are produced even when only five distinct terms were found. The same trick appears in `_slides` at line 232 with `(terms * 2)[:8]`.

`offline.py:221-233`, `_slides`; `offline.py:235-243`, `_study_guide`, which reuses `_markdown` for its body field; `offline.py:245-253`, `_cheat_sheet`.

```python
    def _mind_map(self, _prompt: str, text: str) -> Dict[str, Any]:
```

`offline.py:255-271`. Worth looking at because of the three-level structure. `root` with a label and detail, `children` built from the first five terms, and each of those with its own `children` built from `terms[index + 1 : index + 3]` — the terms that follow it in the ranking. That slice is safe when it runs off the end of the list, because Python slices clamp rather than raise.

Every `detail` is truncated with `[:140]`, which matches the `Field` description on `MindMapLeaf.detail`: "One sentence under 140 characters" (`artifacts.py:110`). The offline fixture honours the same bound the prompt asks a real model to honour, so anything rendering a mind map gets consistently-sized text either way.

`offline.py:273-280`, `_core_summary` and `offline.py:282-291`, `_combined_context`: the merger's two schemas, for combining several sources. `_combined_context` hardcodes `source_count: 1` and `conflict_notes: None`, which is honest — a frequency-analysis fallback has no way to detect conflicts between sources.

```python
    def _intent(self, _prompt: str, _text: str) -> Dict[str, Any]:
        return {
            "action": "answer",
            "target_type": None,
            "instructions": None,
            "reply": (
                "No language model is configured, so I cannot answer questions or "
                "revise artifacts. Set OPENROUTER_API_KEY to enable the assistant."
            ),
        }
```

`offline.py:293-302`. The chat assistant's intent classifier, and the one fixture that declines rather than pretends. Both parameters unused.

The reason this one is different is worth stating. Every other fixture produces something structurally valid and roughly useful — a bad quiz is still a quiz. But an assistant that answers a user's specific question with word-frequency output would be actively misleading, because the user asked something specific and would get a confident, unrelated answer. The `action: "answer"` with an honest `reply` is the assistant declining through its normal channel rather than erroring.

That is the same reasoning as `main.py:191` exposing `offline_model` to the frontend: degraded mode has to be visible, not disguised.

```python
    def _markdown(self, text: str) -> str:
```

`offline.py:304-322`. The free-text generator, used by `complete()` on line 51 and by `_study_guide` on line 241. Builds a Markdown document with a title from the top term, a blockquote saying it came from the offline provider and how to fix that, a summary, up to eight bullets, five `###` concept sections and five review questions.

The blockquote on lines 316-317 is the same visibility principle again — the degraded output labels itself, so a user who copies it into their notes can still see where it came from.

This is precisely the document that replaced every lecture transcript during the locale bug. Seeing that it is well-formed, plausible and completely disconnected from the source is what makes the bug's silence understandable.

**Worth knowing.** `_markdown` calls `self._parts(text)`, which computes `_terms` and `_sentences` again even when the caller has already computed them. In `_study_guide` (line 236 computes `terms`, line 241 calls `_markdown` which recomputes) that is a duplicated pass over the text. Irrelevant at these sizes, and worth naming as a known redundancy rather than being told about it.

---

# `backend/llm/factory.py`

Forty-six lines. Provider selection and caching.

```python
"""Selects and caches the language-model provider for this process."""
```

`factory.py:1`. "For this process" is the important qualifier — this is a per-process singleton, and a Celery worker, the API process and a test session each have their own.

```python
import logging
import threading

from backend.core.config import get_settings
from backend.llm.base import LLMProvider
from backend.llm.offline import OfflineProvider
from backend.llm.openrouter import OpenRouterProvider
```

`factory.py:5-11`. This is the only module in the package that imports both concrete providers. That is what keeps the dependency inversion intact: everything else imports `LLMProvider` from `base`, and this one file is the composition root that knows which implementations exist.

```python
_provider: LLMProvider | None = None
_lock = threading.Lock()
```

`factory.py:15-16`. The cached instance and the lock guarding its construction. `LLMProvider | None` in lowercase union syntax works at module level on 3.10 without the future import, though the file has it anyway on line 3.

A `threading.Lock` and not an `asyncio.Lock`, which is the right choice: this is a synchronous function that can be called from any thread — a Celery worker thread, a FastAPI startup hook, a `to_thread` executor — and an asyncio lock would only serialise coroutines on one loop.

```python
def build_provider() -> LLMProvider:
    """Return OpenRouter when a key is configured, otherwise the offline provider."""
    if not get_settings().has_llm_key:
        return OfflineProvider()
```

`factory.py:19-22`. First branch. `has_llm_key` is a property on the settings object (`config.py:146-148`) that is just `bool(self.openrouter_api_key)`. Putting it behind a named property rather than checking the string here means the definition of "configured" lives in one place.

```python
    try:
        return OpenRouterProvider()
    except Exception as error:
        logger.warning("OpenRouter unavailable (%s). Falling back to the offline provider.", error)
        return OfflineProvider()
```

`factory.py:24-28`. Second branch, and the fallback that makes the whole thing safe.

There is a key, so try to build the real provider. If construction fails for any reason — a malformed base URL, a settings problem, anything raised from `OpenRouterProvider.__init__` — log it and fall back rather than propagating. This is the reason `openrouter.py:74-75` validates the key at construction time: it turns a class of configuration problems into something this `try` can catch at startup.

The design claim is that the application always starts. A misconfigured key degrades the product to offline mode with a warning in the log and an `offline_model: true` on the capabilities endpoint; it does not prevent the server from booting. For something a user will run from a README that is the right default, and the visibility work in `offline.py:45` and `main.py:191` is what stops it from being a silent trap.

`except Exception` and not `except BaseException`, so `KeyboardInterrupt` during startup still interrupts.

```python
def get_provider() -> LLMProvider:
    """The shared provider, constructed on first use."""
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                _provider = build_provider()
                logger.info("LLM provider: %s", _provider.name)
    return _provider
```

`factory.py:31-39`. Double-checked locking, and the doubling is the point.

The outer `if` on line 34 is the fast path: once the provider exists, every subsequent call returns it without touching the lock at all. `get_provider` is called from constructors all over the codebase — `cleaning.py:76`, `knowledge.py:101`, `generators.py:214`, `merger.py:81`, `media.py:53`, plus `main.py:174` on every health check — so the uncontended path being lock-free is worth having.

The inner `if` on line 36 is the correctness half. Two threads can both pass the outer check while `_provider` is still `None`; one takes the lock and builds, the other waits. When the second one gets the lock it has to look again, because the world changed while it was waiting. Without the second check, both build a provider, both log, and the second overwrites the first — two `OpenRouterProvider` instances, each with its own semaphore table, so the concurrency limit would silently be twelve rather than six.

This pattern is genuinely safe in CPython because assignment to a module global is a single bytecode operation and cannot be observed half-done.

The log line is inside the lock so it fires exactly once per process.

```python
def reset_provider() -> None:
    """Discard the cached provider so the next call rebuilds it."""
    global _provider
    with _lock:
        _provider = None
```

`factory.py:42-46`. The escape hatch, and it exists for the tests.

`tests/conftest.py:72` calls it as part of `_reset_singletons`, alongside `get_settings.cache_clear()` and the database, file store, event bus and dispatcher resets. Without it, the first test to construct a provider would fix it for the whole session and a later test that changes `OPENROUTER_API_KEY` via monkeypatch would still get the old instance — because the settings snapshot happens in `OpenRouterProvider.__init__` (`openrouter.py:73`), not per request.

It takes the lock, which is not strictly required for a single assignment but is consistent with `get_provider` and costs nothing.

Setting to `None` rather than building a replacement means the rebuild is lazy — the next `get_provider()` does it, under whatever settings are current then.

---

# `backend/llm/__init__.py`

Six lines, and they are a decision about what the rest of the codebase is allowed to see.

```python
"""Language-model providers behind one interface."""

from backend.llm.base import LLMError, LLMProvider
from backend.llm.factory import get_provider, reset_provider

__all__ = ["LLMError", "LLMProvider", "get_provider", "reset_provider"]
```

`__init__.py:1-6`.

Four names are re-exported: the interface, the error type, the accessor and the test reset. That is the complete public surface. `OpenRouterProvider`, `OfflineProvider`, `strict_schema`, `parse_as`, `PermanentFailure` and `TruncatedResponse` are all deliberately absent. Nothing outside this package should name a vendor class, and nothing outside it should need to build a schema.

`__all__` restates the same four names. It controls `from backend.llm import *` and, more usefully, it tells linters that these imports are intentional re-exports rather than unused imports to be flagged.

The convention is not perfectly enforced — `pipeline/cleaning.py:10-11` imports from `backend.llm.base` and `backend.llm.factory` by their full paths rather than through the package, and `tests/conftest.py:68` imports the `factory` module directly so it can call `reset_provider` after a monkeypatch. Both are reaching past the front door, and both are reaching for things that are on the list anyway. The line that would actually matter — an import of `OpenRouterProvider` from outside this package — does not exist anywhere. That is the invariant worth stating, and it is checkable in one grep.
