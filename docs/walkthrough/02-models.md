# 02 - The models package

`backend/models/` is the bottom of the backend. The one-way dependency rule for this
project is `api -> handlers -> services/pipeline -> llm/models`, and this package sits at
the far end of that arrow. Open any file in it and you will notice that the only imports
are from the standard library and from Pydantic. Nothing in here imports a service, a
handler, a route, or the database. That is deliberate and it is checkable in one glance,
which is the point: if you can import `backend.models.graph` in a REPL with no side
effects, then every layer above it is free to depend on it without creating a cycle.

The package holds three files and they answer three different questions.

- `artifacts.py` answers "what shape is a study artifact". These are the eight schemas
  that the language model is forced to produce, and that the exporters and the frontend
  then read.
- `jobs.py` answers "what work exists and what state can it be in". The job types, the
  job status state machine, and the typed payloads that each handler parses out of the
  queue row.
- `graph.py` answers "what does a finished job hand back". One artifact node, one
  provenance edge, and the bundle that carries a whole job's output to the runner in a
  single object.

They relate to each other in a chain. A job row (`jobs.py`) names a `target_type` in its
payload; that string is one of the keys in `ARTIFACT_MODELS` (`artifacts.py`); the handler
generates an instance of that Pydantic model, dumps it to a dict, wraps it in an
`ArtifactPayload` (`graph.py`), and returns a `JobBundle` that the runner commits. Every
one of those steps has a validation boundary, and this package is where all three of them
are defined.

---

## `backend/models/artifacts.py`

The header tells you what the file is for, and there is nothing interesting in the
imports.

```python
"""The shape of every study artifact the generator can produce."""

from __future__ import annotations
```

`artifacts.py:1` and `artifacts.py:3`. The `__future__` import makes every annotation in
the file a string rather than an evaluated object. Pydantic v2 resolves those strings back
to real types when it builds the class, using the module namespace, so nothing breaks. It
is here because the whole backend uses it consistently, not because this file needs it.

```python
from typing import Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field
```

`artifacts.py:5-7`. Boring. `Literal` is the one worth noticing, because it is how the
closed sets in this file are expressed, and `Literal` is what becomes a JSON Schema `enum`
downstream.

### The big question this file answers

Before the walk-through, hold the "why" in your head, because the interviewer will ask it
and every line below is an instance of the same answer.

These are Pydantic models rather than free-form JSON because they are used twice, at two
different ends of the same call.

First, at request time. `backend/llm/schema.py:15` has `strict_schema(model)`, which turns
a Pydantic class into JSON Schema, inlines every `$ref`, sets `additionalProperties:
False` on every object, and marks every property required. That schema is then sent to the
provider twice over: pasted into the user message at `backend/llm/openrouter.py:107-110`
so the model can read it as text, and attached as
`response_format: {"type": "json_schema", "strict": True, ...}` at
`backend/llm/openrouter.py:112-115` so the provider constrains decoding. The model is not
asked politely to produce a quiz. It is structurally prevented from producing anything
else.

Second, at response time. `backend/llm/schema.py:65` `parse_as` validates the raw text
against the same class. If it does not validate, `complete_as` raises at
`backend/llm/openrouter.py:89-91` with the schema name and a 300-character preview of what
actually came back. The job then fails and rolls back. So a half-formed quiz never reaches
the database: it dies at the parse boundary, before a `JobBundle` is ever constructed.

The concrete payoff is downstream code that does not defend. `services/exports/exam_pdf.py`
imports `FinalExamModel` and `ExamQuestion` directly and walks `exam.questions[i].options`
with no `.get()` and no `None` check, because by the time an exam reaches the renderer it
has already been through validation. If these were dicts, every exporter and every
frontend component would have to re-check the same things.

### ExamSpec

```python
class ExamSpec(BaseModel):
    """The assessment contract an exam is written against."""

    discipline: Literal["Writing", "Philosophy", "Math", "Physics", "CS", "General"]
```

`artifacts.py:10-13`. This is the only model in the file that is not itself an artifact.
It is an intermediate: the exam generator asks the model to write an assessment contract
first, then writes the questions against that contract. You can see it at
`backend/services/generators.py:258`, and the two-stage rationale is in the docstring at
`generators.py:243-256`.

`discipline` is a `Literal` and not a `str`. In the strict JSON Schema this becomes
`{"enum": ["Writing", ..., "General"], "type": "string"}`, and with `strict: True` the
provider will not emit anything outside that list. That matters because the value is
interpolated straight into the next prompt at `generators.py:314`. A free-form string
would let the model invent a discipline and then quietly write questions for it. The
closed set means the second-stage prompt has a bounded input.

If the model does violate it, the failure is loud, not silent: `parse_as` raises, and
`_exam_spec` at `generators.py:293-300` catches it, logs a warning, and falls back to
`DEFAULT_EXAM_SPEC` (`generators.py:199-205`). That is the one place in the codebase where
a schema violation is recoverable, and it is recoverable precisely because the contract is
advisory rather than the artifact itself.

```python
    exam_style: str = Field(description="Analytic, problem-solving, creative, and so on")
    cognitive_targets: List[str] = Field(description="Learning outcomes under test")
    grading_philosophy: str = Field(description="How partial credit is awarded")
    instructions_tone: str = Field(description="Formal, encouraging, and so on")
```

`artifacts.py:14-17`. Four free-text fields, and this is where the `Field(description=...)`
pattern shows up for the first time. Two things are going on and both are worth saying out
loud.

The first is that these descriptions are not documentation for humans. Pydantic puts
`description` into `model_json_schema()`, `strict_schema` preserves it, and the schema is
sent to the model. So `description="How partial credit is awarded"` is prompt engineering
delivered through the type system. It travels with the field, so it cannot drift out of
sync with the field the way a line in a prompt template can.

The second is subtler and comes up repeatedly in this file. `Field(description=...)` with
no positional default leaves the field **required**. `exam_style: str = Field(...)` looks
like an assignment with a default, but the default is `PydanticUndefined`. That is the
intended behaviour here, and it is a real difference from `Field(None, description=...)`
which you will see later at `artifacts.py:110`.

### ExamQuestion

```python
class ExamQuestion(BaseModel):
    id: str
    text: str = Field(description="The question. LaTeX for mathematics")
    type: Literal["MCQ", "Short Answer", "Problem Set"]
```

`artifacts.py:20-23`. `id` is a plain string, not a UUID, because these ids are display
labels rather than database keys. The generator overwrites all of them anyway at
`generators.py:282-283`, renumbering to `Q-1`, `Q-2` and so on after the concurrent
batches come back in whatever order they finished. Whatever the model puts here is
discarded.

The `text` description says LaTeX explicitly, and that pairs with a real decision further
downstream: `services/exports/exam_pdf.py:26-28` passes question text through to LaTeX
untouched, deliberately not escaping it, because escaping would break every formula. So
the description on this field and the non-escaping in the renderer are the two halves of
one contract.

`type` is a `Literal` again, and this one is load-bearing rather than cosmetic. The exam
is generated in three batches, one per question type, at `generators.py:207`
(`EXAM_BATCHES`). The renderer switches on the same three strings at
`exam_pdf.py:18` (`ANSWER_SPACE`), which decides how much blank space to leave for a
handwritten answer. A fourth question type invented by the model would produce a question
the renderer does not know how to lay out.

```python
    options: Optional[List[str]] = Field(description="Choices for MCQ, null otherwise")
```

`artifacts.py:24`. Stop here, because this is the single most probe-able line in the file.

`Optional[List[str]]` with `Field(description=...)` and no default is **required but
nullable**. The model must emit the key; it may emit `null`. I checked the produced
schema: it comes out as
`{"anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}], ...}` and
`options` appears in the object's `required` list.

That is the right shape for strict mode. `strict_schema` sets
`resolved["required"] = list(resolved["properties"])` at `llm/schema.py:40`, so every
property is required whether you like it or not. If `options` had a `None` default,
Pydantic would accept a response with the key missing, but the provider's strict decoder
would still demand it. Making the field required-but-nullable means the Pydantic side and
the provider side agree: always present, sometimes null. A short-answer question emits
`"options": null` and validates.

Compare this with `QuizQuestion.options` at `artifacts.py:42`, which is a bare
`List[str]` — required and non-nullable, because every quiz question is either True/False
or MCQ and both have choices.

```python
    points: int
    model_answer: str = Field(description="The ideal complete response")
    grading_notes: str = Field(description="Where the marks are")
```

`artifacts.py:25-27`. `points` has no bounds, which is worth knowing about (see the note
at the end of this section). `model_answer` and `grading_notes` are the fields that make
an exam usable rather than just printable: `exam_pdf.py` renders them into a solution key
section at the back of the booklet, and `handlers/sources.py:81-89` reads them when an
exam is chained into another generator, so a downstream artifact sees the answers and not
just the questions.

### FinalExamModel

```python
class FinalExamModel(BaseModel):
    title: str
    exam_spec: Optional[ExamSpec] = None
    instructions: Optional[str] = None
    questions: List[ExamQuestion] = Field(default_factory=list)
    rubric: Optional[str] = None
```

`artifacts.py:30-35`. Notice that this model is far laxer than the others: everything
except `title` has a default. That is not sloppiness, it is because **the model never
produces a `FinalExamModel`**. Look at `generators.py:216-228`: `generate` special-cases
`"exam"` on line 223 and routes to `_exam`, and `"exam"` is not in the `SPECS` table at
`generators.py:77-189` at all. The language model produces an `ExamSpec` and three
`QuestionBatch` objects; `FinalExamModel` is assembled in Python at `generators.py:285-291`
from parts that have each already validated.

So the defaults exist because this is a server-side container, and the fields are filled
in by code that already knows they are present. `default_factory=list` on `questions`
rather than `= []` is the ordinary Pydantic idiom: a mutable default shared across
instances would be a bug.

The consequence is that the "at least N questions" rule cannot live in the schema. It
lives at `generators.py:277-280`, which raises `GenerationError` if fewer than
`MIN_EXAM_QUESTIONS` (ten, `generators.py:30`) survive the batch gather. That is the same
division of labour you will see everywhere in this file: shape is enforced by Pydantic,
sufficiency is enforced by `GeneratorSpec.validate`.

### QuizQuestion and QuizModel

```python
class QuizQuestion(BaseModel):
    id: str
    text: str
    type: Literal["True/False", "MCQ"]
    options: List[str]
    correct_answer_index: int = Field(description="Zero-based index into options")
```

`artifacts.py:38-43`. `options` here is required and non-nullable, as discussed. The
interesting field is `correct_answer_index`, which is an unbounded `int` with a
description that tells the model it is zero-based. Nothing in the schema stops the model
from returning `7` for a four-option question.

The consumer defends instead. `handlers/sources.py:64-65`:

```python
index = question.get("correct_answer_index", 0)
answer = options[index] if 0 <= index < len(options) else ""
```

That range check exists because the index bound is not expressible in the type. It is
worth being able to say that plainly: the schema constrains structure, not arithmetic
relationships between fields, and where a relationship matters the code that reads it
checks it.

```python
    explanation: str = Field(description="Why that answer is right")
    topic_focus: str = Field(description="The concept under test")


class QuizModel(BaseModel):
    title: str
    questions: List[QuizQuestion]
```

`artifacts.py:44-50`. `explanation` is required because of the prompt at
`generators.py:92`, "The explanation is what the learner reads to understand the answer" —
the quiz is a study tool, not a test, so an answer with no reasoning is useless. The
`questions` list here has no default, unlike the exam's, so a quiz with a missing
`questions` key fails validation outright. A quiz with an *empty* list would still
validate, which is why `SPECS["quiz"]` at `generators.py:78-81` sets
`required_field="questions"` and `minimum_items=5`. `tests/test_seams.py:105-118` pins
that behaviour: a one-question quiz raises `GenerationError` matching "at least 5
questions".

### Flashcard and FlashcardModel

```python
class Flashcard(BaseModel):
    front: str = Field(description="Prompt or question")
    back: str = Field(description="Answer or definition")
    hint: Optional[str] = None
    source_reference: Optional[str] = None
```

`artifacts.py:53-57`. Here is the contrast with `ExamQuestion.options`. `hint` and
`source_reference` are `Optional[...] = None`, so they are genuinely optional on the
Pydantic side — an object with neither key validates. They are still marked required in
the strict JSON Schema because `strict_schema` requires everything, so in practice the
provider emits them as `null`. The looseness is for everything that is not the provider:
older rows, test fixtures, hand-constructed cards.

```python
class FlashcardModel(BaseModel):
    cards: List[Flashcard]
```

`artifacts.py:60-61`. A single-field wrapper. It exists because the provider's structured
output must be a JSON object, not a bare array, and because giving the collection a named
type means `SPECS["flashcards"]` can say `required_field="cards"`.

### NotesModel

```python
class NotesModel(BaseModel):
    """Study notes held as Markdown."""

    title: str
    format: str = "markdown"
    body: str
```

`artifacts.py:64-69`. Notes are the odd one out and you should know why. Look at
`SPECS["notes"]` at `generators.py:128-144`: it has **no `schema`**, only
`minimum_characters=200` and a prompt ending "Output pure Markdown. No JSON, no
surrounding code fence." Then at `generators.py:234-238`, the branch is:

```python
model = (
    await self._provider.complete_as(prompt, spec.schema, context=context)
    if spec.schema
    else self._as_notes(await self._provider.complete(prompt, context=context), core)
)
```

So notes go through `complete` (free text), and `_as_notes` at `generators.py:343-351`
constructs the `NotesModel` in Python, lifting the title out of the leading `# ` line if
there is one. The reason is that Markdown prose does not want to be JSON. Forcing a long
document through a JSON string field means escaping every newline, and it wastes output
tokens on escapes at exactly the artifact type that needs the most output budget.

`format: str = "markdown"` is a constant carried on the object so a frontend renderer can
switch on it without knowing the artifact type. Nothing currently sets it to anything
else.

### Slide and SlidesModel

```python
class Slide(BaseModel):
    heading: str
    main_idea: str = Field(description="One sentence summary")
    bullet_points: List[str]
    visual_cue: str = Field(description="What to draw on this slide")
    speaker_notes: str
```

`artifacts.py:72-77`. Five required fields. `speaker_notes` being required rather than
optional is a product decision expressed as a type: the prompt at `generators.py:124` says
"Every slide needs speaker notes that say what to explain", and the schema makes it
non-negotiable rather than a suggestion the model can skip on slide nine when it is
running low on budget.

`visual_cue` is a description of an image, not an image. Nothing renders it today;
`services/exports/slides_pptx.py` builds the deck from headings, bullets and notes. It is
a hook for a future image generation step, and you should say so rather than claim it does
something it does not.

```python
class SlidesModel(BaseModel):
    title: str
    audience_level: str
    slides: List[Slide]
```

`artifacts.py:80-83`. `audience_level` is free text that the model fills in from the
material. `SPECS["slides"]` requires at least three slides (`generators.py:112-115`).

### StudyGuideModel

```python
class StudyGuideModel(BaseModel):
    """A revision plan for a single study session."""

    title: str
    estimated_minutes: int
    objectives: List[str] = Field(description="Most important first")
    body: str = Field(description="Markdown, ordered by dependency")
    checklist: List[str] = Field(description="Self-check questions")
```

`artifacts.py:86-93`. Every field is required. The three descriptions are all about
*ordering*, which is something you cannot express in a type at all: "most important
first", "ordered by dependency". This is the clearest example in the file of the
description field doing prompt work. The prompt at `generators.py:152-153` says the same
thing again — "Order by dependency: prerequisites before the ideas that need them" —
because saying it in both places is cheap and the model attends to both.

Note that `body` is a Markdown string inside a JSON schema here, which is exactly what
`NotesModel` avoids. The difference is that a study guide's body sits alongside four other
structured fields, so the object has to be JSON regardless, whereas notes are nothing but
the body.

`SPECS["study_guide"]` validates on `objectives` with a minimum of three
(`generators.py:145-148`), not on `body` — so a study guide with a thin body but three
objectives passes. That is a gap, not a design.

### CheatSheetSection and CheatSheetModel

```python
class CheatSheetSection(BaseModel):
    heading: str
    entries: List[str] = Field(description="Terse one-line facts or formulas")


class CheatSheetModel(BaseModel):
    """A dense single-page reference, optimised for scanning."""

    title: str
    sections: List[CheatSheetSection]
```

`artifacts.py:96-105`. Two levels, both required, minimum two sections at
`generators.py:159-162`. The "under 120 characters" rule for entries lives only in the
prompt (`generators.py:169`), not in the type — there is no `max_length` on the string.
The one-page conceit is therefore aspirational; nothing enforces it.

### The mind map: three explicit levels, not recursion

```python
class MindMapLeaf(BaseModel):
    label: str = Field(description="At most six words")
    detail: Optional[str] = Field(None, description="One sentence under 140 characters")
```

`artifacts.py:108-110`. Note `Field(None, description=...)` here, with an explicit
positional `None`. That is the optional form, and it is the deliberate counterpart to
`ExamQuestion.options` at line 24 which has no positional default and is therefore
required. Same-looking syntax, opposite meaning. If an interviewer points at both lines
and asks what the difference is, that is the answer.

```python
class MindMapBranch(BaseModel):
    label: str = Field(description="At most six words")
    detail: Optional[str] = Field(None, description="One sentence under 140 characters")
    children: List[MindMapLeaf] = Field(default_factory=list)


class MindMapRoot(BaseModel):
    label: str = Field(description="The subject of the material")
    detail: Optional[str] = None
    children: List[MindMapBranch] = Field(default_factory=list)
```

`artifacts.py:113-122`. `MindMapBranch.children` is `List[MindMapLeaf]` and
`MindMapRoot.children` is `List[MindMapBranch]`. Three distinct types describing three
distinct depths, rather than one node type that contains a list of itself.

```python
class MindMapModel(BaseModel):
    """
    A concept map fixed at three levels.

    Depth is expressed with distinct types rather than a self-referencing node,
    because a recursive schema gives the model no bound to stop at.
    """
```

`artifacts.py:125-131`. The docstring gives the product reason, and it is the right one: a
`children: List["MindMapNode"]` model tells the model it may nest forever, and models
given unbounded recursion produce deep spindly trees that do not render.

There is a second, mechanical reason worth having ready. A self-referencing Pydantic model
produces a JSON Schema with a `$ref` back into `$defs` — a genuine cycle. Look at
`strict_schema` at `llm/schema.py:25-41`: `resolve` deep-copies the target of every `$ref`
and then calls `resolve` on it again. There is no cycle guard and no depth limit. A
recursive schema would recurse until the stack ran out. So the flat three-level design is
not only better output, it is the shape the inliner can actually handle.

The prompt reinforces it in prose at `generators.py:182-183`: "The tree is exactly three
levels deep: root, branch, leaf. Do not nest further."

```python
    title: str
    root: MindMapRoot
```

`artifacts.py:133-134`. `SPECS["mindmap"]` at `generators.py:175-188` sets no
`required_field` at all, so a mind map with a root and zero branches would pass
validation. The 4-7 branches rule is prompt-only.

### The registry at the bottom

```python
ARTIFACT_MODELS: Dict[str, Type[BaseModel]] = {
    "quiz": QuizModel,
    "exam": FinalExamModel,
    "notes": NotesModel,
    "slides": SlidesModel,
    "flashcards": FlashcardModel,
    "study_guide": StudyGuideModel,
    "cheatsheet": CheatSheetModel,
    "mindmap": MindMapModel,
}
```

`artifacts.py:137-146`. One mapping from the string the API and the canvas speak to the
class that string means. The keys are the vocabulary of the whole product: they appear in
job payloads, in canvas node `subType` fields, in URL paths, and in the capabilities
response.

```python
GENERATED_TYPES = frozenset(ARTIFACT_MODELS)
```

`artifacts.py:148`. `frozenset(dict)` gives you the keys. This is the single source of
truth for "what can this system generate", and it is derived rather than written out
twice, so adding a ninth artifact type means adding one dict entry and the eight places
below pick it up automatically:

- `api/schemas.py:69` and `api/schemas.py:92` reject unknown `target_type` on generate and
  refine requests, so a bad type is a 422 at the edge.
- `handlers/generate_handler.py:53` and `handlers/refine_handler.py:63` check again inside
  the handler, because a job can be inserted by the flow engine without passing through
  the request schema.
- `api/routes/chat.py:129-130` validates what the assistant's intent extraction asked for.
- `services/flow/plan.py:152` and `plan.py:237,255` decide whether a canvas node is a
  generator node and what it generates.
- `handlers/sources.py:14-18` builds `CHAINABLE_TYPES` and `ALLOWED_TARGETS` from it. Line
  18 is worth reading: `{source: GENERATED_TYPES - {source} for source in GENERATED_TYPES}`
  says every generated type can feed every other generated type except itself, which is
  what stops "quiz from quiz".
- `main.py:163` returns it from `/api/capabilities`, and the canvas builds its node palette
  from that response. So the frontend's palette is derived from this dict too.

`frozenset` and not `set` for two reasons: it is immutable so nobody can mutate a
module-level constant at runtime, and set algebra like the `-` on `sources.py:18` works
naturally.

```python
SOURCE_TYPES = frozenset({"youtube", "audio", "video", "pdf", "pptx", "md"})
```

`artifacts.py:150`. The other half of the vocabulary: what can come *in*, as opposed to
what can be generated. Written out literally rather than derived, because there is no
per-source-type Pydantic model — a source artifact's content is a storage key and some
metadata, built at `handlers/ingest_handler.py:232-243`.

Used at `api/schemas.py:43`, `api/routes/projects.py:133`, `handlers/ingest_handler.py:137`
and `main.py:164`. The `youtube` entry is the one with a security consequence: because
`youtube` is a legal source type whose `source_ref` is a URL rather than a path,
`api/schemas.py:47-57` has a separate validator forcing that ref to start with `http://`
or `https://`, since yt-dlp given a bare path will happily read a local file and turn a
YouTube ingest into an arbitrary file read.

The two sets are disjoint, and code relies on that. `ALLOWED_TARGETS` at
`handlers/sources.py:16-19` has no entry for `pdf` or `audio`, so `_check_transition` at
`sources.py:185` finds `None` and permits the transition — a raw source artifact is
allowed to feed anything, and the resolution to a knowledge core happens by walking parent
edges instead.

**Worth knowing.** `ARTIFACT_MODELS`' *values* are not used anywhere outside this file. I
grepped: the only reference to the name is line 148, which throws the values away and
keeps the keys. The schema-to-type mapping that the generator actually uses is the
independent `SPECS` table at `generators.py:77-189`, where each `GeneratorSpec` carries its
own `schema=` field. So there are two tables that both know quiz means `QuizModel`. If an
interviewer notices, the honest answer is that `ARTIFACT_MODELS` is the declarative
registry and `SPECS` is the operational one, they can drift, and collapsing them so
`GeneratorSpec` looked its schema up from `ARTIFACT_MODELS` would remove the duplication.

**Worth knowing.** There are no numeric or length bounds anywhere in this file. No
`ge`/`le` on `points` or `correct_answer_index`, no `min_length`/`max_length` on any
string, no `min_items` on any list. Every quantitative rule — "at most six words", "under
140 characters", "under 120 characters", "10-15 questions" — is either a `description`
string or a line in a prompt. If asked what happens when the model violates a bound: for
the `Literal` fields and the required/nullable structure, validation fails and the job
fails with a message naming the schema. For everything else, nothing happens at the model
layer; the only quantitative gate is `GeneratorSpec.validate` at `generators.py:58-74`,
which checks a minimum item count on one named field and a minimum character count on
`body`. Adding `Field(max_length=140)` to `MindMapLeaf.detail` would move those rules into
the type, at the cost of failing whole artifacts over one long sentence.

---

## `backend/models/jobs.py`

```python
"""Job queue vocabulary: what work exists and what state it can be in."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
```

`jobs.py:1-10`. Standard library plus Pydantic, nothing project-local. Same bottom-of-the-
stack property as `artifacts.py`.

### JobType

```python
class JobType(str, Enum):
    """The kinds of work the queue can execute."""

    INGEST = "ingest"
    GENERATE = "generate"
    REFINE = "refine"
```

`jobs.py:13-19`. Three kinds of work, and that is the whole taxonomy. Ingest turns a file
into a knowledge core. Generate turns one or more artifacts into a new artifact. Refine
rebuilds an existing artifact against a plain-English request.

`class JobType(str, Enum)` and not `class JobType(Enum)` matters. The `str` mixin means
members *are* strings: `JobType.INGEST == "ingest"` is `True`, `json.dumps` serialises it
without a custom encoder, and SQLite can bind it directly as a TEXT value. Without the
mixin, every place that writes a job row would need `.value` and every comparison against
a database string would silently be `False`.

`services/job_runner.py:83-87` maps these to handler classes:

```python
HANDLERS: Dict[str, Callable[[], JobHandler]] = {
    JobType.INGEST.value: IngestHandler,
    JobType.GENERATE.value: GenerateHandler,
    JobType.REFINE.value: RefineHandler,
}
```

That is the entire dispatch table for the worker. There is no `if job.type == ...` chain
anywhere.

### JobStatus and the state machine

```python
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

`jobs.py:21-26`. Five states. Two are live, three are terminal. Learn the transitions,
because "walk me through the lifecycle of a job" is an obvious question and the answer is
entirely in `services/database.py`.

- **created → pending.** `api/routes/jobs.py:69-73` inserts the row with
  `"status": "pending"` *before* dispatching to the broker, so a Redis outage delays the
  work instead of losing it. The flow engine inserts the same way at
  `services/flow/engine.py:229-238`.
- **pending → running.** `database.claim_job` at `database.py:255-278`. It runs inside
  `BEGIN IMMEDIATE`, which takes the write lock before the read, so two workers polling
  the same queue cannot both claim the same row. It also does `attempts=attempts+1` in the
  same statement, which is what makes the retry budget correct.
- **running → completed.** `database.commit_bundle` at `database.py:280-318`. This is the
  only transition into `completed` and it happens in the same transaction as the artifact
  and edge writes. More on that under `graph.py`.
- **running → failed.** `database.fail_job` at `database.py:320-351`.
- **running → pending.** Also `fail_job`, lines 340-345, when the error was classified
  transient by `is_transient` (`job_runner.py:55-72`) and `attempts` is still under
  `job_max_attempts`. Note it clears `started_at` so the reaper does not immediately pick
  it up again. This is the one backwards edge in the machine.
- **running → pending or failed, by the reaper.** `reap_stale_jobs` at `database.py:368-400`
  finds rows left `running` past a cutoff by a worker that died, and either requeues them
  or fails them if the attempts are gone. Without this the row is never claimable again
  and the canvas node spins forever with no error.
- **pending or running → cancelled.** `cancel_job` at `database.py:353-366`.

The three terminal states are exactly the ones in the frozenset:

```python
TERMINAL_STATUSES = frozenset({
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
})
```

`jobs.py:29-33`. This constant is the guard on all three write paths, and each guard
protects a different real scenario.

`database.py:290-291` — `commit_bundle` raises if the job is already terminal. This is how
cancellation is actually honoured. Cancelling does **not** interrupt a running handler;
the handler keeps working and finishes normally. When the runner then tries to commit,
this check fires and the write is refused, so the work is discarded rather than
resurrecting a cancelled job. Trace it through: `commit_bundle` raises, `execute` catches
at `job_runner.py:140`, `_record_failure` calls `fail_job`, `fail_job` sees the terminal
status and returns `"cancelled"` at `database.py:337-338`, and `_record_failure` at
`job_runner.py:179-183` sees an outcome that is neither `failed` nor `missing`, logs
"already finished as cancelled; leaving that outcome alone", and does **not** publish a
`JOB_FAILED` event. The user who cancelled does not get a spurious failure toast.

`database.py:337` — `fail_job` refuses to overwrite a terminal status. The docstring at
`database.py:326-327` names the exact scenario: a job reclaimed by the reaper can be
running twice, and the loser's failure must not overwrite the winner's committed result.

`database.py:359` — `cancel_job` returns `False` for a job that already finished, which
`api/routes/jobs.py:132-133` turns into a 409 rather than a silent success.

The `.value` calls are worth a sentence. Because `JobStatus` subclasses `str`, members hash
and compare as their string values, so a frozenset of members would also match the plain
strings coming out of SQLite — I checked. The `.value` is there so the constant is
unambiguously a set of the exact strings stored in the `status` column, which is what every
caller is comparing against. It removes the need to know the enum-hashing rule to read the
code.

### The payload models

```python
class IngestPayload(BaseModel):
    """Turn a raw source file into a knowledge core."""

    source_type: str
    source_ref: str
    original_name: str = "Untitled"
```

`jobs.py:36-41`. Three fields. `source_ref` is either a filesystem path to a staged upload
or a YouTube URL, depending on `source_type` — see `ingest_handler.py:178-189`.
`original_name` has a default because the caller may not know it (a YouTube URL has no
filename until the download finishes).

Note that `source_type` is a plain `str`, not a `Literal` or an enum. The check against
`SOURCE_TYPES` is explicit at `ingest_handler.py:137-141`. That is on purpose: this model
parses whatever JSON blob was in the queue row, and a typed field would raise a Pydantic
error whose message is worse than the handcrafted "Unknown source type 'x'. Expected one
of: ..." that the handler produces.

```python
class GeneratePayload(BaseModel):
    """Turn one or more artifacts into a new artifact."""

    target_type: str
    source_artifact_ids: List[str] = Field(default_factory=list)
    instructions: Optional[str] = None
    flow_run_id: Optional[str] = None
    flow_node_id: Optional[str] = None
```

`jobs.py:44-51`. `source_artifact_ids` is a **list**, and that plural is the first place
the DAG invariant shows up in a type. A generate job is not "make X from Y", it is "make X
from these N things". Three lectures wired into one quiz node produce one job with three
ids in this list, and `generate_handler.py:133-140` turns that list into three
`EdgePayload` objects. If this were a single `source_artifact_id`, the graph could only
ever be a tree.

`instructions` carries the user's free text, appended to the base prompt by `_steer` at
`generators.py:332-341` with an explicit "these take precedence over the rules above"
marker.

`flow_run_id` and `flow_node_id` are how a job knows it is part of a canvas run. They are
set only by `services/flow/engine.py:235-236` when the flow engine queues a step; a
hand-made generate request leaves them `None`. When the job finishes, `_notify_flow` at
`job_runner.py:190-211` reads them back and tells the flow engine which node just
completed, so the next wave can be scheduled.

```python
class RefinePayload(BaseModel):
    """Rebuild an existing artifact against a plain-English request."""

    source_artifact_id: str
    instructions: str
    target_type: Optional[str] = None
```

`jobs.py:54-59`. Singular `source_artifact_id`, because refinement is by definition one
artifact in and one artifact out. `instructions` is required and not optional here, unlike
generate — `refine_handler.py:53-54` says why: "refinement needs something to act on". A
refine with no instructions is just a regenerate.

`target_type` is optional and defaults to the source artifact's own type at
`refine_handler.py:62`, which is the normal case (refine a quiz, get a quiz). Supplying it
lets refine act as a type conversion.

### JobModel

```python
class JobModel(BaseModel):
    """A row from the job queue."""

    model_config = ConfigDict(use_enum_values=False)
```

`jobs.py:62-65`. This is the in-memory view of a `jobs` table row, built by
`database._to_job` at `database.py:519-532` and handed to handlers.

`use_enum_values=False` is Pydantic's default, so this line is an explicit declaration
rather than a change. It is here because it is load-bearing and someone might otherwise
"simplify" it to `True`. With `False`, `job.type` is a `JobType` **member**, so
`job_runner.py:110` can write `job_type = job.type.value`. If it were `True`, Pydantic
would store the raw string and `.value` would raise `AttributeError` on every single job.
Writing the default down is a note to the next person that the choice was made
deliberately.

```python
    id: UUID
    project_id: UUID
    type: JobType
    status: JobStatus
```

`jobs.py:67-70`. The two id fields are typed `UUID` even though SQLite stores them as
TEXT. Pydantic parses the string on construction, so a corrupt id fails loudly at
`_to_job` rather than propagating into a query. `type` and `status` being enums means
Pydantic rejects a row whose status is not one of the five — a typo in a hand-written
`UPDATE` would surface at the next claim rather than causing a job to sit in a state
nothing handles.

```python
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
```

`jobs.py:71-72`. `payload` is deliberately untyped. One `jobs` table holds three different
kinds of work with three different payload shapes, and the queue does not need to know
which is which — the router does, and each handler re-parses on line one of its `run`:
`IngestPayload(**job.payload)` at `ingest_handler.py:135`, `GeneratePayload(**job.payload)`
at `generate_handler.py:48`, `RefinePayload(**job.payload)` at `refine_handler.py:50`.

That is the design: one generic queue row, three typed views, and the type is asserted at
the moment of use rather than at the moment of storage. It means adding a fourth job type
touches `JobType`, one payload model, one handler and one entry in `HANDLERS` — and
nothing in the database layer at all.

`result` is the same story in reverse: the shape is whatever the handler put in
`JobBundle.result`, and `database.py:312-313` writes it back as JSON.

```python
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

`jobs.py:73-76`. The timestamps map onto the state machine exactly: `created_at` is always
set, `started_at` is set on claim and cleared on requeue, `completed_at` is set on the
transition into any terminal state. `error_message` is truncated to 2000 characters at
`database.py:343` and `database.py:349` before it is stored, because a stack trace from a
provider can be enormous and this column is read by the UI.

Note that `attempts` is a real column (`database.py:52`) but is **not** on `JobModel`. The
retry accounting lives entirely in SQL — incremented in `claim_job`, read in `fail_job` and
`reap_stale_jobs` — and no handler needs to see it. `api/schemas.py:125` does expose it to
the API, from the raw row.

```python
    @property
    def flow_run_id(self) -> Optional[str]:
        return self.payload.get("flow_run_id")

    @property
    def flow_node_id(self) -> Optional[str]:
        return self.payload.get("flow_node_id")
```

`jobs.py:78-84`. Two conveniences that read out of the untyped payload dict. This is a
nice illustration of the dependency rule. The flow engine lives in
`backend/services/flow/`, which is above `models` in the stack, so `JobModel` cannot import
anything about flows and cannot have a typed `flow_run: FlowRun` field. Instead the flow
information rides in the generic payload and these properties give the runner a readable
accessor, used at `job_runner.py:197` and `job_runner.py:204-205`. The lower layer stays
ignorant of the higher one and still exposes something ergonomic.

**Worth knowing.** These properties read from the raw dict, so they resolve for *any* job
type, not just generate. Only `GeneratePayload` declares the fields, and only the flow
engine sets them, so in practice an ingest or refine job always returns `None` — but the
property would happily return a value if something ever put one there. The typed payload
and the untyped accessor are not in sync by construction, only by convention.

---

## `backend/models/graph.py`

Fifty-five lines, and they carry the most important architectural decision in the backend.

```python
"""The unit of work a handler returns and the runner commits."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
```

`graph.py:1-9`. Note both `import uuid` (for `uuid.UUID(...)` as a constructor) and
`from uuid import UUID` (for the annotation). Slightly redundant but harmless.

### as_uuid

```python
def as_uuid(value: Any) -> UUID:
    """Parse an artifact identifier, rejecting anything malformed."""
    if isinstance(value, UUID):
        return value
```

`graph.py:12-15`. The fast path. Ids inside the backend are already `UUID` objects — the
child id in every edge is a freshly minted `uuid.uuid4()` — so this returns immediately for
those and only does work on the ones that arrived as text.

```python
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"Not a valid artifact id: {value!r}") from error
```

`graph.py:16-19`. `str(value)` first so that anything with a sane `__str__` gets a chance,
then `uuid.UUID` does the actual parsing and the actual rejecting.

The three exception types: `ValueError` is the one that fires in practice (`uuid.UUID`
raises it for a badly formed hex string, and `str(None)` gives `"None"` which is a
`ValueError`). `TypeError` and `AttributeError` are belt and braces for exotic inputs — be
honest about that if asked rather than inventing a scenario for each.

`f"...{value!r}"` uses `repr` rather than `str` so that an empty string shows as `''` and
`None` shows as `None` in the log, instead of vanishing into whitespace. `from error`
chains the original so the traceback keeps the underlying reason.

**Now the important part: what this is defending against.** The previous version of this
function did, in substance:

```python
try:
    return uuid.uuid4() if isinstance(x, str) else x
except:
    pass
```

Two independent bugs in three lines. First, on the successful path it did not *parse* the
string, it minted a brand new random UUID and returned that. Second, a bare `except: pass`
meant any failure returned `None` silently.

The consequence was specific and nasty. Ids arrive from JSON as strings — the frontend
sends `source_artifact_ids` as a list of strings, and both `generate_handler.py:135` and
`refine_handler.py:133` feed those strings straight into `as_uuid` to build the
`parent_artifact_id` of an edge. With the old code, every one of those parents became a
fresh random UUID. The edge row was written, the transaction committed, the job reported
success, and the graph looked correct in the database — but the edge pointed at an
artifact that had never existed and never would.

The symptom did not appear until later, when something tried to walk the graph.
`SourceResolver._parent_core` at `handlers/sources.py:174-181` fetches each parent edge and
looks up the parent artifact; `get_artifact` returned `None`, the loop found nothing, and
the caller raised `SourceResolutionError: Could not resolve a knowledge core for artifact
...` at a completely different job, on a completely different node, some time later. A
silent corruption at write time surfacing as an unrelated failure at read time is the worst
possible failure mode, and that is what this function exists to prevent.

Raising `ValueError` here fails the job at bundle-construction time, before
`commit_bundle` is reached, so nothing at all is written. That is only safe because of the
bundle design described below.

### ArtifactPayload

```python
class ArtifactPayload(BaseModel):
    """A node in the knowledge graph, before it is written."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: UUID
    project_id: UUID
    type: str
    content: Dict[str, Any]
```

`graph.py:22-30`. A node the handler intends to create. It is not the database row: the
row also has `created_by_job_id`, `created_at` and `updated_at`, all of which are filled in
by `commit_bundle` at `database.py:293-300` rather than by the handler. That is the right
split — a handler should not be inventing timestamps.

`id` is minted by the handler, not by the database. `generate_handler.py:110` and
`refine_handler.py:109` both do `artifact_id = uuid.uuid4()` at the top of `_bundle`, and
`ingest_handler.py:226` mints two at once. That matters because the id is needed *before*
the write, twice over: the exporter uses it as part of the storage key
(`generate_handler.py:120`), and every edge in the bundle needs it as
`child_artifact_id`. Letting SQLite assign the id would mean a second round trip and a
partially-built bundle.

`type` is a plain `str` and not constrained to `GENERATED_TYPES`, because it also holds the
source types (`pdf`, `audio`) and `knowledge_core`, which is in neither set. The type check
happens earlier, in each handler, against the right set for that handler.

`content: Dict[str, Any]` is the union of every artifact shape. Ingest writes
`{"kind": "source", "storage_key": ..., ...}` and `{"kind": "core", "title": ..., "core": ...}`
at `ingest_handler.py:236-248`; generate writes `{"kind": "generated", "target_type": ...,
"data": model.model_dump(), ...}` at `generate_handler.py:112-121`. The `kind` discriminator
is what readers switch on. It is untyped here because it is stored as a JSON blob in a
single TEXT column, and typing it would mean a discriminated union that no consumer
actually needs.

Notice what `model_dump()` at `generate_handler.py:115` means: the Pydantic model has done
its job by that point. It validated the model's output, and then it is flattened to a plain
dict for storage. The type safety is a gate at generation time, not a runtime wrapper that
persists.

**Worth knowing.** `arbitrary_types_allowed=True` on line 25 does nothing here. That config
flag only matters when a field is annotated with a class Pydantic does not know how to
handle, and every annotation on this model — `UUID`, `str`, `Dict[str, Any]` — is
standard. It is almost certainly left over from an earlier version where `content` held
something richer. Do not claim it is doing work.

### EdgePayload

```python
class EdgePayload(BaseModel):
    """A provenance link: `child` was derived from `parent`."""

    parent_artifact_id: UUID
    child_artifact_id: UUID
    project_id: UUID
    relationship_type: str = "derived_from"
```

`graph.py:33-39`. One directed edge, parent to child, meaning "child was made from
parent".

Read the direction carefully, because it is the opposite of what people often assume:
`parent` is the *source*, the thing that already existed; `child` is the *new* artifact. So
edges point forward in time, from input to output.

`project_id` on the edge is denormalised — you could get it from either endpoint. It is
here because the `artifact_edges` table has
`project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE`
(`database.py:71`), so deleting a project cleans up its edges without a join, and edges can
be filtered per project directly.

`relationship_type` defaults to `"derived_from"` and every call site in the codebase takes
the default. It exists so the edge table can carry other kinds of relationship later
without a migration. It also participates in the uniqueness constraint at
`database.py:76`:

```sql
UNIQUE (parent_artifact_id, child_artifact_id, relationship_type)
```

which, combined with `INSERT OR IGNORE` at `database.py:304`, makes edge writing idempotent.
Re-running a job cannot produce a duplicate edge.

### JobBundle: why this type exists at all

```python
class JobBundle(BaseModel):
    """
    Everything one job produced.

    Handlers build this and never touch the database; the runner commits it in a
    single transaction, so a handler that fails midway leaves no partial graph.
    """
```

`graph.py:42-48`. If you only prepare one answer from this whole document, prepare this
one.

A handler could perfectly well take a `Database` and write as it goes. The reason it does
not is that generation is long, remote and unreliable. A generate job calls out to a
language model, possibly several times concurrently (the exam does three batches at once,
`generators.py:260-264`), and then renders a PDF or a PPTX. Any of those can time out,
return garbage, or hit a rate limit. If the handler wrote the artifact row first and then
the export failed, you would have a row in the graph with no file and no edges, and no
mechanism to notice.

Returning a value instead means there is exactly one moment when anything becomes real.
The contract is stated in `handlers/base.py:22-24`:

> Handlers never write to the database. They return a `JobBundle` and the runner commits
> it in a single transaction, so a handler that fails partway through cannot leave a
> half-written graph behind.

and enforced by the abstract signature at `handlers/base.py:50-52`:
`async def run(self, job: JobModel) -> JobBundle`. The runner is at
`job_runner.py:121-124`:

```python
bundle = await asyncio.wait_for(
    handler.run(job), timeout=get_settings().job_timeout_seconds
)
self._database.commit_bundle(bundle)
```

If `run` raises anywhere — including the `ValueError` from `as_uuid`, including a
`GenerationError` for too few questions, including the whole thing blowing past
`job_timeout_seconds` — `commit_bundle` is simply never called. There is nothing to roll
back because nothing was written.

And `commit_bundle` itself (`database.py:284-318`) does all of it inside one
`BEGIN IMMEDIATE`: insert every artifact, insert every edge, flip the job to `completed`
with its result, and touch the project's `updated_at`. So there is no observable
intermediate state. You never see an artifact whose job is still `running`, and you never
see an edge whose child artifact does not exist. Either the whole job happened or none of
it did.

Three more properties fall out of the design and are worth having ready:

- **Testability.** A handler is a pure-ish function from `JobModel` to `JobBundle`, so a
  test can run it and assert on the returned object without a database at all.
  `tests/test_seams.py:181-183` does exactly that: run the handler, assert
  `bundle.artifacts[0].content["data"]["title"]` and `len(bundle.edges) == 1`.
- **Ordering.** `commit_bundle` writes artifacts before edges, so the child artifact
  always exists by the time its edges land. (Note that `artifact_edges` has no foreign key
  on `parent_artifact_id` or `child_artifact_id` — `database.py:69-77` — so SQLite would
  not catch a violation. The ordering is a correctness discipline, not a constraint.)
- **Events after commit.** `job_runner.py:127-133` publishes `ARTIFACT_CREATED` and
  `JOB_COMPLETED` only after `commit_bundle` returns. A client that hears "artifact
  created" and immediately fetches it always finds it.

```python
    job_id: UUID
    project_id: UUID
    artifacts: List[ArtifactPayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
```

`graph.py:50-54`. `job_id` is what `commit_bundle` uses to find the row to complete
(`database.py:286`) and also what it stamps onto every artifact as `created_by_job_id`
(`database.py:299`). `project_id` is used to touch the project's `updated_at`
(`database.py:315-318`) so a project list sorted by recency is correct.

All three collections default to empty, which makes a bundle with no artifacts and no edges
legal. That is used: `tests/test_pipeline.py:247` commits
`JobBundle(job_id=job.id, project_id=project["id"])` purely to move a job to `completed`.

`result` is the small dict the API and the frontend read. The handlers agree on a rough
shape — `{"status": "success", "artifact_id": ..., "artifact_type": ...}` at
`generate_handler.py:141-146`, plus `source_count`; refine adds `refined_from`
(`refine_handler.py:137-142`); ingest returns `source_artifact_id` and `core_artifact_id`
instead of `artifact_id` (`ingest_handler.py:252-257`). It is untyped because those shapes
genuinely differ. One consumer to be aware of: `job_runner.py:135` reads
`bundle.result.get("artifact_id")` to tell the flow engine which artifact a completed node
produced, and ingest does not set that key — which is fine, because ingest jobs are never
flow steps.

---

## The two graph invariants

Both of these live in the shapes above, but neither is enforced by a constraint. They are
maintained by the handlers, and you should be able to point at the lines.

### 1. Provenance is a DAG, not a tree

A tree gives every node exactly one parent. This graph does not, and that is the whole
point of the canvas.

`generate_handler.py:133-140`:

```python
edges=[
    EdgePayload(
        parent_artifact_id=as_uuid(source_id),
        child_artifact_id=artifact_id,
        project_id=job.project_id,
    )
    for source_id in source_ids
],
```

One edge per source, in a comprehension over the list. Wire three lecture recordings into
one study-guide node on the canvas, and the flow engine collects three input artifact ids
(`services/flow/engine.py:129`), the job payload carries all three in
`source_artifact_ids`, and this comprehension emits three `derived_from` edges into the
same child. That artifact has three parents. The class docstring at
`generate_handler.py:29-30` states it: "Every source becomes a `derived_from` edge, so a
node with three inputs records three parents and the graph the user drew is the graph
stored."

The database side agrees. `get_parent_edges` at `database.py:425-427` carries the comment
"An artifact may have many parents", and both directions are indexed separately
(`idx_edges_parent` and `idx_edges_child`, `database.py:105-106`) because both are walked.

`generate_handler._unique` at `generate_handler.py:165-168` is a small supporting detail:
`list(dict.fromkeys(...))` deduplicates the source ids while preserving the order they were
wired in. Without it, the same artifact wired twice would produce two identical edges — the
`UNIQUE` constraint plus `INSERT OR IGNORE` would absorb the second, but the source would
also be resolved and merged twice, doubling its weight in the generated content.

The **acyclic** half of DAG is guaranteed structurally rather than checked. The child id in
every edge is a `uuid.uuid4()` minted moments earlier in the same function
(`generate_handler.py:110`, `refine_handler.py:109`). A brand-new random id cannot already
be somewhere in the graph, so a new node can never be its own ancestor. There is no cycle
detection on the artifact graph anywhere, and none is needed. (Cycle detection *does* exist,
but on the canvas graph, in `services/flow/plan.py`, which is a different graph and a
different document — Kahn's algorithm there detects a cycle the user drew before any job is
queued.)

Refine adds one more shape: `refine_handler.py:132-136` writes a single edge from the old
artifact to the new one. So revisions are a chain hanging off whatever the original was
derived from, and nothing is edited in place — the class docstring at
`refine_handler.py:30-32` gives the reason, which is that an exported file must not change
underneath the user who downloaded it.

### 2. The knowledge core has indegree zero

`ingest_handler.py:251`:

```python
edges=[],
```

An ingest job produces two artifacts — the source record and the knowledge core — and
**no edges at all**. Not even between those two. The docstring at
`ingest_handler.py:110-114` says why:

> Ingest produces exactly two artifacts and no edges. The core is the root of the project's
> graph, and provenance back to the source file is carried by `created_by_job_id` rather
> than by an edge, because the core was not derived from anything already in the graph.

The mechanism is `commit_bundle` at `database.py:296-299`, which stamps
`created_by_job_id` with `bundle.job_id` on every artifact it writes. Both the source
artifact and the core get the same job id, so the link between them is recoverable — they
are the two outputs of one ingest — without an edge existing.

Why keep it out of the edge table rather than adding a `source_of` edge? Because
`derived_from` has a precise meaning that the rest of the code relies on: it means "a
generator read the parent's content and produced the child". `SourceResolver._parent_core`
at `handlers/sources.py:174-181` walks parent edges looking for a `knowledge_core` to
generate from. If a raw PDF artifact were the core's parent, that walk would have to learn
to skip it. Keeping the edge table to one meaning keeps every traversal simple.

The practical consequence: in any project, the artifacts with indegree zero are exactly the
sources and the cores. Every edge in the table has a generated or refined artifact as its
child. So "where did this quiz come from" is a walk backwards up `derived_from` edges that
always terminates at a knowledge core, and "what was that core made from" is a different
question answered by `created_by_job_id` and the job's payload.

---

## Questions you should expect, and where the answer lives

- *Why Pydantic and not just JSON?* Because the class is used to build the strict JSON
  Schema sent to the provider (`llm/schema.py:15`, `llm/openrouter.py:106-116`) and to
  validate the response (`llm/schema.py:65`, `llm/openrouter.py:88-91`). Shape is enforced
  at both ends of the call, so a half-formed artifact never reaches `commit_bundle`.
- *What happens when the model breaks the schema?* Structural violations — a bad `Literal`,
  a missing required field — fail validation and fail the job, with the schema name and a
  300-character preview in the message. Quantitative rules are not in the schema at all;
  the only quantitative gate is `GeneratorSpec.validate` at `generators.py:58-74`.
- *Why does `JobBundle` exist?* So there is exactly one moment when a job becomes real.
  Handlers are pure, the runner commits, and a handler that throws halfway leaves nothing
  written (`handlers/base.py:19-29`, `job_runner.py:121-124`, `database.py:280-318`).
- *What is `as_uuid` for?* Ids arrive from JSON as strings. The old version minted a random
  UUID instead of parsing, inside a bare `except: pass`, so a malformed id silently became
  an edge pointing at an artifact that never existed, and the damage surfaced later as an
  unrelated `SourceResolutionError`.
- *Which job states are terminal?* `completed`, `failed`, `cancelled`
  (`jobs.py:29-33`), and all three write paths in `database.py` refuse to move a job out of
  one. Cancellation is honoured at commit time rather than by interrupting a running
  handler.
- *Is the provenance graph a tree?* No. One edge per source
  (`generate_handler.py:133-140`), so three inputs give three parents. Acyclicity comes free
  because child ids are freshly minted UUIDs.
