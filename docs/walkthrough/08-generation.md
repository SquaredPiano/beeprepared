# 08 — Generation and export

## How a knowledge core becomes an artifact, and then a file

Ingestion ends with a `KnowledgeCore`: a Pydantic object holding a title, a summary, a list of concepts, a section hierarchy, note blocks, definitions, examples and key facts. That object is defined in `backend/pipeline/knowledge.py:74`. Everything in this document happens after that point.

The path is short. `GenerateHandler.run` (`backend/handlers/generate_handler.py:47`) resolves the source artifacts the user wired into the node into a list of knowledge cores. If there is more than one core it calls `CoreMerger.merge` to collapse them into a single combined context, which the handler then rebuilds into one synthetic `KnowledgeCore` (`generate_handler.py:90`). It hands that core to `ArtifactGenerator.generate` along with the target type and any free-text instructions. The generator looks up a `GeneratorSpec` by type, serialises the core to JSON, sends prompt plus JSON to the language model, validates what comes back, and returns a typed Pydantic model. The handler then calls `ExportService.export`, which renders the model to a file if that type has a natural file form, stores the file in the `FileStore`, and returns a small record of where it went. That record is stashed under `content["binary"]` on the artifact row, and `backend/api/routes/artifacts.py:113` later turns it into an HMAC-signed, expiring download URL.

The important structural point is that the model never sees the raw transcript at this stage. It sees `core.model_dump_json()`. That is why a project's quiz, notes and exam agree with each other: they are eight different renderings of one shared representation, not eight independent readings of the same wall of text.

The second structural point is that the eight types are data, not code. Adding a type is one entry in `SPECS` in `generators.py` and one entry in `ARTIFACT_MODELS` in `backend/models/artifacts.py`. Going from five types to eight touched exactly those two dictionaries.

---

## backend/services/generators.py

351 lines. This is the biggest file in the set and the one most likely to be opened on screen.

### The header, lines 1 to 30

```python
"""Turns a knowledge core into a typed study artifact."""

from __future__ import annotations
```

Line 1 is the module docstring and says the whole job of the file in one sentence. Line 3 is `from __future__ import annotations`, which makes Python store type annotations as strings instead of evaluating them at import time. Two consequences worth knowing: it makes annotations free at runtime, and it lets you refer to a type before it is defined. It is at the top of nearly every module in this backend, so it is a house style rather than a decision made here.

```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Type
```

Lines 5 to 8. `asyncio` is here for exactly one thing, `asyncio.gather` on line 260. `dataclass` is for `GeneratorSpec`. `Type` is needed because `GeneratorSpec.schema` holds a class, not an instance.

```python
from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider
```

Lines 12 and 13, and these two matter. `LLMProvider` (`backend/llm/base.py:17`) is an abstract base class with two methods: `complete(prompt, context) -> str` and `complete_as(prompt, schema, context) -> Schema`. This file never imports OpenRouter, never imports `httpx`, never knows what model is behind the call. `get_provider()` is a process-wide cached factory (`backend/llm/factory.py`) that returns the OpenRouter provider when an API key is configured and an offline stub provider when there is none. That is what lets the whole test suite run with no network and no key: `backend/tests/test_seams.py:97` builds `ArtifactGenerator(OfflineProvider())` and generates four artifact types through it.

Lines 14 to 25 import the eight artifact Pydantic models plus `ExamQuestion` and `ExamSpec`. Line 26 imports `KnowledgeCore`. Line 28 is the module logger, the standard `logging.getLogger(__name__)` pattern so log lines carry `backend.services.generators`.

```python
MIN_EXAM_QUESTIONS = 10
```

Line 30. A floor. The exam is assembled from three independently generated batches and any of them may fail; this is the point below which the surviving questions are not worth calling an exam. It is checked at line 277.

### Two small types, lines 33 to 40

```python
class GenerationError(RuntimeError):
    """A generator could not produce a usable artifact."""
```

Lines 33 and 34. A named exception type so callers can distinguish "the model gave us something unusable" from a network error or a bug. It subclasses `RuntimeError` rather than `Exception` directly, which is conventional but has no behavioural effect here.

```python
class QuestionBatch(BaseModel):
    """One batch of exam questions of a single type."""

    questions: List[ExamQuestion]
```

Lines 37 to 40. This exists for a technical reason that is worth being able to state. The provider's structured-output path (`backend/llm/openrouter.py:112`) sends `response_format: {"type": "json_schema", ...}` with a schema built from a Pydantic model, and a JSON Schema for structured output has to have an object at its root. You cannot ask for a bare array. So when the code wants a list of questions back it wraps the list in a one-field model and unwraps it again at line 330. That is the entire purpose of this class.

### GeneratorSpec, lines 43 to 74

```python
@dataclass(frozen=True)
class GeneratorSpec:
    """
    Everything that distinguishes one artifact type from another.

    Adding a type is a new entry here, not a new method plus a new branch in the
    handler plus a new validation rule.
    """
```

Lines 43 to 50. This is the headline design decision in the file, and the docstring states it plainly. `frozen=True` makes instances immutable, which is right for what is effectively a configuration record shared across every call, in every worker, for the life of the process. Nothing should be able to mutate a spec at runtime.

The claim in the docstring is the one an interviewer will test. The version of this code before the refactor had a method per type on the generator and a branch per type in the handler, and the validation rule for each type lived near the branch. Three places to touch, three places to forget. Now the differences between types are five fields on one record.

```python
    prompt: str
    schema: Optional[Type[BaseModel]] = None
    required_field: Optional[str] = None
    minimum_items: int = 0
    minimum_characters: int = 0
```

Lines 52 to 56, the five fields. Walk them one at a time, because "what would adding a ninth type involve" is a very likely question and this is the answer.

`prompt` is the only required field. It is the instruction text sent to the model, without the source material; the source material is passed separately as `context`.

`schema` is the Pydantic model the response must validate against, or `None`. `None` is not an oversight, it is a mode switch: a spec with no schema takes the free-text path at line 237 instead of the structured path at line 235. Exactly one type uses it, `notes`, because notes are Markdown prose and forcing prose through a JSON field would mean escaping every newline and every backslash in every LaTeX formula.

`required_field` is the name of the collection on the produced model that has to be non-trivially populated: `"questions"` for a quiz, `"cards"` for flashcards, `"slides"` for a deck. It is a string rather than a reference to the field because validation works off `model.model_dump()`, a plain dict.

`minimum_items` is how many entries that collection needs. It only means anything alongside `required_field`.

`minimum_characters` is the equivalent floor for the free-text path, measured on the `body` field.

```python
    def validate(self, model: BaseModel) -> None:
        """Reject artifacts that parse but would not help anyone."""
        data = model.model_dump()
```

Lines 58 to 60. The docstring is the reason this method exists at all. Pydantic validation only tells you the shape is right. A `QuizModel` with one question is perfectly valid JSON and a perfectly valid `QuizModel`, and it is also useless. This is the second gate: structural validity from Pydantic, then usefulness from here.

```python
        if self.minimum_characters:
            body = data.get("body") or ""
            if len(body) < self.minimum_characters:
                raise GenerationError(
                    f"Expected at least {self.minimum_characters} characters, got {len(body)}"
                )
```

Lines 62 to 67. Note `if self.minimum_characters:` — zero means the check is off, so specs that do not set it skip it entirely. `data.get("body") or ""` handles both "no body key" and "body is None" in one expression. The error message includes both the expectation and the actual, which is what you want at 2am reading logs. This is tested at `test_seams.py:143`: a notes generation returning `"# Too short"` raises with `at least 200 characters`.

```python
        if self.required_field:
            items = data.get(self.required_field) or []
            if len(items) < self.minimum_items:
                raise GenerationError(
                    f"Expected at least {self.minimum_items} {self.required_field}, got {len(items)}"
                )
```

Lines 69 to 74. Same shape for collections. The field name goes into the error message, so the log reads "Expected at least 5 questions, got 1" rather than something generic. Tested at `test_seams.py:119`.

**Worth knowing.** Two soft spots here that an interviewer poking at the validation could find. First, `minimum_characters` always reads the key `"body"`; it is not configurable. That works because the only spec using it is `notes`, whose model has a `body` field, but a future free-text type with a differently named field would silently measure an empty string and always fail. Second, `mindmap` sets neither `required_field` nor `minimum_characters`, so it gets no usefulness check at all. `MindMapModel` requires a `root`, but `MindMapRoot.children` defaults to an empty list (`backend/models/artifacts.py:122`), so a mind map with a root and no branches passes both gates. The honest answer if asked is that the spec table makes that a one-field fix rather than a code change, which is rather the point of the design.

### SPECS, lines 77 to 189

```python
SPECS: Dict[str, GeneratorSpec] = {
```

Line 77. A plain module-level dict keyed by the artifact type string. Those strings are effectively public API: they appear in `ARTIFACT_MODELS` (`backend/models/artifacts.py:137`), in the job payload the frontend sends, and in `ALLOWED_TARGETS` in `backend/handlers/sources.py:16`. Here is one entry in full, since it is the thing to be able to read aloud.

```python
    "quiz": GeneratorSpec(
        schema=QuizModel,
        required_field="questions",
        minimum_items=5,
        prompt="""
You are an expert examiner writing a practice quiz.

Write 10-15 questions covering the source material.

Rules:
1. Mix True/False and MCQ.
2. Cover the most important concepts, not the most obscure ones.
3. Distractors must be plausible. Never use "all of the above".
4. Every question must be answerable from the source material alone.
5. The explanation is what the learner reads to understand the answer.
6. Use LaTeX for all mathematics.
""",
    ),
```

Lines 78 to 95. Read the fields against the walkthrough above: structured output into `QuizModel`, the collection to count is `questions`, and five is the floor. Note the gap between "write 10-15" in the prompt and a floor of 5 in the spec. That is deliberate. The prompt states the target, the spec states the point below which you would rather fail the job than show the user the result. Setting the floor at 10 would fail jobs that produced a perfectly usable eight-question quiz.

Some of the prompt rules are worth understanding rather than skimming. Rule 3, "never use all of the above", exists because models reach for it constantly and it makes a question unanswerable as a test of anything. Rule 4 is the anti-hallucination rule, and it is the one that only works because the context is a knowledge core: "the source material" is a bounded, structured document, not a vague gesture at the world. Rule 6 appears in almost every prompt in this file because the frontend renders LaTeX, and a model left to its own devices will mix Unicode maths symbols and LaTeX in the same artifact.

The other six entries follow the same shape, so they are quick.

Lines 96 to 111, `flashcards`: `FlashcardModel`, count `cards`, floor 5, target 15-20. The interesting rule is "One idea per card. Split compound facts into separate cards." — that is spaced-repetition doctrine, and without it the model writes cards with three facts on the back.

Lines 112 to 127, `slides`: `SlidesModel`, count `slides`, floor 3. Target 10-12. Rule 3 requires speaker notes on every slide, which is what makes the PPTX export worth having, since python-pptx writes those into the notes pane.

```python
    "notes": GeneratorSpec(
        minimum_characters=200,
        prompt="""
...
Output pure Markdown. No JSON, no surrounding code fence.
""",
    ),
```

Lines 128 to 144, `notes`. This is the odd one out and the one to point at when explaining the `schema=None` mode. No schema, so the free-text path. The floor is 200 characters of body. The last line of the prompt, "Output pure Markdown. No JSON, no surrounding code fence", is there because this response is not passed through the JSON-schema machinery at all, so nothing downstream would strip a fence for it. Rule 1, "Open with a single `#` title", is load-bearing in a way that is easy to miss: `_as_notes` at line 350 reads the title back out of that first line.

Lines 145 to 158, `study_guide`: `StudyGuideModel`, count `objectives`, floor 3. Rule 1, ordering by dependency, is the reason this is a different artifact from notes rather than a reformatting of it.

Lines 159 to 174, `cheatsheet`: `CheatSheetModel`, count `sections`, floor 2. Rule 1 caps entries at 120 characters, which is the constraint that makes it a cheat sheet rather than short notes.

```python
    "mindmap": GeneratorSpec(
        schema=MindMapModel,
        prompt="""
...
2. Produce 4-7 branches, each with 2-4 leaves. The tree is exactly three levels
   deep: root, branch, leaf. Do not nest further.
""",
    ),
```

Lines 175 to 188, `mindmap`. Schema only, no counting fields. The depth rule in the prompt is backed up by the schema itself: `MindMapModel` is built from three distinct classes, `MindMapRoot`, `MindMapBranch` and `MindMapLeaf` (`backend/models/artifacts.py:108` to `133`), rather than one self-referencing `Node` type. The docstring there gives the reason: "a recursive schema gives the model no bound to stop at". A self-referencing schema also cannot be inlined by `strict_schema` (`backend/llm/schema.py:15`), which resolves every `$ref` by substitution and would not terminate on a cycle. So the three-class shape is both a prompt-engineering choice and a hard requirement of the structured-output pipeline.

**Worth knowing.** The keys are `study_guide` with an underscore but `cheatsheet` and `mindmap` without. There is no rule; it is historical. It matters only because these strings must match exactly across `SPECS`, `ARTIFACT_MODELS`, the flattener in `sources.py:41`, and the frontend. A mismatch shows up as "Unknown artifact type" at line 228.

Note also what is *not* in `SPECS`: `exam`. Seven entries here plus the exam handled separately makes eight types.

### The exam constants, lines 191 to 207

```python
EXAM_SPEC_PROMPT = """
You are an academic assessment designer.

Define the assessment contract for the provided material: the discipline, the
style of exam that suits it, the cognitive targets worth testing, and how
partial credit should be awarded.
"""
```

Lines 191 to 197. The exam is generated in two stages and this is stage one. Rather than asking for questions directly, the model is first asked what kind of exam this material deserves. The result is an `ExamSpec` (`backend/models/artifacts.py:10`) with a `discipline` constrained to a `Literal` of six values, an exam style, cognitive targets, a grading philosophy and a tone. That contract is then quoted back into every question prompt, which is what stops the multiple-choice section and the problem set from reading as though they were written by two different people.

```python
DEFAULT_EXAM_SPEC = ExamSpec(
    discipline="General",
    exam_style="Standard academic",
    cognitive_targets=["Recall", "Understanding", "Application"],
    grading_philosophy="Award partial credit for correct reasoning.",
    instructions_tone="Formal",
)
```

Lines 199 to 205. A hard-coded fallback contract, used at line 300 when stage one fails. The reasoning: stage one is a small nice-to-have call, and losing it should not lose the exam. A generic contract still gives the three batches something consistent to write against.

```python
EXAM_BATCHES = (("MCQ", 15, 3), ("Short Answer", 5, 5), ("Problem Set", 3, 10))
```

Line 207. A tuple of `(kind, count, points_each)`. Three details worth noticing. The `kind` strings match the `Literal` on `ExamQuestion.type` exactly (`backend/models/artifacts.py:23`), so a typo here would fail schema validation on every question. The counts total 23 questions, comfortably above the floor of 10, so the exam survives one batch failing. And the points work out to 45 plus 25 plus 30, which is 100 — that is not a coincidence, and it is printed on the cover page of the PDF at `exam_pdf.py:113`.

Because it is a module-level tuple, adding a fourth section to the exam is one more triple here. The batching code below iterates it and does not care how long it is.

### ArtifactGenerator, lines 210 to 240

```python
class ArtifactGenerator:
    """Generates each artifact type from its spec."""

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()
```

Lines 210 to 214. Constructor injection with a default. Pass a provider and it uses that; pass nothing and it takes the shared one. This one line is what makes the class testable: every test in `TestProviderSubstitution` and `TestGenerationContract` in `test_seams.py` works by passing a fake provider. The `or` idiom means `None` and a falsy provider behave the same, which is fine because a provider object is never falsy.

```python
    async def generate(
        self,
        target_type: str,
        core: KnowledgeCore,
        instructions: Optional[str] = None,
    ) -> BaseModel:
        """Produce and validate an artifact of `target_type`."""
        if target_type == "exam":
            return await self._exam(core, instructions)
```

Lines 216 to 224. The single public entry point. `instructions` is the free-text box the user types into on the generator node; it is optional. The return type is the base `BaseModel` because which concrete model comes back depends on the string argument, and Python's type system will not express that without overloads.

Lines 223 and 224 are the one special case. Exam is not in `SPECS` because a `GeneratorSpec` describes one prompt producing one schema, and an exam is two stages and four model calls. Rather than contort the spec to cover it, exam gets its own branch. That is an honest answer to "why isn't your open/closed design fully open/closed": it is open for anything that fits the shape of one prompt, one schema, one validation rule, and the exam does not fit that shape.

```python
        spec = SPECS.get(target_type)
        if spec is None:
            raise GenerationError(f"Unknown artifact type: {target_type}")
```

Lines 226 to 228. Dictionary lookup instead of a chain of `if` statements. This is the moment the open/closed claim actually pays off: this function has no knowledge of any specific artifact type. Note that the handler already checked the type against `GENERATED_TYPES` at `generate_handler.py:53`, so this is a second line of defence for callers that come in another way, such as the refine handler.

```python
        logger.info("Generating %s", target_type)
        prompt = self._steer(spec.prompt, instructions)
        context = core.model_dump_json()
```

Lines 230 to 232. The logging call uses `%s` lazy formatting rather than an f-string, so the interpolation is skipped when the log level suppresses the line. Line 231 folds the user's instructions into the prompt. Line 232 is the sentence to be able to say out loud: **the source material handed to the model is the knowledge core serialised to JSON**, not the transcript, not the PDF text. That is the whole architecture in one line.

```python
        model = (
            await self._provider.complete_as(prompt, spec.schema, context=context)
            if spec.schema
            else self._as_notes(await self._provider.complete(prompt, context=context), core)
        )
        spec.validate(model)
        return model
```

Lines 234 to 240. A conditional expression choosing between the two provider methods. Python evaluates conditional expressions lazily, so exactly one of those two `await`s ever runs — worth saying if asked, because at a glance it looks like both branches are awaited.

The structured branch calls `complete_as`, which builds a strict JSON Schema from the Pydantic model, sends it in `response_format`, and validates the reply back into the model (`backend/llm/openrouter.py:80`). The free-text branch calls `complete` and passes the raw string through `_as_notes` to wrap it in a `NotesModel`. Then line 239 applies the usefulness check, and line 240 returns a fully typed, twice-validated object. Nothing downstream ever touches raw model output.

### _exam, lines 242 to 291

```python
    async def _exam(self, core: KnowledgeCore, instructions: Optional[str]) -> FinalExamModel:
        """
        Build an exam in two stages.

        The model writes an assessment contract first, then writes each question
        batch against it. The batches are independent, so they run concurrently.

        A batch that fails is dropped and the exam is built from the rest. A
        batch that was cancelled is not a failure: it means teardown, so the
        cancellation is re-raised rather than absorbed into a partial exam.

        The classification is on `BaseException` because that is what `gather`
        captures, and `CancelledError` is one: an `Exception` check lets a
        cancelled batch reach `extend` as if it were a list of questions.
        """
```

Lines 242 to 256. This docstring is unusually long because it is carrying the record of a real bug. Take the last paragraph slowly, because it is the most likely deep question in this file.

`asyncio.CancelledError` inherits from `BaseException`, not from `Exception`. That was changed in Python 3.8 precisely so that a blanket `except Exception` would not swallow cancellation. When you call `asyncio.gather(..., return_exceptions=True)`, a child that was cancelled comes back in the results list as a `CancelledError` *instance*, sitting alongside the successful results. If you then classify results with `isinstance(result, Exception)`, a cancelled child fails that test and is treated as a success. This same mistake existed in three places in this codebase: here, in `CoreMerger.merge` (`merger.py:100`), and in the chunked knowledge extraction (`backend/pipeline/knowledge.py:119`).

The symptoms differ by site. Here, a `CancelledError` that survived classification would reach `questions.extend(result)` on line 275 and raise `TypeError: 'CancelledError' object is not iterable`. In the extraction path the misclassified object was carried into a `" ".join(...)` over summaries and blew up the same way, with a `TypeError` naming a type that has nothing to do with the data. That is what makes this bug class expensive to diagnose: the exception you see is a `TypeError` in string handling, several frames away from the cancellation that caused it, and by then the original signal is gone.

The fix has two halves, both visible below. First, look for cancellation explicitly and re-raise it. Second, classify remaining failures on `BaseException` rather than `Exception`.

```python
        context = core.model_dump_json(indent=2)
        spec = await self._exam_spec(context, instructions)
```

Lines 257 and 258. Same serialisation as line 232 except pretty-printed. Line 258 is stage one, and it is deliberately sequential: every batch prompt quotes the contract, so nothing can start until it exists. This is the part of exam generation that is *not* parallel, and it is worth being able to say that clearly.

```python
        results = await asyncio.gather(
            *(self._exam_batch(context, spec, kind, count, points, instructions)
              for kind, count, points in EXAM_BATCHES),
            return_exceptions=True,
        )
```

Lines 260 to 264. This is where real concurrency shows up in generation. A generator expression builds three coroutines, one per entry in `EXAM_BATCHES`, and `gather` runs all three at once. Three HTTP requests to the model are genuinely in flight simultaneously; the exam takes roughly as long as its slowest batch instead of the sum of all three.

Two things bound that concurrency. `gather` itself does not limit anything, but the provider holds a semaphore sized by `LLM_MAX_CONCURRENCY`, default 6 (`backend/core/config.py:44`), shared across every in-flight job in the process (`backend/llm/openrouter.py:185`). So three batches will genuinely run in parallel unless other jobs are already using the budget. And because the exam is the only place in generation that fans out, the rest of a generation job is one model call at a time.

`return_exceptions=True` is what makes partial success possible. Without it, the first batch to raise would cancel the gather and lose the other two.

```python
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
```

Lines 266 to 268. The first half of the fix. Before anything is classified as success or failure, scan for cancellation and re-raise it. Cancellation means something outside this function decided this work should stop — the job timeout at `job_runner.py:121`, or the worker pool shutting down at `job_runner.py:250`. Turning that into a "partial exam" would be actively wrong: the user would get a shortened exam and a success status for a job that was actually killed. `test_seams.py:123` pins this behaviour with a provider that raises `CancelledError` for every batch and asserts the whole `generate` call raises it too.

```python
        questions: List[ExamQuestion] = []
        for (kind, _, _), result in zip(EXAM_BATCHES, results):
            if isinstance(result, BaseException):
                logger.warning("Exam batch '%s' failed: %s", kind, result)
                continue
            questions.extend(result)
```

Lines 270 to 275. The second half. `gather` returns results in the order the coroutines were passed, so zipping against `EXAM_BATCHES` recovers which batch each result belongs to, which is what makes the log line name the failing section. The `(kind, _, _)` destructuring throws away the count and points, which are not needed here.

Line 272 checks `BaseException`, not `Exception`. Given the re-raise loop above, cancellation can no longer reach this line, so this is belt and braces — but it is the correct check, and it is the check that makes the code robust if the re-raise loop is ever moved or removed. Line 275 is the line that used to throw the `TypeError`.

```python
        if len(questions) < MIN_EXAM_QUESTIONS:
            raise GenerationError(
                f"Expected at least {MIN_EXAM_QUESTIONS} exam questions, got {len(questions)}"
            )
```

Lines 277 to 280. The same "parses but is not useful" gate that `GeneratorSpec.validate` applies to the other types, written out longhand because the exam does not have a spec. If two of three batches fail, the survivors are unlikely to clear 10 and the job fails honestly rather than shipping a five-question "final exam".

```python
        for number, question in enumerate(questions, start=1):
            question.id = f"Q-{number}"
```

Lines 282 and 283. Renumbering, and this is a direct consequence of batching. Each batch is generated in isolation, so each one numbers its questions from 1 and you end up with three questions called `Q1`. The IDs are printed in the solution key in the PDF (`exam_pdf.py:151`), so collisions would be visible in the output. Renumbering after concatenation is where global identity gets restored. Note it mutates the Pydantic objects in place, which works because these models are not frozen.

```python
        return FinalExamModel(
            title=f"Final exam: {core.title}",
            exam_spec=spec,
            instructions=f"({spec.instructions_tone}) {spec.exam_style}. Answer all questions.",
            rubric=spec.grading_philosophy,
            questions=questions,
        )
```

Lines 285 to 291. Assembly. Note that the contract from stage one is stored on the artifact (`exam_spec=spec`), not just used and discarded, so the frontend and the PDF can both show what the exam was written against. The `instructions` string is composed in code rather than asked for from the model, because it is pure formatting of things already decided.

### _exam_spec, lines 293 to 300

```python
    async def _exam_spec(self, context: str, instructions: Optional[str]) -> ExamSpec:
        try:
            return await self._provider.complete_as(
                self._steer(EXAM_SPEC_PROMPT, instructions), ExamSpec, context=context
            )
        except Exception as error:
            logger.warning("Exam spec generation failed (%s); using the default contract", error)
            return DEFAULT_EXAM_SPEC
```

Stage one, with a fallback. Note the user instructions are steered into this call too, so "make it a maths exam" can influence the contract as well as the questions.

The `except Exception` here is correct and consistent with the story above: it catches model failures but deliberately does *not* catch `CancelledError`, which is a `BaseException` and will propagate straight out of `_exam`. That is the behaviour the test at `test_seams.py:130` depends on — the fake provider returns the default spec for the `ExamSpec` call and cancels everything after, and the test asserts the cancellation escapes.

### _exam_batch, lines 302 to 330

```python
        prompt = self._steer(f"""
You are an examiner working to a fixed assessment contract.

Discipline: {spec.discipline}
Style: {spec.exam_style}
Grading philosophy: {spec.grading_philosophy}
Cognitive targets: {", ".join(spec.cognitive_targets)}

Write EXACTLY {count} questions of type "{kind}", worth {points} points each.
...
""", instructions)
```

Lines 302 to 327. The signature takes the contract plus one triple from `EXAM_BATCHES`. The prompt is the only f-string prompt in the file, because it is the only one whose content depends on runtime values. The contract fields are quoted at the top: this is the mechanism by which three independent model calls produce one coherent exam.

`EXACTLY` in capitals, and then rule 1 repeating it, is prompt engineering that earns its keep — models routinely return "about" the requested number otherwise. Rule 3, "MCQ questions need four plausible options. Other types have none", matches `ExamQuestion.options` being `Optional[List[str]]`, and the PDF renderer keys off exactly that at `exam_pdf.py:131`.

```python
        batch = await self._provider.complete_as(prompt, QuestionBatch, context=context)
        return batch.questions
```

Lines 329 and 330. One structured call, and the unwrap that `QuestionBatch` exists to permit.

**Worth knowing.** Nothing verifies that the batch actually returned `count` questions. The only quantity guard is the total floor at line 277. In practice the exam ends up with 20 to 23 questions rather than exactly 23, and the points on the cover page are summed from what actually arrived (`exam_pdf.py:96`) rather than assumed to be 100, so the printed total stays honest.

### _steer, lines 332 to 341

```python
    @staticmethod
    def _steer(prompt: str, instructions: Optional[str]) -> str:
        """Append the user's request so it takes precedence over the defaults."""
        if not instructions or not instructions.strip():
            return prompt
        return (
            f"{prompt}\n"
            "--- USER INSTRUCTIONS (these take precedence over the rules above) ---\n"
            f"{instructions.strip()}\n"
        )
```

Three decisions in ten lines. The instructions go *after* the built-in rules, because models weight later instructions more heavily. The precedence is also stated in words rather than left implicit, because ordering alone is unreliable when the user's request contradicts a rule — "no multiple choice" against rule 1 of the quiz prompt, for instance. And the delimiter line marks where trusted prompt ends and user text begins, which is a mild prompt-injection defence: it does not stop a determined attacker, but it stops a user's stray text being read as part of the system's own rules.

The empty check on line 335 covers both `None` and whitespace-only strings, so a user who tabs through the box without typing gets the plain prompt rather than a prompt with a dangling empty section. `test_seams.py:89` asserts both the instruction text and the phrase "take precedence" reach the provider.

`@staticmethod` because it touches no instance state. Same for `_as_notes`.

### _as_notes, lines 343 to 351

```python
    @staticmethod
    def _as_notes(body: str, core: KnowledgeCore) -> NotesModel:
        if not body or not body.strip():
            raise GenerationError("The model returned no note text")

        body = body.strip()
        first_line = body.splitlines()[0] if body.splitlines() else ""
        title = first_line[2:].strip() if first_line.startswith("# ") else f"Notes: {core.title}"
        return NotesModel(title=title, body=body)
```

The adapter for the free-text path. Lines 345 and 346 catch an empty response, which the structured path gets for free from Pydantic and this path does not.

Line 349 pulls the title out of the Markdown itself. This is why the notes prompt insists on opening with a single `#` heading: the model has already written a good title, so there is no reason to make a second call to ask for one. `first_line[2:]` strips the `"# "` prefix by length. If the model ignored the instruction, line 350 falls back to `"Notes: "` plus the core's title, so the artifact always has a name. The `core` parameter exists purely for that fallback.

**Worth knowing.** `body.splitlines()` is computed twice on line 349, once for the guard and once for the index. Harmless on a document of this size, and worth mentioning only because it is the kind of thing an interviewer points at to see whether you notice.

---

## backend/services/merger.py

206 lines. This runs only when a generator node has more than one inbound edge on the canvas. One source goes straight through (`generate_handler.py:81`) and never touches this file.

### Constants and prompts, lines 17 to 45

```python
CONCEPTS_PER_SOURCE = 7
FACTS_PER_SOURCE = 7
DIRECT_MERGE_LIMIT = 3
```

Lines 17 to 19. The first two are the compression budget: however large a source is, it is reduced to at most seven concepts and seven facts. The third is the fan-in threshold — up to three summaries go into the model in one call; beyond that they are reduced pairwise first.

```python
SUMMARISE_PROMPT = f"""
You are compressing one source into a fixed-size summary for cross-source merging.

Produce at most {CONCEPTS_PER_SOURCE} key concepts, at most {FACTS_PER_SOURCE}
key facts, and a two or three sentence summary.
...
3. Preserve the source's own terminology, which matters when merging.
4. Invent nothing.
"""
```

Lines 21 to 32. An f-string at module level, so the budget in the prompt and the budget in `_structural_summary` can never drift apart. Rule 3 is subtle and worth understanding: the merge step needs to be able to notice that two sources are talking about the same thing under different names, and it can only do that if the summariser has not already normalised the vocabulary away.

```python
SYNTHESISE_PROMPT = """
You are synthesising several sources into one study context.

Rules:
1. Merge concepts that are the same idea under different names, keeping both
   namings when the wording differs meaningfully.
2. If two sources disagree on a fact, keep BOTH and record the disagreement in
   conflict_notes, naming the sources. Never silently pick a winner.
3. The unified summary must reflect every source, not just the longest one.
4. Each source is authoritative within its own scope. Invent nothing.
5. Plain text only: no Markdown, no LaTeX.
"""
```

Lines 34 to 45, and rule 2 is the conflict policy. It is the answer to "what happens when your sources contradict each other". The system does not resolve the contradiction, because it has no basis on which to resolve it: a textbook and a lecture disagreeing about a definition is not something a merge step can adjudicate. It records the disagreement in a named field instead, and `generate_handler.py:87` logs it. Rule 3 exists because the failure mode without it is that the longest source dominates the merged summary. Rule 5 is because this text is context for a later prompt, not output for a human, so markup is noise.

### The two models, lines 48 to 67

```python
class CoreSummary(BaseModel):
    source_title: str
    key_concepts: List[str]
    key_facts: List[str]
    summary: str
```

Lines 48 to 54. One source compressed. This is the unit that the map step produces and the reduce step consumes.

```python
class CombinedContext(BaseModel):
    source_count: int
    source_titles: List[str]
    unified_summary: str
    all_concepts: List[str]
    all_facts: List[str]
    conflict_notes: Optional[str] = Field(
        default=None, description="Contradictions between sources, labelled not resolved"
    )
```

Lines 57 to 67. What several sources say together. `conflict_notes` is optional and defaults to `None`, so "no conflicts" is a normal outcome rather than an empty-string special case. The `description` is not decoration: `strict_schema` (`backend/llm/schema.py:15`) carries Pydantic field descriptions into the JSON Schema sent to the model, so that sentence is read by the model as part of its instructions.

### The class docstring, lines 70 to 78

```python
class CoreMerger:
    """
    Compresses each source, then synthesises the summaries.

    Concatenating full sources does not scale: the combined text overruns the
    context window and the model attends mostly to whichever came first. Beyond
    a few sources the synthesis runs pairwise up a tree, so the prompt stays a
    bounded size however many sources are wired in.
    """
```

This is the "why not just concatenate the transcripts" answer, and it has two halves. The first is the obvious one: five hour-long lectures do not fit in a context window. The second is the interesting one: even when they do fit, attention is not uniform across a long prompt, so a naive concatenation quietly privileges whichever source happens to be first. Compressing each source to the same fixed budget first makes the sources structurally equal before the model ever compares them.

There is a third argument that is worth having ready. Concatenation cannot detect conflicts, because it never puts the two claims side by side in a form the model is asked to compare. The map/reduce shape does, which is what makes `conflict_notes` possible at all.

### merge, the map/reduce, lines 83 to 116

```python
    async def merge(self, cores: List[KnowledgeCore]) -> CombinedContext:
        """
        Reduce many knowledge cores to one context.

        `summarise` absorbs its own failures, so the only thing `gather` can
        hand back here is a cancelled child. Falling through to a structural
        summary would turn that teardown into a plausible-looking result, so it
        is re-raised instead. Cancelling the whole `merge` already propagates on
        its own; this covers a child cancelled by itself, which is what a
        per-call timeout inside `summarise` would produce.
        """
```

Lines 83 to 93. The second of the three cancellation sites, with the reasoning written out. The extra precision here is worth reading: cancelling `merge` itself would propagate anyway, because awaiting a cancelled gather re-raises. The case this guards is a *child* being cancelled independently, which is what a per-call timeout inside `summarise` would produce. Without the guard, that child's cancellation would be quietly replaced by a structural summary and the job would return a plausible-looking result built from a torn-down call.

```python
        if not cores:
            raise ValueError("merge needs at least one knowledge core")
```

Lines 94 and 95. A precondition, not a fallback. Merging nothing has no sensible answer.

```python
        results = await asyncio.gather(
            *(self.summarise(core) for core in cores), return_exceptions=True
        )
```

Lines 97 to 99. **The map step.** Every source is compressed at the same time, one model call each. Same `gather` pattern as the exam, same reason: these calls do not depend on each other.

```python
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
```

Lines 100 to 102. Same fix, same reason as `generators.py:266`.

```python
        summaries = [
            result if isinstance(result, CoreSummary) else self._structural_summary(core)
            for core, result in zip(cores, results)
        ]
```

Lines 104 to 107. Note the shape of this test. Rather than asking "is this an exception", which is the question that got the codebase into trouble, it asks "is this the type I wanted". Anything else, whatever it is, falls back to the deterministic structural summary. That positive-type check is the pattern to point at if asked how you would avoid the `CancelledError` class of bug in general: classify on success, not on failure.

`zip(cores, results)` works because `gather` preserves input order, so each result lines up with the core that produced it — necessary here because the fallback needs the original core.

```python
        level = summaries
        while len(level) > DIRECT_MERGE_LIMIT:
            pairs = [level[index : index + 2] for index in range(0, len(level), 2)]
            logger.info("Reducing %d summaries into %d", len(level), len(pairs))
            contexts = await asyncio.gather(*(self.synthesise(pair) for pair in pairs))
            level = [self._as_summary(context) for context in contexts]

        return await self.synthesise(level)
```

Lines 109 to 116. **The reduce step**, and it is a tree, not a fold.

While there are more than three summaries at the current level, line 111 chops them into adjacent pairs. Python's slicing handles an odd tail without special-casing: with five summaries you get `[0:2]`, `[2:4]`, `[4:6]`, and the last slice yields a single-element list rather than an error. That single-element list is handled at line 135, which returns a passthrough without calling the model.

Line 113 synthesises every pair concurrently, so each level of the tree costs one round trip rather than one per pair. Line 114 converts each `CombinedContext` back down to a `CoreSummary` so the next level up has a uniform input type. Line 116 does the final synthesis once three or fewer remain.

The property this buys: the prompt sent to any single `synthesise` call contains at most three summaries, each capped at seven concepts and seven facts. That is bounded regardless of whether the user wired in three sources or thirty. The number of levels grows as log₂(n), so thirty sources is five rounds of calls, not one impossible one.

Note that the inner `gather` on line 113 has no `return_exceptions`. That is deliberate and safe: `synthesise` catches its own `Exception`s at line 152, so the only thing that can escape it is a `BaseException`, and a cancellation escaping the reduce loop is exactly what should happen.

**Worth knowing.** Two costs of the tree, both fair game for a question. First, `_as_summary` truncates back to seven concepts and seven facts at every level, so a sixteen-source merge discards a lot on the way up. That is the price of a bounded prompt, and it is the honest trade: some loss versus not fitting at all. Second, `_as_summary` does not carry `conflict_notes` upward, so a conflict detected between sources 1 and 2 at the bottom level does not appear in the final output. In practice the tree only engages beyond three sources, which is rare on this canvas, but it is a real gap and better to name it than be caught by it.

### summarise, lines 118 to 128

```python
    async def summarise(self, core: KnowledgeCore) -> CoreSummary:
        """Compress one core to a bounded summary."""
        try:
            summary = await self._provider.complete_as(
                SUMMARISE_PROMPT, CoreSummary, context=core.model_dump_json()
            )
            summary.source_title = core.title or summary.source_title
            return summary
        except Exception as error:
            logger.warning("Summarising '%s' failed (%s); using its own fields", core.title, error)
            return self._structural_summary(core)
```

The map function. One structured call per source.

Line 124 is the interesting one. The model is asked for a `source_title` as part of the schema, and then that answer is overwritten with the core's actual title whenever there is one. The reasoning: identity is a fact the system already knows, and letting the model rename a source would break the conflict notes, which name sources by title. `core.title or summary.source_title` keeps the model's answer only as a fallback for an untitled core.

Line 126 catches `Exception`, so once again cancellation passes straight through, which is what the guard in `merge` is written to receive.

### synthesise, lines 130 to 154

```python
        if not summaries:
            raise ValueError("synthesise needs at least one summary")

        if len(summaries) == 1:
            only = summaries[0]
            return CombinedContext(
                source_count=1,
                source_titles=[only.source_title],
                unified_summary=only.summary,
                all_concepts=only.key_concepts,
                all_facts=only.key_facts,
            )
```

Lines 133 to 143. The single-summary passthrough, which is what makes the odd tail in the pairing loop safe. It saves a model call, and more importantly it avoids asking a model to "synthesise" one thing, which invites it to paraphrase and drift.

```python
        try:
            merged = await self._provider.complete_as(
                SYNTHESISE_PROMPT, CombinedContext, context=self._render(summaries)
            )
            merged.source_count = len(summaries)
            merged.source_titles = [summary.source_title for summary in summaries]
            return merged
```

Lines 145 to 151. The real reduce. Lines 149 and 150 are the same distrust as line 124, applied to bookkeeping: `source_count` and `source_titles` are in the schema so the model has them in view while writing, but the values it returns are thrown away and replaced with the truth. The model is trusted for judgement, not for counting.

```python
        except Exception as error:
            logger.warning("Synthesis failed (%s); falling back to a structural merge", error)
            return self._structural_merge(summaries)
```

Lines 152 to 154. Degrade rather than fail.

### The deterministic helpers, lines 156 to 205

```python
    @staticmethod
    def _render(summaries: List[CoreSummary]) -> str:
        return "\n\n".join(
            f"### Source {index + 1}: {summary.source_title}\n"
            f"Summary: {summary.summary}\n"
            f"Concepts: {', '.join(summary.key_concepts)}\n"
            "Facts:\n" + "\n".join(f"- {fact}" for fact in summary.key_facts)
            for index, summary in enumerate(summaries)
        )
```

Lines 156 to 164. Formats the summaries as labelled text blocks rather than JSON. Two reasons: it is markedly fewer tokens than JSON for the same content, and the explicit `### Source N: title` header is what lets rule 2 of the prompt name a source when it records a conflict.

```python
    @staticmethod
    def _structural_summary(core: KnowledgeCore) -> CoreSummary:
        ranked = sorted(core.concepts, key=lambda concept: -(concept.importance_score or 0))
        return CoreSummary(
            source_title=core.title,
            key_concepts=[concept.name for concept in ranked[:CONCEPTS_PER_SOURCE]],
            key_facts=[fact.fact for fact in core.key_facts[:FACTS_PER_SOURCE]],
            summary=(core.summary or "Summary unavailable.")[:800],
        )
```

Lines 166 to 174. The no-model fallback, used whenever a summarise call fails. It leans on a field the extraction stage already produced: `Concept.importance_score`, a 1-to-10 relevance rating (`backend/pipeline/knowledge.py:39`). Sorting on the negated score gives descending order without `reverse=True`; the `or 0` guards a `None`. Facts are taken in document order rather than ranked, because `KeyFact` has no score to rank on. The 800-character clamp on the summary keeps this fallback within roughly the same budget as a real summary, so a mixed batch of real and fallback summaries stays balanced.

```python
    @staticmethod
    def _structural_merge(summaries: List[CoreSummary]) -> CombinedContext:
        def union(values: List[str]) -> List[str]:
            seen: set = set()
            result = []
            for value in values:
                identity = value.strip().lower()
                if identity and identity not in seen:
                    seen.add(identity)
                    result.append(value.strip())
            return result
```

Lines 176 to 186. A nested helper doing order-preserving, case-insensitive deduplication. The trick is that the comparison key is lowercased and stripped, but what gets appended is the original stripped value — so "Raft Consensus" and "raft consensus" collapse to one entry, and the entry keeps its original capitalisation. The empty check on line 183 drops blanks. Compare with `KnowledgeExtractor.merge` at `backend/pipeline/knowledge.py:143`, which uses exactly the same idiom over objects with a key function; this is the string version of it.

```python
        return CombinedContext(
            source_count=len(summaries),
            source_titles=[summary.source_title for summary in summaries],
            unified_summary=" ".join(
                f"From {summary.source_title}: {summary.summary}" for summary in summaries
            )[:4000],
            all_concepts=union([c for s in summaries for c in s.key_concepts]),
            all_facts=union([f for s in summaries for f in s.key_facts]),
        )
```

Lines 188 to 196. The summaries are concatenated with a source label on each, capped at 4000 characters, and the concepts and facts are unioned. Note the one thing this cannot produce: `conflict_notes`. Detecting that two sources disagree requires reading both and understanding them, which is precisely the work the model was doing. So the fallback is honest about being a union rather than a synthesis, and it leaves the field `None` rather than guessing.

```python
    @staticmethod
    def _as_summary(context: CombinedContext) -> CoreSummary:
        return CoreSummary(
            source_title=f"Merged: {', '.join(context.source_titles)}",
            key_concepts=context.all_concepts[:CONCEPTS_PER_SOURCE],
            key_facts=context.all_facts[:FACTS_PER_SOURCE],
            summary=context.unified_summary,
        )
```

Lines 198 to 205. The adapter that closes the reduce loop, turning a level's output back into a level's input. The two slices on lines 202 and 203 are the mechanism that keeps the prompt bounded as the tree grows — and, as noted above, the mechanism that loses detail on the way up. The composed title, "Merged: A, B", is what makes the final `source_titles` readable when the tree ran.

---

## backend/services/exports/\_\_init\_\_.py

161 lines. This turns a validated artifact model into a file on disk and a row's worth of metadata. Everything here is synchronous.

```python
MIME_TYPES = {
    "pdf": "application/pdf",
    "tex": "application/x-tex",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "md": "text/markdown",
}
```

Lines 20 to 25. Extension to MIME type. `tex` is in here because the exam export deliberately falls back to shipping the LaTeX source when `pdflatex` is not installed, and that fallback is only useful if the download is labelled correctly. The pptx MIME type is that long because that is genuinely what the OOXML presentation type string is.

```python
MARKDOWN_TYPES = frozenset({"notes", "study_guide", "cheatsheet"})
```

Line 27. The three types whose natural file form is a Markdown document. `frozenset` for a constant lookup set. Quiz, flashcards, mindmap and exam are not here — the first three have no file form at all and are viewed in the app, and exam has its own PDF path.

```python
EXAM_ARTEFACTS = (".pdf", ".tex", ".aux", ".log")
```

Line 29. Every suffix a `pdflatex` run leaves behind next to the source. Used at line 104 for cleanup.

```python
@dataclass(frozen=True)
class Export:
    """Where a rendered file lives and what it is."""

    format: str
    storage_key: str
    mime_type: str
    size_bytes: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "storage_path": self.storage_key,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }
```

Lines 32 to 47. A small immutable value object describing a rendered file, plus its serialisation. Notice the rename in `as_dict`: the field is `storage_key` in Python and `storage_path` in the JSON. The dict shape is what gets written into `content["binary"]` (`generate_handler.py:122`) and read back at `api/routes/artifacts.py:101`, so it is a stored wire format and cannot be changed without a migration; the Python name is free to be clearer.

```python
class ExportService:
    """
    Renders an artifact to its natural file format, when it has one.

    Rendering never fails a job: an artifact is defined by its content and the
    file is a convenience, so a missing LaTeX install costs the download rather
    than the whole generation.
    """
```

Lines 50 to 57. The policy statement, and it is worth being able to defend. A user waited a minute or two for the model to write an exam. If `pdflatex` is absent on the box, the right outcome is an exam they can read in the app without a PDF button, not a failed job. Everything in `export` below follows from that sentence.

```python
    def __init__(
        self,
        store: Optional[FileStore] = None,
        exam_renderer: Optional[ExamPdfRenderer] = None,
        slides_renderer: Optional[SlidesPptxRenderer] = None,
    ) -> None:
        self._store = store or get_file_store()
        self._exam = exam_renderer or ExamPdfRenderer(Path(tempfile.gettempdir()))
        self._slides = slides_renderer or SlidesPptxRenderer()
```

Lines 59 to 67. The same optional-injection pattern as the generator, applied to three collaborators. The exam renderer is rooted at the system temp directory because LaTeX compilation is a multi-file affair that needs a real scratch directory; the finished PDF is copied out into the store and the scratch files are deleted.

```python
    def export(
        self,
        artifact_type: str,
        model: BaseModel,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
    ) -> Optional[Export]:
        """Render `model` and return where it was stored, or None if it has no file form."""
        try:
            if artifact_type == "exam":
                return self._export_exam(model, project_id, artifact_id)
            if artifact_type == "slides":
                return self._export_slides(model, project_id, artifact_id)
            if artifact_type in MARKDOWN_TYPES:
                return self._export_markdown(model, project_id, artifact_id)
        except Exception as error:
            logger.warning("Export failed for %s (%s); keeping the artifact", artifact_type, error)
        return None
```

Lines 69 to 86. The dispatcher. Three branches and a fall-through to `None` for the four types with no file form.

Be ready for the obvious question: why is this an if-chain when `generators.py` uses a lookup table? The honest answer is that a table buys nothing here. Each branch is a genuinely different piece of code with a different signature and different resource handling, whereas the generator branches were identical code differing only in data. A dict of `{type: method}` would be the same three lines wearing a hat.

`Optional[Export]` as the return type is what encodes "this type has no file", and both callers check it before writing `content["binary"]`.

The `try/except` on lines 84 and 85 is the policy from the docstring, implemented. Every failure below — a missing LaTeX binary, a malformed deck, a full disk — becomes a warning and a `None`, and the artifact is saved regardless.

```python
    def _export_exam(self, exam, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Optional[Export]:
        """
        Render into the scratch directory and clear every intermediate afterwards.

        The cleanup covers rendering itself, not just storage: a LaTeX run that
        dies partway still leaves its source and logs behind, and nothing else
        ever revisits that directory.
        """
        stem = self._exam.output_dir / f"exam_{artifact_id}"

        try:
            rendered = self._exam.render(exam, stem.name)
            if rendered is None:
                return None
            return self._store_file(rendered, project_id, artifact_id, rendered.suffix.lstrip("."))
        finally:
            self._cleanup(*(stem.with_suffix(suffix) for suffix in EXAM_ARTEFACTS))
```

Lines 88 to 104. The docstring records what went wrong: temp files accumulated. Every exam left a `.tex`, an `.aux` and a `.log` in the system temp directory, and a failed compile left them too. Nothing ever cleaned up, because nothing else knows those files exist.

The `try/finally` is the fix, and the placement matters. `_store_file` runs inside the `try`, so the finished PDF is copied into the `FileStore` *before* the cleanup deletes the scratch copy. The `finally` runs on every path out, including the exception path, which is the case the docstring calls out.

Line 96 builds the full path but line 99 passes `stem.name` — just the filename — because the renderer joins it with its own `output_dir`. Line 102 reads the extension off whatever came back rather than assuming `pdf`, because `render` returns a `.tex` path when LaTeX is unavailable. That is the one line that makes the degradation actually work end to end: the stored key, the extension and the MIME type all follow the file that was really produced.

```python
    def _export_slides(self, deck, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Export:
        with tempfile.TemporaryDirectory() as workspace:
            path = self._slides.render(deck, Path(workspace) / f"{artifact_id}.pptx")
            return self._store_file(path, project_id, artifact_id, "pptx")
```

Lines 106 to 109. A different and simpler discipline for a simpler job. `TemporaryDirectory` as a context manager deletes the whole directory on exit, exception or not, so no explicit cleanup list is needed. It works here and not for the exam because python-pptx writes exactly one file, whereas LaTeX writes four with names it chooses itself.

```python
    def _export_markdown(self, model, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Optional[Export]:
        body = self._to_markdown(model)
        if not body:
            return None

        key = f"{project_id}/exports/{artifact_id}.md"
        self._store.put_bytes(body.encode("utf-8"), key)
        return Export("md", key, MIME_TYPES["md"], self._store.size_of(key))
```

Lines 111 to 118. No temp file at all: the Markdown is produced as a string and written straight into the store as bytes. Explicit `.encode("utf-8")` rather than relying on a platform default, which matters because these documents are full of LaTeX and occasionally non-ASCII terminology.

```python
    def _store_file(
        self,
        path: Path,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        extension: str,
    ) -> Export:
        key = f"{project_id}/exports/{artifact_id}.{extension}"
        self._store.put(str(path), key)
        size = self._store.size_of(key)
        logger.info("Exported %s (%d bytes)", key, size)
        return Export(extension, key, MIME_TYPES.get(extension, "application/octet-stream"), size)
```

Lines 120 to 131. The shared tail for the two file-producing paths. The key convention `{project_id}/exports/{artifact_id}.{ext}` is worth stating: it is project-scoped, so the ownership check at `api/routes/artifacts.py` can compare the project prefix, and it is artifact-scoped, so two exports never collide. `FileStore.resolve` refuses any key that escapes the store root (`services/files.py:82`), which is what stops a crafted key becoming a path traversal.

Line 131 defaults to `application/octet-stream` for an unknown extension, which makes the browser download rather than try to render something it does not understand.

```python
    @staticmethod
    def _to_markdown(model: BaseModel) -> Optional[str]:
        data = model.model_dump()

        if data.get("body"):
            parts = [str(data["body"])]
            if data.get("checklist"):
                parts.append("\n## Self-check\n")
                parts.extend(f"- [ ] {item}" for item in data["checklist"])
            return "\n".join(parts)
```

Lines 133 to 142. Dispatch on structure rather than on type. Both `NotesModel` and `StudyGuideModel` have a `body` field, so both take this branch; the study guide additionally has a `checklist`, which is appended as GitHub-flavoured task-list items so it renders as real tick boxes. Notes have no checklist, so the block is skipped. One branch covers two types without either being named.

```python
        if data.get("sections"):
            lines = [f"# {data.get('title', 'Cheat sheet')}\n"]
            for section in data["sections"]:
                lines.append(f"## {section.get('heading', '')}\n")
                lines.extend(f"- {entry}" for entry in section.get("entries", []))
                lines.append("")
            return "\n".join(lines)

        return None
```

Lines 144 to 152. The cheat sheet branch, which has `sections` rather than `body`. Everything is read with `.get` and a default because `model_dump()` returns plain dicts and this code is deliberately not type-aware. `return None` at line 152 means "this model has no Markdown form", which `_export_markdown` turns into no export at all.

```python
    @staticmethod
    def _cleanup(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove %s", path)
```

Lines 154 to 160. Best-effort deletion. `missing_ok=True` means a file that was never created is not an error, which matters because `EXAM_ARTEFACTS` lists four suffixes and a failed compile produces fewer. The `OSError` catch handles a permissions or locking problem, logged at debug level because a leftover temp file is not something anyone needs woken up for. Crucially this never raises, so cleanup running in a `finally` block can never mask the real exception.

**Worth knowing.** `export` is synchronous and it is called from `bundle`, which is called from an `async def run`. The `pdflatex` subprocess can take up to 120 seconds (`exam_pdf.py:19`) and it runs on the event loop thread, blocking every other worker task in the process for its duration. That is a real gap in the "async throughout" story: generation is fully async, export is not. The right fix is `asyncio.to_thread` around the export call, exactly as the audio path already does at `backend/llm/openrouter.py:95`. Say it as a known limitation rather than waiting to be shown it.

The exports themselves are verified end to end: a 145 KB PDF, a 64 KB PPTX and a 3 KB Markdown file were all downloaded through signed links. That verification was manual — there are no unit tests over these three files, which is the other honest thing to say if asked about test coverage here.

---

## backend/services/exports/exam_pdf.py

155 lines. This builds a LaTeX document with PyLaTeX and shells out to `pdflatex`.

```python
from pylatex import Document, Enumerate, Itemize, Package, Section
from pylatex.utils import NoEscape
```

Lines 11 and 12. PyLaTeX is a document-object-model library: you build a tree of Python objects and it emits `.tex` source. It does not compile anything itself beyond calling the system binary. `NoEscape` is a string subclass meaning "this is already LaTeX, pass it through verbatim", and it is used on essentially every line of this file.

```python
ANSWER_SPACE = {"Short Answer": "4cm", "Problem Set": "8cm"}
COMPILE_TIMEOUT_SECONDS = 120
```

Lines 18 and 19. How much blank vertical space to leave under each question type for a student to write in. Multiple choice is absent from the dict because it gets a printed option list instead of blank space. The keys match the `Literal` on `ExamQuestion.type` exactly.

```python
class ExamPdfRenderer:
    """
    Produces an exam booklet with a cover page, questions and a solution key.

    Question text is passed through untouched because the model writes LaTeX for
    mathematics, and escaping it would break every formula.
    """
```

Lines 22 to 28. The central decision of the file, stated up front. Every generation prompt asks for LaTeX mathematics, so question text arrives containing things like `$O(n \log n)$`. PyLaTeX's default behaviour is to escape special characters, which would turn that into a literal `$O(n \log n)$` on the page instead of typeset mathematics. So the renderer opts out of escaping everywhere.

**Worth knowing**, and this is the probe an interviewer is most likely to find here. Opting out of escaping means model output is injected into a LaTeX document unescaped. Two consequences. The mild one: an unbalanced `$` or a stray backslash breaks the compile — handled, because `_compile` returns `None` and `render` falls back to shipping the `.tex`. The serious one: LaTeX is a programming language with file access. `\input` can read files and, with `-shell-escape`, `\write18` can execute commands. Shell escape is off by default and this code does not enable it, so the realistic exposure is a broken build rather than code execution. The right answer is that the trade is knowingly made — you cannot have both typeset mathematics and full escaping — and the mitigations are that shell escape stays off, the compile is time-limited, and the input comes from your own model rather than directly from a user.

```python
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def pdflatex_available() -> bool:
        return which("pdflatex") is not None
```

Lines 30 to 36. The constructor normalises to a `Path` and ensures the directory exists. `shutil.which` is the portable "is this binary on the PATH" check, better than trying to run it and catching the error.

```python
    def render(self, exam: FinalExamModel, filename: str) -> Optional[Path]:
        """Write the exam and return the PDF path, or the .tex path if LaTeX is absent."""
        document = self._build(exam)
        stem = self.output_dir / filename

        document.generate_tex(str(stem))
        tex_path = stem.with_suffix(".tex")

        if not self.pdflatex_available():
            logger.info("pdflatex is not installed; keeping the LaTeX source only")
            return tex_path

        pdf_path = self._compile(tex_path)
        return pdf_path or tex_path
```

Lines 38 to 51. Note the ordering: the `.tex` is written first, unconditionally, and only then does the code consider compiling. That is what makes the fallback free — the source already exists, so returning it costs nothing. `generate_tex` takes a path without an extension and appends `.tex` itself, which is why line 44 reconstructs the path with `with_suffix`.

Line 51, `return pdf_path or tex_path`, is the whole degradation policy in five words: a PDF if we got one, otherwise the source. Combined with `_export_exam` reading the extension off the returned path, the user always gets a download button, sometimes labelled `.tex`.

```python
    def _compile(self, tex_path: Path) -> Optional[Path]:
        command = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory", str(self.output_dir),
            str(tex_path),
        ]
```

Lines 53 to 59. `-interaction=nonstopmode` is essential: by default `pdflatex` stops at the first error and waits at an interactive prompt, which in a background worker means hanging forever. In nonstopmode it logs the error and carries on, and often still produces a usable PDF. `-output-directory` keeps the by-products in the scratch directory rather than the process's working directory. The command is a list, not a string, so there is no shell involved and no quoting to get wrong.

```python
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=COMPILE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error("pdflatex timed out compiling %s", tex_path.name)
            return None
```

Lines 61 to 70. Both streams are captured rather than inherited, so LaTeX's very chatty output does not end up interleaved in the application log. The timeout is the second reason this is safe to run unattended: a pathological document can put `pdflatex` into a very long or non-terminating run, and without a timeout that is a stuck worker. On timeout the function returns `None` and the caller falls back to the `.tex`.

```python
        pdf_path = tex_path.with_suffix(".pdf")
        if pdf_path.exists():
            return pdf_path
```

Lines 72 to 74. Success is judged by whether a PDF exists, not by the exit code. That is the correct check for LaTeX specifically: in nonstopmode it frequently exits non-zero over recoverable errors while still producing a perfectly readable document. Trusting the return code here would throw away good PDFs.

```python
        logger.error(
            "pdflatex produced no PDF (exit %d): %s",
            result.returncode,
            result.stdout.decode("utf-8", errors="replace")[-400:],
        )
        return None
```

Lines 76 to 81. When there really is no PDF, log the exit code and the last 400 characters of **stdout**, not stderr — LaTeX writes its errors to stdout, and the useful part is at the end, which is why it is the tail rather than the head. `errors="replace"` stops a decode error inside the error handler, which is the sort of thing that turns a diagnosable failure into a mystery.

```python
    def _build(self, exam: FinalExamModel) -> Document:
        document = Document(documentclass="article", document_options=["11pt"])
        for package in ("geometry", "amsmath", "amssymb", "titlesec"):
            options = ["margin=1in"] if package == "geometry" else None
            document.packages.append(Package(package, options=options))

        self._cover(document, exam)
        self._questions(document, exam)
        self._solution_key(document, exam)
        return document
```

Lines 83 to 92. Standard `article` class at 11pt. `geometry` with a one-inch margin, `amsmath` and `amssymb` for the mathematics the model writes. The loop with an inline conditional for options is a slightly clever way to write four appends; it is fine, though a plain list of pairs would read better. `titlesec` is loaded but nothing in this file uses it — harmless dead weight, and worth admitting rather than inventing a reason for.

Lines 89 to 91 are the document structure in three calls: cover, questions, solution key.

```python
        for line in (
            r"\begin{titlepage}",
            r"\centering",
            ...
            r"{\Large \textbf{" + exam.title + r"} \par}",
            ...
            r"{\large Total points: " + str(total_points) + r" \par}",
            r"\end{titlepage}",
        ):
            document.append(NoEscape(line))
```

Lines 94 to 116, `_cover`. This is hand-written LaTeX in raw strings, appended line by line. Raw strings (`r"..."`) throughout, because otherwise every LaTeX backslash would need doubling. Line 96 sums the actual points on the questions that survived generation rather than assuming the nominal 100, so a batch that failed produces a cover page that still tells the truth. `\today` on line 108 is resolved by LaTeX at compile time. `\vfill` on line 112 pushes the total to the bottom of the page.

Note that `exam.title` and `instructions` are concatenated in raw — the no-escaping decision applied consistently, with the same caveat as above.

```python
    @classmethod
    def _questions(cls, document: Document, exam: FinalExamModel) -> None:
        document.append(NoEscape(r"\newpage"))

        with document.create(Section(NoEscape("Questions"), numbering=False)):
            with document.create(Enumerate()) as questions:
                for question in exam.questions:
                    questions.add_item(NoEscape(f"{question.text} ({question.points} points)"))
                    cls._answer_area(document, question)
                    document.append(NoEscape(r"\vspace{0.5cm}"))
```

Lines 118 to 127, and there is one thing here worth understanding properly because it looks wrong.

Inside the `Enumerate` block, line 126 calls `_answer_area(document, question)` and line 127 appends to `document` — not to `questions`. At a glance that should place the answer areas outside the numbered list. It does not, and the reason is how PyLaTeX's `create` context manager works. From `pylatex/base_classes/containers.py`:

```python
prev_data = self.data
self.data = child.data  # This way append works appends to the child
yield child
self.data = prev_data
self.append(child)
```

It temporarily swaps the document's own content list for the child environment's content list. So for the duration of the `with` block, `document.append(...)` really does append into the environment, and the environment is added to the document when the block exits. That is why passing `document` into the helper is correct, and why the nested `document.create(Itemize())` inside `_answer_area` also lands in the right place. If asked why the code does not pass `questions` around, the answer is that PyLaTeX's design makes the container implicit, and the helper stays usable from either context because of it.

`numbering=False` on line 122 gives an unnumbered "Questions" heading, so the section is not labelled "1 Questions" above a list that starts at 1.

```python
    @staticmethod
    def _answer_area(document: Document, question: ExamQuestion) -> None:
        if question.type == "MCQ" and question.options:
            with document.create(Itemize()) as options:
                for option in question.options:
                    options.add_item(NoEscape(option))
            return

        space = ANSWER_SPACE.get(question.type)
        if space:
            document.append(NoEscape(rf"\vspace{{{space}}}"))
```

Lines 129 to 139. Multiple choice gets a bullet list of options; everything else gets blank writing space. The `and question.options` guard handles a question the model typed as MCQ without supplying options, which would otherwise produce an empty `itemize` and a LaTeX error. `ANSWER_SPACE.get` returning `None` for an unrecognised type means an unknown type silently gets no space rather than crashing — a reasonable default for a cosmetic property. Line 139 uses an f-string with doubled braces inside a raw string, which is how you get a literal `{4cm}` past f-string interpolation.

```python
    @staticmethod
    def _solution_key(document: Document, exam: FinalExamModel) -> None:
        document.append(NoEscape(r"\newpage"))

        with document.create(Section(NoEscape(r"Solution key \& grading rubric"), numbering=False)):
            document.append(NoEscape(r"\textbf{Confidential: instructor use only}"))
            ...
            with document.create(Enumerate()) as answers:
                for question in exam.questions:
                    answers.add_item(NoEscape(r"\textbf{" + question.id + r"}"))
                    document.append(NoEscape(r" \ \ \textbf{Model answer:} " + question.model_answer))
                    document.append(NoEscape(r" \\ \textit{Grading notes:} " + question.grading_notes))
                    document.append(NoEscape(r"\vspace{0.3cm}"))
```

Lines 141 to 155. The answer key, on its own page. Note the escaped `\&` on line 145 — a bare `&` is a column separator in LaTeX and would break the compile. That is the one place in the file where escaping is done, and it is done by hand because the string is written by the developer rather than the model.

Line 151 prints `question.id`, which is where the renumbering back at `generators.py:283` becomes visible: without it this key would list `Q1` three times. The `\\` on line 153 forces a line break between the model answer and the grading notes.

**Worth knowing.** The solution key is in the same PDF as the exam. For a self-study tool that is the point — you want the answers. The "Confidential: instructor use only" line is a nod to the other use case, and if an interviewer asks, the honest answer is that a two-file export, exam and key separately, would be the right shape for classroom use and is not built.

---

## backend/services/exports/slides_pptx.py

154 lines. This builds a real PowerPoint file with python-pptx, which writes the OOXML zip that PowerPoint, Keynote and Google Slides all open.

```python
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
```

Lines 8 to 12. `Inches` and `Pt` are converters into English Metric Units, the internal unit of OOXML, where one inch is 914400 EMU. You never write EMU by hand.

```python
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
BLANK_LAYOUT = 6
```

Lines 18 to 20. python-pptx's default template is 10 by 7.5 inches, which is 4:3 — the shape of a projector from 2005. Setting 13.333 by 7.5 makes it 16:9, which is what every screen the deck will actually be shown on looks like.

`BLANK_LAYOUT = 6` is an index into the default template's layout list. Index 6 is genuinely called "Blank" in that template; the others are "Title Slide", "Title and Content" and so on. The named constant is there because a bare `slide_layouts[6]` in the middle of a function tells the reader nothing. Choosing the blank layout is a deliberate decision: layouts with placeholders bring inherited fonts, sizes and positions, and fighting that inheritance is harder than positioning every box explicitly. So this file uses an empty canvas and absolute coordinates throughout.

```python
PRIMARY = RGBColor(0x1E, 0x1B, 0x4B)
ACCENT = RGBColor(0x63, 0x66, 0xF1)
BODY = RGBColor(0x36, 0x36, 0x36)
SUBTITLE = RGBColor(0xCB, 0xD5, 0xE1)
HEADER_FILL = RGBColor(0xF1, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
```

Lines 22 to 27. A six-colour palette named by role rather than by colour, so the deck can be re-themed by editing six lines. These are the Tailwind indigo and slate values the frontend uses, so an exported deck looks like the app it came from.

```python
class DeckError(ValueError):
    """A deck was missing content that rendering requires."""
```

Lines 30 and 31. Subclassing `ValueError` because that is what it is: bad input. It is caught by the blanket handler in `ExportService.export`, so a malformed deck costs the download and nothing more.

```python
    def render(self, deck: SlidesModel, destination: Path) -> Path:
        """Write `deck` to `destination` and return that path."""
        self._validate(deck)
        logger.info("Rendering %d slides", len(deck.slides))

        presentation = Presentation()
        presentation.slide_width = SLIDE_WIDTH
        presentation.slide_height = SLIDE_HEIGHT

        self._title_slide(presentation, deck)
        for index, entry in enumerate(deck.slides, start=1):
            self._content_slide(presentation, entry, index)

        destination.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(str(destination))
        return destination
```

Lines 37 to 52. Validate first, before any work — nothing has been written when it raises, so there is nothing to clean up. `Presentation()` with no argument loads python-pptx's bundled default template, which is what supplies the eleven layouts. Lines 43 and 44 resize it to 16:9 before any slide is added.

Line 46 adds a title slide, then one slide per entry. `start=1` gives a human-readable number, used only for the log message inside `_content_slide`. Line 50 creates the parent directory, which is redundant here because the caller passes a path inside a freshly created `TemporaryDirectory`, but it makes the renderer safe to call with any destination. Returning the destination lets the caller chain without reconstructing the path.

```python
    @staticmethod
    def _validate(deck: SlidesModel) -> None:
        if not deck.title:
            raise DeckError("The deck has no title")
        if not deck.slides:
            raise DeckError("The deck has no slides")
        for index, slide in enumerate(deck.slides):
            if not slide.heading:
                raise DeckError(f"Slide {index + 1} has no heading")
```

Lines 54 to 62. Three checks that Pydantic cannot make. `SlidesModel.title` is typed `str`, and an empty string is a perfectly valid `str` — so the schema guarantees the field exists but not that it says anything. The per-slide heading check on line 61 is the one that earns its place: a slide with no heading renders as a bare coloured bar with nothing on it, which looks like a bug in the export rather than a thin artifact. The error message names the slide by its 1-based position so it can be found in the app.

```python
    def _title_slide(self, presentation: Presentation, deck: SlidesModel) -> None:
        slide = presentation.slides.add_slide(presentation.slide_layouts[BLANK_LAYOUT])

        background = slide.background.fill
        background.solid()
        background.fore_color.rgb = PRIMARY

        self._text(slide, deck.title, top=2.25, size=44, colour=WHITE, bold=True)
        self._text(
            slide,
            f"Audience: {deck.audience_level or 'General'}",
            top=3.75, height=0.6, size=20, colour=SUBTITLE,
        )
        self._bar(slide, top=7.1, height=0.4, colour=ACCENT)
```

Lines 64 to 77. A dark full-bleed cover. `background.solid()` has to be called before setting a colour — in python-pptx you set the fill *type* first and then its properties, and setting `fore_color` on an unset fill raises. The `or 'General'` on line 74 covers an empty `audience_level`, since the field is a plain `str` with no default. The accent bar at `top=7.1` with `height=0.4` sits exactly on the bottom edge of a 7.5-inch slide.

```python
    def _content_slide(self, presentation: Presentation, entry: Slide, number: int) -> None:
        slide = presentation.slides.add_slide(presentation.slide_layouts[BLANK_LAYOUT])

        self._bar(slide, top=0, height=1.0, colour=HEADER_FILL)
        self._text(slide, entry.heading, top=0.1, left=0.5, width=12.333,
                   height=0.8, size=32, colour=PRIMARY, bold=True)
        self._bar(slide, top=1.1, height=0.03, left=1, width=11.333, colour=ACCENT)
```

Lines 79 to 85. Every content slide is built from the same four or five absolutely positioned elements: a pale header band across the top inch, the heading inside it, and a three-hundredths-of-an-inch accent rule under it. The widths are chosen against the 13.333-inch canvas — `left=0.5` with `width=12.333` leaves a half-inch margin on both sides.

Order matters here in a way that is easy to miss: shapes are drawn in the order they are added, so the header bar has to be added before the heading text or it would cover it.

```python
        if entry.main_idea:
            self._text(slide, entry.main_idea, top=1.4, left=1.5, width=10.333, height=0.8,
                       size=20, colour=RGBColor(0x43, 0x38, 0xCA), italic=True)

        if entry.bullet_points:
            self._bullets(slide, entry.bullet_points)
```

Lines 87 to 92. Both optional, both guarded, because the schema does not require them to be non-empty. The colour on line 89 is an inline `RGBColor` rather than a named constant — the only one in the file, and an inconsistency rather than a decision.

```python
        if entry.speaker_notes:
            try:
                slide.notes_slide.notes_text_frame.text = entry.speaker_notes
            except Exception as error:
                logger.debug("Could not attach notes to slide %d: %s", number, error)
```

Lines 94 to 98. Speaker notes, and the only `try/except` in the file. Accessing `slide.notes_slide` lazily creates a notes slide from the template's notes master, and that can fail on templates where the notes master is missing or malformed. Notes are worth having but not worth losing a deck over, so the failure is logged at debug level and the render continues. This is the same "the file is a convenience" policy from `ExportService`, applied one level down. The `number` parameter exists solely for this log line.

```python
    @staticmethod
    def _text(
        slide,
        text: str,
        *,
        top: float,
        left: float = 0,
        width: float = 13.333,
        height: float = 1.5,
        size: int,
        colour: RGBColor,
        bold: bool = False,
        italic: bool = False,
    ) -> None:
```

Lines 100 to 113. Note the bare `*` on line 104: everything after it is keyword-only. With this many numeric parameters that is the right call — `self._text(slide, title, 2.25, 0, 13.333, 1.5, 44, ...)` would be unreadable and easy to get wrong. The defaults describe a full-width box, so callers only pass what differs.

```python
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        box.text_frame.word_wrap = True

        paragraph = box.text_frame.paragraphs[0]
        paragraph.text = str(text)
        paragraph.font.size = Pt(size)
        ...
        paragraph.alignment = PP_ALIGN.CENTER
```

Lines 114 to 123. `word_wrap = True` is off by default in python-pptx, and without it long text runs off the side of the slide instead of wrapping. Line 117 uses `paragraphs[0]` rather than adding a paragraph, because a new text frame already contains one empty paragraph; adding another would leave a blank line above the text. `str(text)` is defensive against a non-string sneaking through. Formatting is applied at paragraph level, which works because every box here holds exactly one paragraph.

```python
    @staticmethod
    def _bullets(slide, points: list[str]) -> None:
        box = slide.shapes.add_textbox(Inches(1.0), Inches(2.4), Inches(11.333), Inches(4.5))
        frame = box.text_frame
        frame.word_wrap = True

        for index, point in enumerate(points):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = f"{index + 1}. {point}"
            paragraph.font.size = Pt(20)
            paragraph.font.color.rgb = BODY
            paragraph.space_after = Pt(16)
```

Lines 125 to 136. The bullet block, positioned below the header and main idea. Line 132 is the same first-paragraph trick as `_text`, now inside a loop: reuse the existing empty paragraph for the first point, add new ones after that.

Line 133 numbers the bullets manually with `f"{index + 1}. "`. That is not laziness — a plain text box on a blank layout has no list formatting attached, and getting real PowerPoint bullet glyphs means writing `buChar` elements into the XML by hand through python-pptx's lower-level API. Numbering in the string is the pragmatic choice and it prints identically. `space_after` gives the lines breathing room without manual positioning.

```python
    @staticmethod
    def _bar(
        slide,
        *,
        top: float,
        height: float,
        colour: RGBColor,
        left: float = 0,
        width: float = 13.333,
    ) -> None:
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height)
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = colour
        shape.line.fill.background()
```

Lines 138 to 154. Every coloured band on every slide comes from here. `fill.solid()` before `fore_color`, same rule as the background. Line 154, `shape.line.fill.background()`, removes the outline — PowerPoint autoshapes come with a default dark border, and without this line every band would have a thin box drawn round it, which looks broken at the 0.03-inch accent rule size.

**Worth knowing.** `Slide.visual_cue` (`backend/models/artifacts.py:76`) is required by the schema and asked for in the prompt, and nothing renders it — not this file and not the frontend. The model spends tokens on it every time. It is a leftover from an intended illustration feature. Also, there is no autofit or shrink-to-fit anywhere here: a very long heading wraps within its 0.8-inch box and can overlap the accent rule below it. The prompt asks for bullets that are "prompts for the speaker, not paragraphs", which keeps it out of trouble in practice, but the layout has no defence of its own.

---

## Two things to have ready

**Adding a ninth artifact type.** In the backend it is genuinely two dictionary entries: a Pydantic model plus a line in `ARTIFACT_MODELS` (`backend/models/artifacts.py:137`), and a `GeneratorSpec` plus a line in `SPECS` (`generators.py:77`). Nothing else in the generation path needs touching — `generate` looks the spec up, `validate` reads the fields off the spec, and the handler validates against `GENERATED_TYPES`, which is derived from `ARTIFACT_MODELS` at line 148. Two further things are optional and worth naming so the claim stays honest: a renderer in `ArtifactFlattener` (`backend/handlers/sources.py:31`) if the new type should be chainable as a source for another generation, and a branch in `ExportService.export` if it has a file form. The frontend needs a display component either way. The claim is that the *generation pipeline* is open for extension, and that is exactly true.

**Why there is no streaming.** It is the obvious question after "why does this take ninety seconds", and the answer is a design choice rather than an omission. Artifacts are validated before they are shown: Pydantic checks the shape, then `GeneratorSpec.validate` checks that the result is worth reading, and the exam additionally checks it has enough questions. Streaming means rendering tokens before either gate has run. For prose that is a good trade, which is why chat interfaces stream. For a quiz it is not: a half-rendered quiz is a question with no options and no answer key, and if validation then fails the user has already watched a broken artifact appear on screen and now has to watch it disappear. What the system streams instead is *progress* — the handler reports stages at 20, 35, 55 and 90 percent (`generate_handler.py:64` onwards) and those go out over a WebSocket. The user sees "merging sources", "writing quiz", "saving" rather than a spinner, and the artifact appears once, complete and checked.
