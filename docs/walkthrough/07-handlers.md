# 07 — Handlers

Files walked in this document:

- `backend/handlers/base.py` — the `JobHandler` contract
- `backend/handlers/sources.py` — `SourceResolver` and `ArtifactFlattener`
- `backend/handlers/ingest_handler.py` — a source file becomes a knowledge core
- `backend/handlers/generate_handler.py` — artifacts become a new artifact
- `backend/handlers/refine_handler.py` — an artifact plus instructions becomes a revision

---

## Part 0 — The contract, before any code

Everything in these five files is shaped by one rule, so it is worth stating on
its own before looking at a single line.

### The lifecycle a handler sits inside

A job goes through six steps. Handlers are step four.

1. **The job row is written as `pending`, and it is committed before anything is
   dispatched.** Whoever creates the job (the `/api/jobs` route, the upload
   route, the chat route, or the flow engine) writes a row into the `jobs` table
   and commits it. Only then does it tell a worker the job exists. The ordering
   is deliberate. If the broker is down, or the dispatch call throws, the row is
   still there, and the next worker to poll the queue will find it. Work gets
   delayed; it does not get lost.

2. **Dispatch, which is allowed to fail.** `enqueue(job_id)` either hands the id
   to Celery or falls back to the in-process worker pool. Because of step one,
   a failure here is a delay, not a loss.

3. **`claim_job()`, which exactly one worker wins.** `backend/services/database.py:276`.
   It opens the transaction with `BEGIN IMMEDIATE`, which takes SQLite's write
   lock *before* the read, so two workers polling the same queue cannot both
   select the same `pending` row and both flip it to `running`. The winner gets a
   `JobModel`; the loser gets `None` and moves on.

4. **`handler.run(job)` returns a `JobBundle`, and writes nothing to the
   database.** This is the contract. A handler reads whatever it needs, calls
   whatever models it needs, builds an in-memory description of everything the
   job produced, and returns it. It does not insert artifacts. It does not
   insert edges. It does not set the job status.

5. **`commit_bundle()` writes artifacts, edges and the terminal status in one
   transaction.** `backend/services/database.py:301`. Artifacts, edges, the job's
   `completed` status and result, and the project's `updated_at` all land inside
   a single `BEGIN IMMEDIATE ... COMMIT`. Either all of it is there or none of it
   is.

6. **The flow engine is notified so it can schedule whatever this unblocked.**
   `JobExecutor._notify_flow`, `backend/services/job_runner.py:223`.

### Why step four forbids writes

The honest reason is failure rates. A handler for one of these jobs makes
between one and six calls to a language model over the network. Those calls time
out, get rate limited, return truncated JSON, return JSON that parses but fails
schema validation, and occasionally return something the generator's own
validation rejects as too thin to be useful. A handler throwing partway through
is not the rare edge case here. It is a routine outcome that happens many times
a day.

Now imagine handlers wrote as they went. `GenerateHandler` would insert the
artifact, then insert the edge from each source, then mark the job complete. A
failure between the artifact insert and the edge inserts leaves an artifact in
the graph with no parents: an orphan node that the canvas renders floating in
space, that the flow engine cannot reason about, and that nothing will ever
clean up. A failure after the edges but before the status update leaves a job
stuck at `running` with its output already committed — and then the stale-job
reaper requeues it, and it runs a second time and produces a *second* artifact
with a second set of edges.

Returning a bundle makes all of that structurally impossible. If the handler
throws, the runner catches it at `job_runner.py:154`, records the failure, and
there is nothing to undo, because nothing was written.

There is a second benefit that matters for the interview: **a handler is
testable without a database in any interesting state.** `handler.run(job)` is
close to a pure function from a job row to a description of work. You can assert
on the returned bundle — its artifact types, its edge count, its result payload
— without inspecting a single table. `backend/tests/test_seams.py:187` does
exactly this.

### One handler serves every worker

There is a second half to the contract, and it is easy to miss because it is
about the handler object rather than about the database.

`JobExecutor` builds one handler instance per job type and keeps it
(`handler_for`, `job_runner.py:101-115`), and `WorkerPool` hands every one of its
worker tasks the *same* `JobExecutor` (`job_runner.py:262`). The default worker
concurrency is four (`core/config.py:136`). So up to four jobs of the same type
can be inside `handler.run` at the same moment, on one object.

That sharing is deliberate. Constructing a handler builds its whole collaborator
graph — five objects for `IngestHandler` (`ingest_handler.py:120-132`), several
of which reach for the model provider — and building a fresh one per job would
pay that cost every time anybody uploads anything. But it is only safe while the
handler is something a job *reads*. The moment one job writes to the instance,
the four runs are writing to each other.

So the contract has two halves, and the second one is stated as plainly as the
first: **a handler writes nothing to the database, and nothing writes to the
handler.** Anything that varies per job arrives on a copy. `with_progress`
(`base.py:37-52`) returns `copy.copy(self)` with the reporter set on the copy,
and the shared instance is never touched. The docstring on `handler_for` says the
same thing from the other side: *"Callers get a handler to read, not one to write
to"* (`job_runner.py:102-109`).

That second half is not a theoretical nicety. It was violated, and the walk
through `base.py` below tells the story of what it cost.

### The shape of the return value

`backend/models/graph.py` defines it.

```python
class JobBundle(BaseModel):
    job_id: UUID
    project_id: UUID
    artifacts: List[ArtifactPayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
```

`graph.py:42`. Five fields: which job this was, which project it belongs to, the
nodes to write, the edges to write, and a small dictionary that gets stored on
the job row and shipped over the WebSocket as the `job.completed` payload.

Note that the handler generates the artifact UUIDs itself, in Python, before
anything is written. It has to: the edges reference the new artifact's id, so
the id must exist before the transaction opens. `uuid.uuid4()` at
`ingest_handler.py:242`, `generate_handler.py:110` and `refine_handler.py:109`.

### One sentence for the interview

> Handlers are pure. They do the work, they describe what they produced, and the
> runner commits that description in a single transaction. That is because model
> calls fail often, and a handler that could write halfway through would leave
> orphan nodes and duplicate artifacts in the graph — so I made it impossible for
> a handler to write at all.

And, if the follow-up is about concurrency:

> One handler instance serves every worker, so purity has to hold in the other
> direction too: nothing writes to the handler either. The per-job reporter is
> attached to a shallow copy rather than assigned to the shared object, which is
> a bug I had and fixed rather than a rule I started with.

---

## Part 1 — `backend/handlers/base.py`

69 lines. It defines one abstract class and one type alias, and almost every
line is a decision.

```python
"""The contract every job handler implements."""

from __future__ import annotations
```

`base.py:1-3`. The `__future__` import makes all annotations lazy strings rather
than objects evaluated at import time. It is here for the same reason it is at
the top of every file in this backend: it lets you write a forward reference like
`-> "JobHandler"` inside the class that is still being defined, and it costs
nothing.

```python
import copy
from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.models.graph import JobBundle
from backend.models.jobs import JobModel
```

`base.py:5-10`. Boring imports, with one that is not. There is no `Database`
here — the base class has no idea persistence exists, which is the first half of
the contract expressed as an import list. And `copy` on line 5 is the second
half: it is there for exactly one call, in `with_progress`, and the reason is
below.

```python
ProgressReporter = Callable[[str, int], None]
```

`base.py:12`. A named type alias for "a function taking a stage name and a
percentage, returning nothing". Naming it means the signature appears once
instead of three times, and it reads better at the call sites.

```python
def _ignore(_stage: str, _percent: int) -> None:
    """Default reporter, used when nobody is listening."""
```

`base.py:15-16`. A no-op with the right signature. The alternative would have
been `Optional[ProgressReporter] = None` plus an `if self.progress is not None`
guard at every call site. A null object is cheaper to read and cannot be
forgotten. The underscore prefixes on the parameters say "deliberately unused"
so a linter does not complain.

```python
class JobHandler(ABC):
```

`base.py:19`. Abstract base class. `ABC` plus `@abstractmethod` on `run` means
Python refuses to instantiate a subclass that has not implemented `run`. That
failure happens at construction time in `JobExecutor.handler_for`
(`job_runner.py:114`) rather than as an `AttributeError` deep inside a worker
loop.

```python
    """
    Does the work for one kind of job and describes what it produced.

    Handlers never write to the database. They return a `JobBundle` and the
    runner commits it in a single transaction, so a handler that fails partway
    through cannot leave a half-written graph behind.

    Progress is reported through a callback carried by the handler rather than
    published directly, which keeps the event transport out of the handler and
    lets a test assert on the sequence of stages. The callback is per job and
    the instance is not: a handler is built once and shared by every worker, so
    it is attached by `with_progress` on a copy and never written to the shared
    instance.
    """
```

`base.py:20-33`. The contract, written where someone opening the file will read
it.

The second paragraph is worth expanding when asked. The alternative was for
handlers to `import publish` from `services/events` and call it directly. That
would couple every handler to the WebSocket layer, mean every handler test needs
the event system stubbed, and make it impossible to run a handler in a context
where there is no live connection. Instead the runner builds a closure
(`job_runner.py:130`) that knows the project id and the job id, and the handler
only knows "call this with a stage and a number".

**This docstring used to say something different, and correcting it was part of
the fix described below.** It said progress was reported "through an injected
callback". That word made the mechanism sound like dependency injection — a
collaborator handed in at construction, the pattern the rest of this backend
genuinely uses. It was not. It was an assignment onto an object that several
jobs were running on at once. Somebody reading the docstring would have believed
a concurrency property that the code did not have.

That matters more here than it would in most codebases, because of a convention
this backend keeps strictly: there are no inline comments in it at all. Not few —
none, across `handlers`, `services`, `pipeline`, `models`, `api`, `llm` and
`core`. Every explanation lives in a docstring.

Once that is the rule, a docstring is not documentation sitting beside the code;
it is the only account of why the code is the way it is. So a docstring that
misdescribes the code is not untidiness. It is a wrong explanation shipped in
place of a right one, and the next person to reason about concurrency here would
have reasoned from it. It is a defect, and it gets fixed in the same commit as
the defect it was describing.

That is also the honest answer to "why are there no comments in your code". The
rule is not "never explain". It is "explain in the one place that is attached to
the thing it explains, that shows up in `help()` and in an editor's hover, and
that a reviewer reads as part of the signature". The cost of the rule is that
docstrings have to be maintained like code — which is exactly what this change
had to do.

```python
    progress: ProgressReporter = staticmethod(_ignore)
```

`base.py:35`. This line looks like a typo and is not. If it were written
`progress: ProgressReporter = _ignore`, then `_ignore` would be a plain function
sitting in the class dictionary, and plain functions are descriptors: accessing
`self.progress` would bind it as a method and pass `self` as the first argument.
`self.progress("storing source", 10)` would then be calling `_ignore(self,
"storing source", 10)` — three arguments into a two-parameter function, and a
`TypeError`. Wrapping it in `staticmethod` suppresses that binding. Since Python
3.10 a `staticmethod` object is directly callable, so this works when accessed
through the class as well as through an instance.

**Worth knowing.** The instance assignment on the next method
(`attached.progress = reporter or _ignore`) does *not* need the same treatment,
because the descriptor protocol only fires for attributes found on the class, not
for attributes found in the instance dictionary. So a plain function assigned to
an instance's `progress` stays unbound and is called with exactly the two
arguments given. This is the kind of asymmetry an interviewer may well ask about
if they notice the `staticmethod`.

```python
    def with_progress(self, reporter: Optional[ProgressReporter]) -> "JobHandler":
        """
        Return a copy of this handler that reports to `reporter`.

        Assigning the reporter here would write to an instance several jobs are
        running on at once: the job that attached last would own the callback,
        and every job still in flight would report into that job's project under
        that job's id.

        The copy is shallow on purpose: the collaborators opened in `__init__`
        are what make construction expensive and they stay shared. Only the
        reporter differs per job, and no handler keeps any other per-job state.
        """
        attached = copy.copy(self)
        attached.progress = reporter or _ignore
        return attached
```

`base.py:37-52`. Three lines of body and twelve of docstring, which is the right
ratio here, because this method is where a live concurrency bug was.

The runner calls it as one expression:

```python
handler = self.handler_for(job_type).with_progress(lambda stage, percent: ...)
```

`job_runner.py:129`. The `or _ignore` means passing `None` explicitly resets to
the no-op rather than installing `None` and blowing up later.

**The bug this replaced, which is worth being able to tell end to end.**

This method used to read `self.progress = reporter or _ignore; return self`, and
its docstring called that "attach a progress reporter and return self for
chaining". Nothing about it looked wrong on its own. The problem was what it was
attaching to.

`WorkerPool.__init__` builds one `JobExecutor` (`job_runner.py:262`) and starts
`worker_concurrency` worker tasks against it — four by default
(`core/config.py:136`). `JobExecutor.handler_for` caches one handler instance per
job type (`job_runner.py:110-115`). Its docstring said "Build one handler per
type and reuse it; construction opens clients", which reads as a harmless
optimisation and is a true statement about cost. It is also, unstated, a
statement about sharing: every concurrent job of that type is running on that one
object.

So play it through. Worker 0 claims generate job A in project P1 and calls
`with_progress`, which sets the reporter on the shared `GenerateHandler`. Worker 1
claims generate job B in project P2, calls `with_progress`, and overwrites it.
Job A resumes from its `await`, calls `self.report("writing quiz", 55)`, and that
event publishes to project **P2** under job **B's** id. P1's client sees the job
start and then nothing until it completes. P2's client sees job B jump to a stage
it never reached. Cross-project event misattribution, reproduced directly rather
than reasoned about.

**Why the tests never caught it**, which is a question worth having an answer to.
Under Celery the bug cannot happen: `backend/tasks.py:44` builds a fresh
`JobExecutor()` for every task, so each task gets its own handler cache and each
handler instance serves exactly one job. Only the in-process `WorkerPool` shares
an executor across concurrent runs, and nothing in the suite ran two jobs through
one executor at the same time. The bug needed concurrency *and* a shared
executor, and the tests had neither together.

**The fix, and why it is a copy rather than a lock or a per-job build.** Building
a handler per job would be correct and would throw away the reason the cache
exists: `IngestHandler()` constructs five collaborators, `GenerateHandler()` five
more, and several of them reach for the model provider on the way up. A lock
would serialise jobs that have no reason to be serialised. `copy.copy` gives a
new object whose `__dict__` is a
shallow copy of the original's, so every collaborator is still the same object by
reference and nothing expensive is reconstructed. What differs per job is one
attribute holding one closure.

That is only safe if `progress` is the only per-job mutable state, so all three
handlers were read to confirm it before the change: each one sets its
collaborators in `__init__` and never writes to `self` during `run`. Everything
else a job needs is a local variable or an argument.

Two named tests, one for each half of the claim.
`test_concurrent_jobs_report_under_their_own_identity` (`test_seams.py:448`) runs
two jobs in different projects through one `JobExecutor`, holds both inside `run`
at a rendezvous so their reporters are definitely both attached, and asserts that
all four progress events carry the right project and job id — it fails on the old
code. `test_attaching_a_reporter_leaves_the_shared_handler_alone`
(`test_seams.py:476`) asserts the narrower structural fact:
`attached is not shared`, `"progress" not in vars(shared)`, and the cache still
returns the same shared instance afterwards. The middle assertion is the precise
one — the shared handler's instance dictionary never gains a `progress` key at
all, so it goes on resolving the class-level `staticmethod(_ignore)`.

```python
    def report(self, stage: str, percent: int) -> None:
        """
        Announce the stage now running and how far through the job it is.

        A reporter that fails is swallowed: progress is decoration, and losing a
        WebSocket mid-run must not fail work that is otherwise succeeding.
        """
        try:
            self.progress(stage, max(0, min(100, percent)))
        except Exception:
            pass
```

`base.py:54-64`. Two decisions.

`max(0, min(100, percent))` clamps the value into the range the frontend's
progress bar expects. The clamp lives here so no individual handler has to think
about it, and so a mistake in one handler's percentages cannot render a bar at
137%.

The bare `except Exception: pass` is the kind of thing that is usually a smell,
and it is defensible here for a specific reason: the callback is a WebSocket
publish. If the user closed the browser tab mid-generation, that publish can
raise. It would be absurd for a closed tab to fail a job that has already spent
thirty seconds of model time and is about to succeed. Note that it catches
`Exception` and not `BaseException`, so an `asyncio.CancelledError` — which is a
`BaseException` — still propagates, and a job being torn down is still torn down.
That distinction matters elsewhere in this codebase (see `generators.py:266` and
`merger.py:100`) and it is consistent here.

```python
    @abstractmethod
    async def run(self, job: JobModel) -> JobBundle:
        """Do the work and return everything that should be committed."""
```

`base.py:66-68`. The whole interface. One method, `async`, takes a job row,
returns a bundle.

The `async` is not cosmetic and it is worth knowing the history. Handlers used to
be declared `async` while calling a *synchronous* HTTP client for the model. An
`async def` that blocks on a synchronous network call holds the event loop for
the entire duration of that call, which for a knowledge-core extraction is tens
of seconds. Every other worker, every other request, and every WebSocket in the
process froze for that whole time. Four workers and one worker performed
identically, because there was only ever one thing making progress. The path is
now genuinely async end to end: `LLMProvider.complete` and `complete_as` are both
`async` (`backend/llm/base.py:29` and `:33`), and everything between the handler
and the provider — `KnowledgeExtractor.extract`, `TextCleaner.clean_transcript`,
`ArtifactGenerator.generate`, `CoreMerger.merge` — is `async` too. That is what
makes concurrency real, and it is also what lets `ArtifactGenerator._exam` run
its three question batches under one `asyncio.gather`
(`generators.py:260`).

**Worth knowing.** Not everything a handler touches is async. `SourceResolver`
does synchronous SQLite reads, and `ExportService.export` is synchronous and
shells out to LaTeX with `subprocess.run` (`services/exports/exam_pdf.py:62`).
Both run on the event loop. SQLite reads are sub-millisecond and local, so they
are genuinely fine. The LaTeX subprocess is the one that could still stall the
loop for a second or two on an exam export. If asked "is it async all the way
down", the accurate answer is "the model calls are, which is where the seconds
were; the PDF render is not, and that is the remaining one".

---

## Part 2 — `backend/handlers/sources.py`

201 lines. Two classes. `ArtifactFlattener` turns a generated artifact back into
plain text. `SourceResolver` turns a list of artifact ids into a list of
`KnowledgeCore` objects that a generator can read.

### Why this file exists at all

The premise of the product is that everything is generated from a knowledge
core, so that the quiz and the notes and the exam agree with each other. But the
canvas lets a user wire *any* artifact into a generator: notes into a quiz, a
quiz into flashcards, three different lectures into one study guide. The
generator only knows how to read a `KnowledgeCore`. Something has to stand
between "whatever the user wired in" and "one `KnowledgeCore`". That is this
file.

```python
"""Resolves the artifacts feeding a generator into knowledge cores."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.models.artifacts import GENERATED_TYPES
from backend.pipeline.knowledge import KnowledgeCore
from backend.services.database import Database

logger = logging.getLogger(__name__)
```

`sources.py:1-12`. Boring.

```python
CHAINABLE_TYPES = GENERATED_TYPES | {"text", "flat_text", "transcription"}
```

`sources.py:14`. `GENERATED_TYPES` is a `frozenset` of the eight generated
artifact types (`models/artifacts.py:148`, derived from the keys of
`ARTIFACT_MODELS` so the two can never drift). The `|` union adds three plain-text
artifact types. "Chainable" means: this artifact can be rendered back to text and
used as the source material for a new generation.

Notice what is *not* in this set: the raw source types (`pdf`, `audio`,
`youtube`, and so on, from `models/artifacts.py:150`) and `knowledge_core`.
`knowledge_core` is excluded because it is handled by a separate, earlier branch
— it does not need flattening, it *is* the target format. The raw source types
are excluded because their content is a storage key and a byte count, not text.

**Worth knowing.** Because a raw source artifact is neither `knowledge_core` nor
chainable, `to_core` falls through to `_parent_core` for it, and `IngestHandler`
deliberately emits no edges — so a raw source artifact has no parents and
resolution raises. In practice this is correct: on the canvas the node you wire
into a generator is the knowledge core, not the uploaded PDF. But if an
interviewer asks "what happens if I wire the PDF node itself into a quiz", the
answer is a `SourceResolutionError` naming the artifact and its type, which is a
clear failure rather than a silent wrong answer.

```python
ALLOWED_TARGETS: Dict[str, frozenset] = {
    "knowledge_core": GENERATED_TYPES,
    **{source: GENERATED_TYPES - {source} for source in GENERATED_TYPES},
}
```

`sources.py:16-19`. The transition table. A `knowledge_core` can produce any of
the eight generated types. Any generated type can produce any generated type
*except itself* — `GENERATED_TYPES - {source}` is a frozenset difference. So
notes → quiz is fine, quiz → flashcards is fine, quiz → quiz is refused.

The self-exclusion is the interesting part. Generating a quiz from a quiz is
almost never what the user meant: it would take the quiz, flatten it back to
text, and ask a model to write a quiz from that text — a lossy round trip that
produces a worse copy. The operation the user actually wants there is *refine*,
which keeps the original in view and revises it, and which lives in a different
handler. Refusing the transition pushes them to the right tool.

**This is the fix for a specific past defect.** The old version of this map was
called `ALLOWED_GENERATIONS`, and the code checked it and then did nothing:

```python
if target not in ALLOWED_GENERATIONS.get(source_type, ...):
    pass
```

A rule that is written down, checked, and then not enforced is worse than no
rule, because everyone reading the file believes the constraint holds. The
enforcement now lives in `_check_transition` at `sources.py:183`, which raises,
and the error message lists what *is* allowed so the user can act on it.

```python
class SourceResolutionError(ValueError):
    """A source artifact could not be reduced to a knowledge core."""
```

`sources.py:22-23`. A named exception subclassing `ValueError`. Naming it means
`RefineHandler` can raise the same type for "artifact not found"
(`refine_handler.py:60`) and callers can distinguish "the input was wrong" from
"the model failed". Subclassing `ValueError` means it is not caught by the
retry classifier as transient — see `is_transient` at `job_runner.py:57`, which
only treats connection-shaped failures and labelled status codes as retryable. A
missing source artifact will never become present on a retry, so retrying it
would just spend three attempts to reach the same conclusion.

### `ArtifactFlattener`

```python
class ArtifactFlattener:
    """Renders a generated artifact back into plain text so it can be chained."""
```

`sources.py:26-27`. The whole class does one thing: given an artifact of any
generated type, produce a plain-text rendering of it.

Why it needs to exist: a downstream node on the canvas can receive artifacts of
mixed types. A "study guide" node might have a notes artifact and a quiz artifact
wired into it. The generator takes exactly one `KnowledgeCore`. So the mixed
inputs have to be reduced to a single uniform representation, and the only
representation that all eight artifact types share is text. The flattener is the
per-type knowledge of how to turn structured JSON back into readable prose.

```python
    def flatten(self, artifact: Dict[str, Any]) -> Optional[str]:
        """Return a text view of the artifact's content, or None if it has none."""
        renderers = {
            "notes": self._body,
            "study_guide": self._body,
            "text": self._raw_text,
            "flat_text": self._raw_text,
            "transcription": self._raw_text,
            "quiz": self._quiz,
            "flashcards": self._flashcards,
            "exam": self._exam,
            "slides": self._slides,
            "cheatsheet": self._cheatsheet,
            "mindmap": self._mindmap,
        }
        renderer = renderers.get(artifact.get("type"))
        if renderer is None:
            return None
```

`sources.py:29-46`. A dispatch table instead of an eleven-branch `if/elif`. Two
types share `_body` and three share `_raw_text`, which a chain of conditionals
would have to repeat.

`renderers.get(...)` returning `None` for an unknown type, and the early return,
is what makes this safe to call on anything. `RefineHandler` calls
`flatten(artifact)` at `refine_handler.py:89` without first checking the type,
and relies on `None` coming back for anything it cannot render.

The table is rebuilt on every call, which is a small waste — it could be a module
constant. It is written this way because the values are bound methods, which
means they cannot be defined at module scope without either making them free
functions or building the table in `__init__`. Not worth changing; worth knowing
it is a deliberate readability trade rather than an oversight, if asked.

```python
        data = (artifact.get("content") or {}).get("data") or {}
        return renderer(data) or None
```

`sources.py:48-49`. `content` is the JSON blob stored on the artifact row. For a
generated artifact it has the shape `{"kind": "generated", "target_type": ...,
"data": {...}}` — see `generate_handler.py:112`. The `or {}` on both levels means
a row with a null `content`, or a `content` with no `data` key, produces an empty
dict rather than an `AttributeError` two frames later.

`renderer(data) or None` normalises the empty string to `None`. Several renderers
can return a header line with no body — `_quiz` with zero questions returns
`"Quiz content:"` and `_body` with no `body` field returns `None` already. The
`or None` gives callers one thing to check: falsy means nothing usable.

```python
    @staticmethod
    def _body(data: Dict[str, Any]) -> Optional[str]:
        return data.get("body") or data.get("markdown") or data.get("content")
```

`sources.py:51-53`. `NotesModel` and `StudyGuideModel` both have a `body` field
(`models/artifacts.py:69` and `:92`), so `body` is the real key. `markdown` and
`content` are fallbacks for rows written by earlier versions of the schema. This
is compatibility cruft and it is fine to describe it as such.

```python
    @staticmethod
    def _raw_text(data: Dict[str, Any]) -> Optional[str]:
        return data.get("text")
```

`sources.py:56-57`. Trivial.

```python
    @staticmethod
    def _quiz(data: Dict[str, Any]) -> str:
        lines = ["Quiz content:"]
        for question in data.get("questions", []):
            options = question.get("options") or []
            index = question.get("correct_answer_index", 0)
            answer = options[index] if 0 <= index < len(options) else ""
            lines += [
                f"Q: {question.get('text', '')}",
                f"Answer: {answer}",
                f"Why: {question.get('explanation', '')}",
            ]
        return "\n".join(lines)
```

`sources.py:59-71`. The header line `"Quiz content:"` is there so that when this
text becomes the `summary` of a synthetic core and gets fed to a model, the model
can tell what kind of material it is reading.

The bounds check on line 65 is the load-bearing line. `QuizQuestion.correct_answer_index`
is a plain `int` in the schema (`models/artifacts.py:43`), and the model that
produced it is not perfectly reliable about staying inside the options list. An
unguarded `options[index]` raises `IndexError`, which would fail the entire
downstream generate job because of one bad question in an artifact that was
generated successfully days earlier. The guard turns that into an empty answer
string for one question, and the rest of the quiz still flattens. Every `.get()`
with a default in this file exists for the same reason: this data was produced by
a model and stored as JSON, so nothing in it is guaranteed.

```python
    @staticmethod
    def _flashcards(data: Dict[str, Any]) -> str:
        lines = ["Flashcard content:"]
        for card in data.get("cards", []):
            lines += [f"Front: {card.get('front', '')}", f"Back: {card.get('back', '')}"]
        return "\n".join(lines)
```

`sources.py:73-78`. Same pattern, simpler shape. `hint` and `source_reference`
are dropped — they are aids for the person studying, not content the next
generator needs.

```python
    @staticmethod
    def _exam(data: Dict[str, Any]) -> str:
        lines = ["Exam content:"]
        for question in data.get("questions", []):
            lines += [
                f"Q: {question.get('text', '')} [{question.get('type', '')}]",
                f"Model answer: {question.get('model_answer', '')}",
                f"Grading: {question.get('grading_notes', '')}",
            ]
        return "\n".join(lines)
```

`sources.py:80-89`. The question type is included in brackets because an exam
mixes MCQ, short answer and problem sets, and a downstream generator reading
"Q: derive the bound" reads differently if it knows that was a problem set.

```python
    @staticmethod
    def _slides(data: Dict[str, Any]) -> str:
        lines = ["Slide content:"]
        for slide in data.get("slides", []):
            lines += [f"# {slide.get('heading', '')}", slide.get("main_idea", "")]
            lines += [f"- {point}" for point in slide.get("bullet_points", [])]
            lines.append(f"Speaker notes: {slide.get('speaker_notes', '')}")
        return "\n".join(lines)
```

`sources.py:91-98`. Renders as loose Markdown — `#` for headings, `-` for
bullets. The speaker notes are kept because on a well-generated deck they carry
more actual content than the bullets do; the bullets are prompts, the notes are
the explanation. `visual_cue` is dropped, since a drawing instruction is not
teachable content.

```python
    @staticmethod
    def _cheatsheet(data: Dict[str, Any]) -> str:
        lines = ["Cheat sheet content:"]
        for section in data.get("sections", []):
            lines.append(f"## {section.get('heading', '')}")
            lines += [f"- {entry}" for entry in section.get("entries", [])]
        return "\n".join(lines)
```

`sources.py:100-106`. Nothing surprising.

```python
    @staticmethod
    def _mindmap(data: Dict[str, Any]) -> str:
        lines = ["Mind map content:"]

        def walk(node: Dict[str, Any], depth: int = 0) -> None:
            lines.append(f"{'  ' * depth}- {node.get('label', '')}: {node.get('detail') or ''}")
            for child in node.get("children", []):
                walk(child, depth + 1)

        root = data.get("root")
        if isinstance(root, dict):
            walk(root)
        return "\n".join(lines)
```

`sources.py:108-120`. The only recursive renderer. `walk` is a closure over
`lines`, appending as it descends; indentation by two spaces per level encodes
the tree structure in the text.

The `isinstance(root, dict)` check on line 118 is the guard. `MindMapModel`
requires a `root` (`models/artifacts.py:134`), but this is reading JSON out of a
database row, not a validated model, so `root` could be absent or a string. Being
explicit here means a malformed mind map flattens to just its header line and
gets treated as "no usable text" by the `or None` in `flatten`, rather than
throwing.

Note that the recursion is unbounded even though the schema is fixed at three
levels. That is fine: `MindMapModel` is a chain of distinct types
(`MindMapRoot` → `MindMapBranch` → `MindMapLeaf`), so a stored mind map
physically cannot nest deeper than three. The docstring at
`models/artifacts.py:126-131` explains why the schema is built that way — a
self-referencing node gives the model no bound to stop at, and it will happily
generate until it runs out of tokens.

### `SourceResolver`

```python
class SourceResolver:
    """
    Reduces every artifact feeding a generator to a knowledge core.

    A generated artifact resolves to its own content rather than its ancestor's,
    so chaining notes into a quiz reads the notes instead of quietly
    regenerating from the original lecture.
    """
```

`sources.py:123-130`. Read the second paragraph carefully, because it is the
single most important design decision in this file.

Every generated artifact has a `derived_from` edge back to whatever produced it,
so from any artifact you can walk up to the original knowledge core. An earlier
design did exactly that: resolve any source by walking to its ancestral core and
generating from that. It was appealing because it meant every artifact in a
project came from the same authoritative core.

It was also wrong from the user's point of view. If someone generates notes,
edits them, and then wires those notes into a quiz node, they are asking for a
quiz *about their notes*. Walking to the ancestor produces a quiz about the whole
original lecture — including all the material the notes deliberately left out.
The user's intermediate step was silently discarded. The failure was invisible:
you got a plausible quiz, just not the one you asked for. So now a generated
artifact resolves to *itself*, flattened. Walking to the parent is only the
fallback for artifacts that cannot be flattened. There is a regression test at
`backend/tests/test_pipeline.py:283`,
`test_chaining_reads_the_chained_artifact_not_its_ancestor`.

```python
    def __init__(self, database: Database, flattener: Optional[ArtifactFlattener] = None) -> None:
        self._database = database
        self._flattener = flattener or ArtifactFlattener()
```

`sources.py:132-134`. The dependency-inversion pattern used throughout these
files, in its simplest form. Note the asymmetry: `database` is required, with no
default. A resolver with no database cannot do anything, so making it optional
would only defer the failure. `flattener` has a default because there is a
sensible one and nobody wants to construct it at every call site.

```python
    def resolve(self, artifact_ids: List[str], target_type: str) -> List[KnowledgeCore]:
        """Fetch every source in one query and turn each into a knowledge core."""
        artifacts = {
            str(artifact["id"]): artifact
            for artifact in self._database.get_artifacts(artifact_ids)
        }
```

`sources.py:136-141`. "In one query" is the point. `get_artifacts`
(`database.py:439`) builds a single `WHERE id IN (?, ?, ?)`, with proper
parameter binding — see `_where` at `database.py:513`, which splits the
`in.(...)` expression and emits one placeholder per value. So this is one round
trip regardless of how many sources a fan-in node has, and it is not string
interpolation into SQL.

Keying the dictionary by `str(artifact["id"])` matters because the ids arriving
in `artifact_ids` are strings (the payload stores them as strings, and
`GenerateHandler._unique` re-stringifies at `generate_handler.py:168`) while the
database row's `id` is also a string in SQLite but could be a `UUID` under a
different driver. Normalising both sides to `str` means the lookup works either
way.

```python
        missing = [artifact_id for artifact_id in artifact_ids if artifact_id not in artifacts]
        if missing:
            raise SourceResolutionError(f"Source artifacts not found: {', '.join(missing)}")
```

`sources.py:143-145`. Every missing id is reported, not just the first. If a user
wired three nodes and two of the ids are stale, one error naming both is one
round of fixing instead of two.

**Worth knowing — this exact error message caused a separate bug.** The message
embeds UUIDs, and UUIDs contain digits. The retry classifier used to search error
text for any bare three-digit HTTP status code, so `"Source artifacts not found:
429e4567-e89b-..."` matched `429` and got classified as a rate limit, and the
permanently-doomed job was retried three times. `TRANSIENT_STATUS` at
`job_runner.py:54` now only matches a code where it is *labelled* as one
(`status: 429`, `code=503`). There is a named regression test:
`test_status_digits_inside_identifiers_do_not_trigger_a_retry`
(`test_pipeline.py:389`). This is a good story to have ready, because it connects
a line in this file to a line in a completely different one.

```python
        for artifact_id in artifact_ids:
            self._check_transition(artifacts[artifact_id].get("type"), target_type)

        return [self.to_core(artifacts[artifact_id]) for artifact_id in artifact_ids]
```

`sources.py:147-150`. Two separate passes, and the ordering is deliberate.
`_check_transition` is cheap and local; `to_core` may hit the database again via
`_parent_core`. Checking all the transitions first means an illegal wiring is
refused before any further work is done.

Both loops iterate `artifact_ids`, not `artifacts.values()`. That preserves the
caller's order, which matters because `GenerateHandler` builds one edge per
source in the same order and the merge output labels sources by title.

```python
    def to_core(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """Reduce a single artifact to the core that should drive generation."""
        source_type = artifact.get("type")
        content = artifact.get("content") or {}
```

`sources.py:152-155`. This is public, not `_`-prefixed, because `RefineHandler`
calls it directly on a single artifact (`refine_handler.py:88`) without going
through `resolve`.

```python
        if source_type == "knowledge_core" and content.get("core"):
            return KnowledgeCore(**content["core"])
```

`sources.py:157-158`. The common case, checked first. A knowledge core artifact
stores the serialised core under `content["core"]` (written at
`ingest_handler.py:264`), and `KnowledgeCore(**...)` revalidates it through
Pydantic on the way back in. Round-tripping through the model rather than passing
the raw dict means a row written by an older schema version fails loudly here
rather than producing odd behaviour inside the generator.

The `and content.get("core")` is not redundant: an artifact typed
`knowledge_core` with an empty or missing `core` falls through to the later
branches instead of raising a `TypeError` on the unpacking.

```python
        if source_type in CHAINABLE_TYPES:
            text = self._flattener.flatten(artifact)
            if text and text.strip():
                logger.info("Chaining from a %s artifact", source_type)
                return self._synthetic(content.get("title") or source_type, text)
```

`sources.py:160-164`. The chaining branch — the one the class docstring is about.
Flatten to text, and if there is real text, wrap it as a synthetic core.

`text and text.strip()` catches whitespace-only output, which a renderer can
produce from an artifact whose fields are all empty strings. The log line is
useful in practice because chaining changes what the model sees, and when a
generated artifact looks wrong the first question is always "what did it actually
read".

If flattening produced nothing, control does *not* return — it falls through to
the parent lookup below. So an empty notes artifact will still generate, from its
ancestor core, rather than failing. That is the right fallback ordering: prefer
the artifact's own content, fall back to its provenance, fail only if neither
exists.

```python
        parent_core = self._parent_core(artifact["id"])
        if parent_core is not None:
            return parent_core

        raise SourceResolutionError(
            f"Could not resolve a knowledge core for artifact {artifact['id']} ({source_type})"
        )
```

`sources.py:166-172`. The fallback, then the failure. Note the error names both
the id and the type, so the message tells you which node on the canvas and what
kind of thing it was.

```python
    def _parent_core(self, artifact_id: Any) -> Optional[KnowledgeCore]:
        for edge in self._database.get_parent_edges(artifact_id):
            parent = self._database.get_artifact(edge["parent_artifact_id"])
            if parent and parent.get("type") == "knowledge_core":
                core = (parent.get("content") or {}).get("core")
                if core:
                    return KnowledgeCore(**core)
        return None
```

`sources.py:174-181`. One level up only. It looks at the artifact's immediate
parents and returns the first one that is a knowledge core.

The single-level limit is worth defending because it looks like an oversight. A
recursive walk would handle a deeper chain — notes → quiz → flashcards, where the
flashcards' grandparent is the core. In practice that case is already handled,
because a quiz is chainable and resolves to itself long before this method is
reached. `_parent_core` only runs for artifacts that could not be flattened at
all, and those are one hop from their core by construction. Adding recursion
would add a cycle-detection problem and an unbounded query count to handle a case
that cannot arise.

Note also that this issues one query per parent edge. Fine, because it only runs
in a rare fallback and the loop exits on the first core it finds.

```python
    @staticmethod
    def _check_transition(source_type: Optional[str], target_type: str) -> None:
        allowed = ALLOWED_TARGETS.get(source_type)
        if allowed is not None and target_type not in allowed:
            raise SourceResolutionError(
                f"Cannot generate '{target_type}' from '{source_type}'. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )
```

`sources.py:183-190`. The enforcement that replaced the `pass`. Note the
structure: `allowed is not None` means an unlisted source type is unrestricted,
not forbidden. `ALLOWED_TARGETS` has keys for `knowledge_core` and the eight
generated types; a `text` or `transcription` artifact is not a key, so it can
feed anything. That is the intended reading — the table exists to forbid the
specific nonsense of regenerating a type from itself, not to enumerate a
whitelist of everything permissible.

The error message lists the allowed targets, sorted for stable output. This is
the difference between "that's not allowed" and an error the user can act on.

**Worth knowing.** `RefineHandler` never calls `_check_transition` — it calls
`to_core` directly at `refine_handler.py:88`. So refining a quiz into a quiz is
allowed while *generating* a quiz from a quiz is refused. That is the intended
split (refine is the operation for "same type, revised"), but it is exactly the
kind of asymmetry an interviewer will probe, so it is better to state it as a
decision than to be caught by it.

```python
    @staticmethod
    def _synthetic(title: str, text: str) -> KnowledgeCore:
        """Wrap chained text as a core so the generator has one uniform input."""
        return KnowledgeCore(
            title=f"Source: {title}",
            summary=text,
            concepts=[], section_hierarchy=[], notes=[],
            definitions=[], examples=[], key_facts=[],
        )
```

`sources.py:192-200`. The adapter that makes the whole chaining design work. The
generator's only input type is `KnowledgeCore`, so chained text is put into the
`summary` field and every other collection is left empty.

Two consequences worth having ready.

First, `summary` here is not a summary. It is the entire flattened artifact,
which for a long set of notes could be many thousands of characters. That is
deliberate — compressing it would throw away the content the user explicitly
wired in — but it means the name of the field is misleading, and the generator
prompt sees the whole thing.

Second, this shape is the implicit signal that `GenerateHandler.build_context`
tests for. "All cores have no concepts and a non-empty summary" means "these are
all synthetic chained cores", which routes to concatenation rather than the
LLM-based merge. See `generate_handler.py:83`. That coupling is real and it is
undocumented at the far end, so it is worth knowing about in both directions.

---

## Part 3 — `backend/handlers/ingest_handler.py`

275 lines. Two classes: a validator for the knowledge core, and the handler that
produces one.

```python
"""Turns an uploaded source into the knowledge core a project is built on."""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.handlers.base import JobHandler
from backend.models.artifacts import SOURCE_TYPES
from backend.models.graph import ArtifactPayload, JobBundle
from backend.models.jobs import IngestPayload, JobModel
from backend.pipeline.cleaning import TRANSCRIBED_SOURCE_TYPES, TextCleaner
from backend.pipeline.extraction import ExtractionService
from backend.pipeline.ingestion import IngestionService, StoredSource
from backend.pipeline.knowledge import KnowledgeCore, KnowledgeExtractor

logger = logging.getLogger(__name__)
```

`ingest_handler.py:1-20`. The import list is the pipeline in order: ingestion
(store it), extraction (read it), cleaning (tidy it), knowledge (distil it).

`TRANSCRIBED_SOURCE_TYPES` on line 15 is the one import that is not a
collaborator but a fact: the frozenset `{"audio", "video", "youtube"}`, defined
at `pipeline/cleaning.py:17`. It lives next to the cleaning rules rather than
here because it is a property of the rules — which sources can survive them —
and this handler is only its user. `_clean` below is where it is read.

```python
MIN_EXTRACTED_CHARS = 50
FORBIDDEN_MARKUP = ("$", "\\(", "\\)", "\\[", "\\]")
```

`ingest_handler.py:22-23`. Two module constants.

`MIN_EXTRACTED_CHARS` is the floor below which the source is considered
unreadable. Fifty characters is not a meaningful lecture; it is what you get from
a scanned PDF with no text layer, or an empty slide deck, or a corrupted upload.
Catching it here produces a message the user can act on ("the file may be
image-only") rather than letting the model produce a confident core from three
words.

`FORBIDDEN_MARKUP` is the LaTeX delimiters. These are checked in the validator
below; the reasoning is with that code.

```python
class CoreValidationError(ValueError):
    """A knowledge core violated the contract every artifact depends on."""
```

`ingest_handler.py:26-27`. Named exception, same reasoning as
`SourceResolutionError`: a `ValueError` subclass so the retry classifier treats
it as permanent, and a distinct name so it reads clearly in logs.

```python
class KnowledgeCoreValidator:
    """
    Checks a core before it becomes the root of a project's graph.

    Only the fields every generator reads are required. A short recording may
    genuinely contain no worked examples, and rejecting the whole core over an
    empty optional list would discard an otherwise usable extraction.

    Markup is rejected everywhere: the core is plain text by contract, and stray
    LaTeX here corrupts every artifact derived from it.
    """
```

`ingest_handler.py:30-40`. Both paragraphs record a decision that was made after
something went wrong.

The first: this validator used to require *every* collection to be non-empty —
concepts, hierarchy, notes, definitions, examples, key facts. A ten-minute
recording that contained no worked examples produced a core with an empty
`examples` list, failed validation, and failed the ingest. The user's upload was
discarded because of a field nothing was going to need. Strictness that costs the
user their work is a bug, not rigour. The required set is now only what every
generator actually reads.

The second: the core is the input to every generator prompt. If it contains
`$\alpha$`, that markup propagates into the quiz, the flashcards, the slides and
the mind map, where it renders as literal dollar signs in a UI that is not
expecting LaTeX. The extraction prompt already says "plain text only, no LaTeX
and no Markdown" (`pipeline/knowledge.py:31`), but a prompt is a request, not a
guarantee. This is the check that makes it a guarantee.

```python
    REQUIRED_FIELDS = ("title", "summary", "concepts", "key_facts")
```

`ingest_handler.py:42`. Four fields. Every generator prompt gets the whole core
serialised as JSON, but these four are what carry the actual substance: without
concepts and key facts there is nothing to write a quiz about.

```python
    def validate(self, core: KnowledgeCore) -> None:
        """Raise if the core is unusable or contains markup."""
        self._require_content(core)
        self._require_plain_text(core)
```

`ingest_handler.py:44-47`. Returns `None`, raises on failure. A validator that
returns a boolean invites a caller who forgets to check it.

```python
    def _require_content(self, core: KnowledgeCore) -> None:
        missing = [name for name in self.REQUIRED_FIELDS if not getattr(core, name)]
        if missing:
            raise CoreValidationError(
                f"Knowledge core has no {', '.join(missing)}. "
                "The source may be too short or contain no teachable content."
            )
```

`ingest_handler.py:49-55`. `not getattr(core, name)` is a truthiness test, so it
catches the empty string for `title` and `summary` and the empty list for
`concepts` and `key_facts` with one expression. All missing fields are collected
before raising, and the second sentence of the message tells the user what to do
about it, which is the part that makes this a good error rather than a correct
one.

```python
    def _require_plain_text(self, core: KnowledgeCore) -> None:
        for path, value in self._text_fields(core):
            if not isinstance(value, str):
                raise CoreValidationError(f"Knowledge core field {path} is not text")
            for token in FORBIDDEN_MARKUP:
                if token in value:
                    raise CoreValidationError(
                        f"Knowledge core field {path} contains markup '{token}'. "
                        "The core must be plain text."
                    )
```

`ingest_handler.py:57-66`. Walks every text field and checks two things.

The `isinstance` check is defensive against a Pydantic field that somehow holds a
non-string; more usefully, it means the `token in value` below cannot raise a
`TypeError`.

`path` is a dotted path like `concepts[3].description`. This is why
`_text_fields` builds tuples instead of just yielding values: when this fires,
the message names the exact field, and you can look at that one field rather than
diffing a whole core.

Both checks raise on the first failure rather than collecting. That is a
different choice from `_require_content` and it is defensible: if one field has
LaTeX in it, the extraction ignored the instruction and the whole core is
suspect, so listing every instance adds nothing.

```python
    @staticmethod
    def _text_fields(core: KnowledgeCore) -> List[Tuple[str, Any]]:
        fields: List[Tuple[str, Any]] = [("title", core.title), ("summary", core.summary)]
```

`ingest_handler.py:68-70`. Flattens the whole nested structure into a list of
`(path, value)` pairs. Starts with the two top-level strings.

```python
        for index, concept in enumerate(core.concepts):
            fields += [(f"concepts[{index}].name", concept.name),
                       (f"concepts[{index}].description", concept.description)]
```

`ingest_handler.py:72-74`. `importance_score` is an int and is skipped — only
text fields are collected.

```python
        for index, section in enumerate(core.section_hierarchy):
            fields += [(f"section_hierarchy[{index}].title", section.title),
                       (f"section_hierarchy[{index}].summary", section.summary)]
            for position, subsection in enumerate(section.subsections):
                prefix = f"section_hierarchy[{index}].subsections[{position}]"
                fields += [(f"{prefix}.title", subsection.title),
                           (f"{prefix}.summary", subsection.summary)]
```

`ingest_handler.py:76-82`. The only nested case. `Section` has `subsections`
(`pipeline/knowledge.py:66`) and `Subsection` has none, so the nesting is exactly
two levels and a hand-written double loop is simpler than a recursive walk.

```python
        for index, note in enumerate(core.notes):
            fields.append((f"notes[{index}].heading", note.heading))
            fields += [(f"notes[{index}].bullets[{position}]", bullet)
                       for position, bullet in enumerate(note.bullets)]
```

`ingest_handler.py:84-87`. `bullets` is a `List[str]`, so the values are the
strings themselves.

```python
        for index, definition in enumerate(core.definitions):
            fields += [(f"definitions[{index}].term", definition.term),
                       (f"definitions[{index}].definition", definition.definition),
                       (f"definitions[{index}].context", definition.context)]

        for index, example in enumerate(core.examples):
            fields += [(f"examples[{index}].description", example.description),
                       (f"examples[{index}].relevance", example.relevance)]

        for index, fact in enumerate(core.key_facts):
            fields += [(f"key_facts[{index}].fact", fact.fact),
                       (f"key_facts[{index}].category", fact.category)]

        return fields
```

`ingest_handler.py:89-102`. The remaining three collections, same pattern. Every
string field on the model is covered — worth checking against
`pipeline/knowledge.py:74-89` if you want to confirm nothing was missed, because
"does this cover every field" is a fair question and the answer is yes.

**Worth knowing.** This is written by hand rather than derived from
`model_dump()` and a recursive walk. A generic walker would be shorter and would
automatically pick up new fields. The trade is that the hand-written version
produces exactly the paths shown and skips non-text fields without a type check
at every node. If asked "would you write it this way again", a reasonable answer
is that a recursive walk over `model_dump()` with an `isinstance(value, str)`
filter would be better as the model grows, and this version is fine at the
current size.

### `IngestHandler`

```python
class IngestHandler(JobHandler):
    """
    Stores a source, extracts its text, cleans it, and distils a knowledge core.

    Ingest produces exactly two artifacts and no edges. The core is the root of
    the project's graph, and provenance back to the source file is carried by
    `created_by_job_id` rather than by an edge, because the core was not derived
    from anything already in the graph.

    Ingest is also the end of the buffered upload's life. The upload endpoint
    stages a copy on disk so a large recording never has to be held in memory,
    and this is the last reader of it; leaving it behind would duplicate every
    ingested file for as long as the machine stays up.
    """
```

`ingest_handler.py:105-118`. Three claims, all checkable.

"Exactly two artifacts and no edges" — see `ingest_handler.py:247-267`. The
source artifact records where the file went; the core artifact holds the
extraction. `edges=[]`.

"Provenance via `created_by_job_id`" — `commit_bundle` writes that column on
every artifact it inserts (`database.py:317`). So both artifacts point at the
same job, and from the job you can read the payload and see the original
filename. An edge would have been the wrong tool: edges mean "this artifact was
*derived from* that artifact", and the core was derived from a file, which is not
a node in the graph.

"The end of the buffered upload's life" — the upload endpoint streams the request
body to a `NamedTemporaryFile` (`_buffer_upload`, `api/routes/projects.py:192`)
rather than reading it into memory, because a 600 MB lecture recording read whole
becomes 600 MB resident and two concurrent uploads on a small machine is an OOM
kill. The staged file then has to be deleted by somebody, and the only code that
knows the ingest has finished is this handler.

```python
    def __init__(
        self,
        ingestion: Optional[IngestionService] = None,
        extraction: Optional[ExtractionService] = None,
        cleaner: Optional[TextCleaner] = None,
        knowledge: Optional[KnowledgeExtractor] = None,
        validator: Optional[KnowledgeCoreValidator] = None,
    ) -> None:
        self._ingestion = ingestion or IngestionService()
        self._extraction = extraction or ExtractionService()
        self._cleaner = cleaner or TextCleaner()
        self._knowledge = knowledge or KnowledgeExtractor()
        self._validator = validator or KnowledgeCoreValidator()
```

`ingest_handler.py:120-132`. **This is the constructor to point at when asked
about dependency injection**, because it is the clearest instance of the pattern
in the codebase.

Five collaborators, all `Optional[X] = None`, each falling back to a default
construction. The pattern buys three things:

*Testability without mocking machinery.* `backend/tests/test_seams.py:255` builds
this handler with `StubIngestion`, `StubExtraction`, `StubCleaner` and
`StubKnowledge` — four small classes defined in the test file at lines 191-233,
none of which inherit from anything. No `unittest.mock`, no patching of module
globals, no monkeypatching import paths. The stubs simply have the right methods.
That is what makes the tests at lines 275-301 possible: they run a full ingest,
end to end, with no network, no file store and no model, and assert on real
behaviour (the staged upload was deleted; the caller's own file was not).

*Substitutability at the seam.* `TestProviderSubstitution` in the same file
(`test_seams.py:60`) demonstrates the same idea one layer down: `RecordingProvider`
implements `LLMProvider` and is passed to `ArtifactGenerator(provider)`, which
neither knows nor cares that it is talking to a script instead of OpenRouter.

*Honest defaults.* Production never passes anything. `JobExecutor.HANDLERS` maps
the job type straight to the class (`job_runner.py:86`) and calls it with no
arguments (`job_runner.py:114`): no wiring, no container, no factory registry.

The cost is real too, and being able to name it is worth more than the pattern
itself:

- **The default is evaluated at construction, not at import.** That is fine here,
  but it does mean `IngestHandler()` reaches out to the model provider
  (`KnowledgeExtractor` calls `get_provider()`), which is part of why
  `JobExecutor.handler_for` caches one instance per type rather than constructing
  per job (`job_runner.py:110-115`). Be accurate about the size of that cost if
  asked: `get_provider` is a process-wide singleton behind a lock
  (`llm/factory.py:31-38`), so the HTTP client is opened once for the process and
  every later construction gets the same object. What a per-job build would
  really waste is the five objects, not five connections. The docstring on
  `handler_for` says "construction opens clients", which is true of the first one
  and loose about the rest.
- **No compile-time guarantee the stub matches, and this one has already
  drifted.** `StubCleaner` (`test_seams.py:223`) defines
  `async def clean(self, text, *, use_model=True)`. The real `TextCleaner.clean`
  no longer takes `use_model` — that argument moved to `clean_transcript` when
  cleaning was split by source type — and `StubCleaner` has no `clean_transcript`
  at all. The staged-upload tests still pass, because they ingest an `md` source,
  which routes to `clean`, and the stub's extra keyword-only argument is simply
  never supplied. So the tests exercise a stub that no longer has the shape of
  the thing it stands for, and nothing said so. A `Protocol` on the cleaner would
  have failed the type check the day the real signature changed; there isn't one.
  This is the honest live example of the cost, and better to volunteer than to be
  shown.
- **The type annotation is a lie about intent.** `Optional[X] = None` reads as
  "this may be absent", when it actually means "this will be constructed for you".
  It is the idiomatic Python way to do it, but it is not self-documenting.

```python
    async def run(self, job: JobModel) -> JobBundle:
        payload = IngestPayload(**job.payload)
```

`ingest_handler.py:134-135`. `job.payload` is a `Dict[str, Any]` read out of a
JSON column. The first thing every handler does is parse it through the Pydantic
model for its job type (`models/jobs.py:36`), which validates the shape and
gives typed attribute access for the rest of the method. If the payload is
malformed, it fails here, on line two, with a Pydantic error naming the field —
not twenty lines later with an unhelpful `KeyError`.

```python
        if payload.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"Unknown source type '{payload.source_type}'. "
                f"Expected one of: {', '.join(sorted(SOURCE_TYPES))}"
            )
```

`ingest_handler.py:137-141`. A second validation of something the API already
validated. `IngestRequest.known_source` (`api/schemas.py:40`) rejects an unknown
`source_type` with a 400 before the job row is ever written.

This is not redundancy for its own sake. The job row is data at rest that outlives
the request that created it, and there is more than one way to get a row into the
`jobs` table — the API, the flow engine, and anything that writes to the database
directly. The handler validating its own input means it is correct regardless of
how the row arrived. Mirror this reasoning at `generate_handler.py:53` and
`refine_handler.py:63`, which do exactly the same thing.

```python
        logger.info("Ingesting %s (%s)", payload.original_name, payload.source_type)

        self.report("storing source", 10)
        source = self._store(payload, str(job.project_id))
```

`ingest_handler.py:143-146`. The first progress report, at 10%. The percentages
across this method are 10, 30, 50, 70, 90 — hand-tuned to feel roughly linear
rather than measured. They are honest about *ordering*, not about time; the
knowledge-core extraction between 70 and 90 usually takes longer than everything
before it combined.

`_store` is called *before* the `try`, which is the subject of its docstring
below.

```python
        try:
            self.report("reading source", 30)
            extracted = await self._read(source, payload.source_ref)
            if len(extracted.text) < MIN_EXTRACTED_CHARS:
                raise RuntimeError(
                    f"Only {len(extracted.text)} characters came out of {payload.original_name}. "
                    "The file may be empty, image-only, or an unsupported format."
                )
```

`ingest_handler.py:148-155`. The floor check. The message gives the actual
character count and three plausible causes, which for the common case — a scanned
PDF with no text layer — tells the user exactly what is wrong with their file.

This raises `RuntimeError`, not a named exception. Slightly inconsistent with the
rest of the file, and harmless: it is not transient by `is_transient`'s rules, so
it will not be retried.

```python
            self.report("cleaning text", 50)
            cleaned = await self._clean(extracted.text, payload.source_type)

            self.report("building knowledge core", 70)
            core = await self._knowledge.extract(cleaned)

            self.report("validating knowledge core", 90)
            self._validator.validate(core)
            logger.info("Knowledge core ready: %s", core.title)
```

`ingest_handler.py:157-165`. The middle of the pipeline. Both `_clean` and
`extract` are awaited — this is the async surface discussed under `base.py:67`.

Line 158 calls `self._clean`, a method on this handler, rather than
`self._cleaner.clean` directly. That indirection is new and it is the fix for a
silent corruption; the method is walked below, after `_store`, in the order it
appears in the file.

`KnowledgeExtractor.extract` is worth being able to describe: under 24,000
characters it makes one call; over that it splits into 12,000-character chunks,
runs them concurrently under `asyncio.gather`, and merges the resulting partial
cores de-duplicating each collection on its natural key
(`pipeline/knowledge.py:103-165`). The reason for chunking is not the context
window — it is that a single request over a whole transcript demonstrably loses
detail towards the end.

Note that `validate` is synchronous. It is pure CPU over in-memory strings, so
there is nothing to await.

```python
        finally:
            self._discard_staged_upload(payload.source_ref)
```

`ingest_handler.py:166-167`. The `finally` is the whole point of the `try`.
Whether the extraction succeeded, the model timed out, or the validator rejected
the core, the staged upload gets deleted.

This is the fix for a leak. `_buffer_upload` unlinked the temp file on every
*failure* path in the upload endpoint, but nothing deleted it after a successful
ingest — so every successfully ingested lecture left a full-size duplicate in
`/tmp` until the machine rebooted. Two named tests cover it, one for each
direction: `test_a_successful_ingest_removes_the_staged_upload`
(`test_seams.py:275`) and `test_a_failed_ingest_removes_the_staged_upload`
(`test_seams.py:284`).

```python
        return self._bundle(job, payload, source, extracted.metadata, core)
```

`ingest_handler.py:169`. Outside the `try`, so it only runs when the block
completed. Nothing has been written to the database at this point and nothing
will be by this handler.

```python
    def _store(self, payload: IngestPayload, project_id: str) -> StoredSource:
        """
        Put a durable copy of the source in the file store.

        Deliberately outside the cleanup block: until this returns, the staged
        upload is the only copy there is.
        """
```

`ingest_handler.py:171-177`. Read the docstring twice, because this is a
correctness argument about ordering, and it is a good thing to be asked about.

If `_store` were inside the `try`, then a failure *during* the copy would hit the
`finally`, which would delete the staged upload — the only copy of the user's
file — while the durable copy was incomplete or absent. The upload would be
irrecoverably gone. Putting `_store` before the `try` means the staged file
survives any failure that happens before a durable copy exists, and is only
eligible for deletion once there is something else to read.

```python
        if payload.source_type == "youtube":
            return self._ingestion.store_youtube(payload.source_ref, project_id)
```

`ingest_handler.py:178-179`. YouTube takes a different path: there is no local
file, so the ingestion service downloads it.

The related security note lives at the API boundary, not here.
`IngestRequest.youtube_ref_is_a_url` (`api/schemas.py:47-63`) rejects a
`source_ref` that is not `http://` or `https://` for a YouTube source, because
yt-dlp given a bare path will happily read a local file — which would turn a
YouTube ingest into an arbitrary file read.

Be precise about what that check is, because its own docstring is: it is a cheap
early rejection and not the guard. It says nothing about where the URL points,
and an `http(s)` URL naming an internal address is an SSRF. The actual
authorisation is `YouTubeUrlGuard` in `backend/pipeline/ingestion.py`, which
resolves the host and checks it immediately before the call that fetches it.

```python
        if not Path(payload.source_ref).is_file():
            raise RuntimeError(
                f"No readable file at {payload.source_ref}. A buffered upload is deleted "
                "once its ingest finishes, so a finished job cannot be re-run; upload again."
            )
```

`ingest_handler.py:181-185`. This message exists because of a confusing
interaction between two correct behaviours. The staged upload is deleted when
ingest finishes. The stale-job reaper requeues jobs stuck at `running`. Put those
together and a job that was reaped after it had actually completed its file work
comes back, finds no file, and fails. Without this message the failure reads as
"file not found" with no explanation; with it, the message tells you it is
expected and what to do.

```python
        return self._ingestion.store_upload(
            payload.source_ref, project_id, payload.original_name, payload.source_type
        )
```

`ingest_handler.py:187-189`. Copies the staged file into the file store under a
project-scoped key and returns a `StoredSource` — key, original name, source type,
size (`pipeline/ingestion.py:43-50`).

```python
    async def _clean(self, text: str, source_type: str) -> str:
        """
        Send the text to the only cleaning rules its source can survive.

        The transcript rules delete every parenthesised and bracketed span,
        which is what `(laughs)` and `[inaudible]` deserve and what `f(x)`,
        `[0,1]`, `O(n log n)` and a bracketed citation do not. Running them over
        a document failed silently: no error, no warning, just a knowledge core
        and every artifact under it built on mangled text. Anything not known to
        have been transcribed is treated as a document, so a source type added
        later is conservative until someone decides otherwise.
        """
        if source_type in TRANSCRIBED_SOURCE_TYPES:
            return await self._cleaner.clean_transcript(text)
        return await self._cleaner.clean(text)
```

`ingest_handler.py:191-205`. Fifteen lines, most of them explanation, and they
describe a bug that produced no error at all.

**What was wrong.** `run` used to call `self._cleaner.clean(extracted.text)` for
every source type, and there was only one `clean`. Its rules were written for
lecture transcripts, and they are still there, unchanged, in
`TRANSCRIPT_NOISE` at `pipeline/cleaning.py:27-32`:

```python
TRANSCRIPT_NOISE = (
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b"),
    re.compile(r"\b[A-Z]{2,}:\s*"),
    re.compile(r"\([^)]*\)"),
    re.compile(r"\[[^\]]*\]"),
)
```

Read those four as a document rather than as speech. The third deletes every
parenthesised span, so `f(x) = 2x` becomes `f = 2x` and `O(n log n)` becomes `O`.
The fourth deletes every bracketed span, so the interval `[0,1]` and the citation
`[Knuth 1998]` disappear entirely. The second deletes any run of two or more
capitals followed by a colon, so `NOTE:`, `CPU:` and `TCP:` go. The first deletes
anything shaped like a timestamp, so `3:14` goes with `12:34`. And then the old
whitespace rule collapsed every newline into a space, which flattened the
`--- Page N ---` markers the PDF reader had just inserted so that the model could
tell one page from the next.

Nothing raised. A maths or computer-science PDF went in, and text with its
notation cut out came back. The knowledge core was built on that, every artifact
was generated from that core, and each one looked plausible. The user got a quiz
about a lecture whose formulae had been deleted before anyone read it.

This is the same failure shape as the locale bug this project already fixed
(walked in `docs/walkthrough/05-llm.md`, "The one-word locale bug"), and it is
worth naming the shape rather than just the instance: an operation whose failure
mode is *plausible output* rather than an exception. There is no stack trace to
find and no alert to fire, so it survives until somebody reads the output
carefully. Two of those in one codebase is a pattern, and the answer to a pattern
is not "be more careful" — it is to make the dangerous path something a caller
has to choose on purpose. That is what the fix does.

**The fix, and the seam choice, which is the interesting part.**
`TextCleaner` now exposes two methods (`pipeline/cleaning.py:78` and `:90`):
`clean(text)` for documents, which is regex-only, conservative, and preserves
newlines so page markers survive; and `clean_transcript(text, *, use_model=True)`
for speech, which is the old behaviour unchanged, destructive rules and model
repair pass included. `_clean` here picks between them.

Two decisions in that sentence are worth defending.

*The handler picks the method; the cleaner does not take a `source_type`.* The
alternative — `clean(text, source_type)` with the branch inside — would have put
knowledge of the project's source taxonomy into a text-processing class, and
would have meant every caller had to have a source type to hand even when the
answer was obvious. Routing is a decision about the job, and the handler is what
knows about the job. The cleaner just offers two named behaviours.

*The plain name `clean` was kept on the SAFE path, deliberately.* This is the
part to say out loud. A caller who does not know what kind of text they are
holding will reach for the method called `clean`, and the worst thing that can
happen to them is that some noise survives. The destructive rules cannot be
reached by accident: they have to be asked for by name, and the name says what
they assume. The class docstring states this as a rule
(`pipeline/cleaning.py:69-72`): *"`clean` is the conservative path and holds the
plain name on purpose."* Naming is doing real safety work there, which is a
better answer than "I added a flag".

*And the default for an unknown type is the conservative one.* The condition is
`if source_type in TRANSCRIBED_SOURCE_TYPES`, not `if source_type not in
DOCUMENT_TYPES`. Written the second way, adding a new source type to
`SOURCE_TYPES` and forgetting to update the cleaner would silently send it
through the destructive path. Written this way, the same oversight sends it
through the safe path and the worst outcome is a timestamp nobody removed. The
docstring says this in its last sentence, and it is the difference between a
default and a *safe* default.

There is a parametrised regression test over all six source types:
`test_only_transcribed_sources_reach_the_transcript_rules`
(`test_pipeline.py:224`), which calls `_clean` with a recording cleaner and
asserts which of the two paths each type took. Two more assert the behaviour
rather than the routing:
`test_a_document_keeps_mathematical_and_bracketed_notation`
(`test_pipeline.py:196`) checks that `f(x) = 2x`, `[0,1]`, `O(n log n)`,
`[Knuth 1998]`, `NOTE:` and `3:14` all survive a document clean, and
`test_a_transcript_still_loses_asides_labels_and_timestamps`
(`test_pipeline.py:209`) checks that the old behaviour was not weakened for the
sources that need it.

```python
    async def _read(self, source: StoredSource, original_path: str):
        if original_path and Path(original_path).exists():
            return await self._extraction.extract(original_path)
        return await self._extraction.extract_stored(source.key)
```

`ingest_handler.py:207-210`. Prefer the original path; fall back to the stored
copy.

Both branches are needed. For an uploaded file, the staged temp file is still on
disk and reading it directly avoids pulling the copy back out of the store. For
YouTube, `source_ref` is a URL — `Path("https://...").exists()` is `False` — so
it takes the second branch and reads what the downloader stored. One expression
handles both.

Note the missing return annotation. It returns an `Extracted`
(`pipeline/extraction.py:28`), which is text plus a metadata dict; annotating it
would have meant another import.

```python
    @staticmethod
    def _discard_staged_upload(source_ref: str) -> None:
        """
        Delete the upload the API buffered for this job, if that is what this is.

        The upload endpoint stages through `tempfile.NamedTemporaryFile`, so a
        staged upload is a regular file sitting directly in the system temp
        directory under the temp-file prefix. A YouTube URL is not a path, and a
        caller naming source material of their own is naming something outside
        that shape; deleting the wrong file here is far worse than leaking one.
        """
        path = Path(source_ref)
        if not path.name.startswith(tempfile.gettempprefix()):
            return
        if path.parent != Path(tempfile.gettempdir()):
            return
        if not path.is_file():
            return

        path.unlink(missing_ok=True)
        logger.info("Discarded the staged upload %s", path.name)
```

`ingest_handler.py:212-232`. This is the most defensive code in the file and the
reasoning is worth stating precisely, because "why three checks" is an obvious
question.

The method is handed `payload.source_ref`, which is a string from a job payload.
For an upload it is a temp path this backend created. But `source_ref` is
caller-supplied in the general case: the `/api/jobs` route accepts an `ingest`
payload with any `source_ref`, so a caller can name any path on the machine. If
this method deleted whatever it was handed, a caller could delete arbitrary files
that the process has permission to remove.

So instead of trusting the input, it shape-matches against what the upload
endpoint actually creates. `tempfile.NamedTemporaryFile` produces a file whose
name starts with `tempfile.gettempprefix()` (usually `tmp`), sitting directly in
`tempfile.gettempdir()`. Three checks:

1. **Name prefix.** Not a temp-file name, not ours.
2. **Parent directory is exactly the temp directory.** `path.parent !=
   Path(tempfile.gettempdir())` — exact equality, not `is_relative_to`, so a file
   in a *subdirectory* of `/tmp` is also refused. It also rules out `../` tricks,
   because `Path.parent` on a path containing `..` will not equal the temp
   directory.
3. **It is a regular file.** Not a directory, not a symlink to a directory, not
   something already gone.

A YouTube URL fails check one. A developer's own file path fails check one or
two. The asymmetry in the last sentence of the docstring is the justification:
leaking a temp file costs disk space; deleting the wrong file costs data. When
uncertain, leak.

`missing_ok=True` on the unlink handles the race where two processes both reached
here — an extra safety net on top of the `is_file` check.

There is a test that this specific guard works:
`test_a_callers_own_file_is_never_deleted` (`test_seams.py:294`), which points
ingest at a file in a pytest `tmp_path` (which is not the system temp directory)
and asserts it survives.

```python
    @staticmethod
    def _bundle(
        job: JobModel,
        payload: IngestPayload,
        source: StoredSource,
        metadata: dict,
        core: KnowledgeCore,
    ) -> JobBundle:
        source_id, core_id = uuid.uuid4(), uuid.uuid4()
```

`ingest_handler.py:234-242`. A `@staticmethod` — it uses none of the handler's
collaborators, only its arguments, which is a small signal that bundle
construction is pure data assembly.

Both ids are minted here, in Python, before anything is written. This is the
mechanic that makes the pure-handler contract possible: the ids have to exist
before the transaction so that edges (in the other handlers) can reference them,
and so the `result` dict can name them.

```python
        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[
                ArtifactPayload(
                    id=source_id,
                    project_id=job.project_id,
                    type=payload.source_type,
                    content={
                        "kind": "source",
                        "storage_key": source.key,
                        "original_name": source.original_name,
                        "size_bytes": source.size_bytes,
                        "extraction": metadata,
                    },
                ),
```

`ingest_handler.py:244-259`. The source artifact. Its `type` is the source type
(`pdf`, `audio`, …), so the canvas can render the right icon. Its content is
metadata only — the bytes live in the file store under `storage_key`, and the
row records where.

`"kind": "source"` is a discriminator so a consumer reading a content blob can
tell what shape it is without consulting the artifact's `type` column. Compare
`"kind": "core"` below and `"kind": "generated"` in the other two handlers.

`extraction: metadata` carries whatever the extractor learned on the way through
— page counts, durations, whether OCR was used. Not read by any generator; useful
when debugging why a core came out thin.

```python
                ArtifactPayload(
                    id=core_id,
                    project_id=job.project_id,
                    type="knowledge_core",
                    content={"kind": "core", "title": core.title, "core": core.model_dump()},
                ),
            ],
            edges=[],
```

`ingest_handler.py:260-267`. The core artifact. `core.model_dump()` serialises
the Pydantic model to a plain dict for JSON storage; `SourceResolver.to_core`
reads it back at `sources.py:158` with `KnowledgeCore(**content["core"])`, which
revalidates on the way in.

`title` is duplicated outside `core` so the canvas can label the node without
parsing the whole core. Denormalisation for the sake of the read path.

`edges=[]` is the claim from the class docstring, in code.

```python
            result={
                "status": "success",
                "source_artifact_id": str(source_id),
                "core_artifact_id": str(core_id),
                "title": core.title,
            },
        )
```

`ingest_handler.py:268-274`. The result dict, stored on the job row and published
as the `job.completed` WebSocket payload (`job_runner.py:145`). The frontend
reads `core_artifact_id` to know which node to drop on the canvas.

Ids are stringified because this becomes JSON and `UUID` is not JSON
serialisable.

**Worth knowing.** `JobExecutor._notify_flow` reads `bundle.result.get("artifact_id")`
(`job_runner.py:149`), and this result dict has no `artifact_id` key — it has
`source_artifact_id` and `core_artifact_id`. So an ingest job notifies the flow
engine with `artifact_id=None`. That is harmless in practice, because
`_notify_flow` returns immediately unless the job has a `flow_run_id`, and ingest
jobs are never created by the flow engine (it only creates `generate` jobs, see
`_queue_job` at `services/flow/engine.py:255-273`). Worth knowing so that the
inconsistency reads as understood rather than accidental.

---

## Part 4 — `backend/handlers/generate_handler.py`

169 lines. The busiest handler: it resolves sources, merges them, generates,
exports, and builds a bundle with one edge per source.

```python
"""Turns one or more source artifacts into a new study artifact."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from backend.handlers.base import JobHandler
from backend.handlers.sources import SourceResolver
from backend.models.artifacts import GENERATED_TYPES
from backend.models.graph import ArtifactPayload, EdgePayload, JobBundle, as_uuid
from backend.models.jobs import GeneratePayload, JobModel
from backend.pipeline.knowledge import Concept, KeyFact, KnowledgeCore
from backend.services.database import Database, get_database
from backend.services.exports import ExportService
from backend.services.generators import ArtifactGenerator
from backend.services.merger import CoreMerger

logger = logging.getLogger(__name__)
```

`generate_handler.py:1-22`. Note `as_uuid` on line 14 — that import is the fix
for a defect discussed below.

```python
class GenerateHandler(JobHandler):
    """
    Resolves sources, merges them into one context, generates, then exports.

    Every source becomes a `derived_from` edge, so a node with three inputs
    records three parents and the graph the user drew is the graph stored.
    """
```

`generate_handler.py:25-31`. The second sentence is the fan-in story. A canvas
node with three incoming edges produces a job whose payload has three
`source_artifact_ids`, and the resulting artifact gets three parent edges. The
provenance in the database is a faithful copy of the picture on screen, which is
what lets the canvas be reconstructed from the database on reload.

```python
    def __init__(
        self,
        database: Optional[Database] = None,
        resolver: Optional[SourceResolver] = None,
        generator: Optional[ArtifactGenerator] = None,
        merger: Optional[CoreMerger] = None,
        exporter: Optional[ExportService] = None,
    ) -> None:
        self._database = database or get_database()
        self._resolver = resolver or SourceResolver(self._database)
        self._generator = generator or ArtifactGenerator()
        self._merger = merger or CoreMerger()
        self._exporter = exporter or ExportService()
```

`generate_handler.py:33-45`. Same injection pattern as `IngestHandler`, with one
detail worth pointing out: line 42 builds the default resolver from
`self._database`, not from a fresh `get_database()`. So injecting a database gets
you a resolver that uses it, without having to inject both. That is what makes
`test_seams.py:173` work:

```python
handler = GenerateHandler(
    database=database,
    generator=ArtifactGenerator(RecordingProvider(model=quiz)),
)
```

Two arguments — a test database and a generator wired to a scripted provider —
and everything else defaults. The test then inserts a real job row, calls
`handler.run(...)`, and asserts on the returned bundle: the artifact's title came
from the fake, and there is exactly one edge. No network, no patching.

`get_database()` is a module-level singleton, which is the "module singleton" half
of the pattern. The handler does not know it is a singleton; it just knows it got
a `Database`.

```python
    async def run(self, job: JobModel) -> JobBundle:
        payload = GeneratePayload(**job.payload)
        source_ids = self._unique(payload.source_artifact_ids)
```

`generate_handler.py:47-49`. Parse the payload, then de-duplicate the source ids
before anything else.

```python
        if not source_ids:
            raise ValueError("source_artifact_ids is required")
        if payload.target_type not in GENERATED_TYPES:
            raise ValueError(
                f"Unknown target type '{payload.target_type}'. "
                f"Expected one of: {', '.join(sorted(GENERATED_TYPES))}"
            )
```

`generate_handler.py:51-57`. Both re-validate things the API checked
(`GenerateRequest.at_least_one_source` at `api/schemas.py:79` and
`known_target` at `:73`). Same reasoning as ingest: the job row is the input, not
the request, and the flow engine writes job rows without going through the
request schema.

Failing before the model call also matters commercially — an unknown target type
that reached `ArtifactGenerator` would fail there anyway
(`generators.py:228`), but only after the resolve and merge had already spent
model calls.

There is a test for the whole path: `test_unknown_target_type_fails_the_job`
(`test_pipeline.py:298`).

```python
        logger.info(
            "Generating %s from %d source(s)%s",
            payload.target_type, len(source_ids), " with instructions" if payload.instructions else "",
        )
```

`generate_handler.py:59-62`. The conditional suffix means the log line
distinguishes a plain generate from a steered one, which is the first thing you
want to know when an artifact came out unexpectedly.

```python
        self.report("loading sources", 20)
        cores = self._resolver.resolve(source_ids, payload.target_type)
```

`generate_handler.py:64-65`. Everything from Part 2 happens here: one query for
all sources, missing-id check, transition check, and each artifact reduced to a
`KnowledgeCore`. Synchronous, because it is only local SQLite reads.

Note that `resolve` is where fan-in becomes concrete. Three ids in, three cores
out, in the order the user wired them.

```python
        self.report("merging sources", 35)
        context = await self.build_context(cores)
```

`generate_handler.py:67-68`. Many cores become one.

```python
        self.report(f"writing {payload.target_type}", 55)
        model = await self._generator.generate(payload.target_type, context, payload.instructions)
```

`generate_handler.py:70-71`. The generation itself. The stage string is
interpolated so the UI shows "writing quiz" rather than a generic "generating".

`ArtifactGenerator.generate` (`generators.py:216`) looks up a `GeneratorSpec` for
the type, appends the user's instructions to the prompt so they take precedence
over the defaults (`_steer` at `generators.py:332`), calls the provider, and
validates the result against a per-type minimum — at least five quiz questions,
at least 200 characters of notes, and so on. Exams take a different path with a
two-stage build and three concurrent batches.

The three positional arguments here are the whole interface between the handler
and generation: what to make, what to make it from, and how the user wants it
steered.

```python
        self.report("saving", 90)
        return self.bundle(job, source_ids, payload.target_type, model, payload.instructions)
```

`generate_handler.py:73-74`. "Saving" is a small lie in the UI's favour — nothing
is saved here, the bundle is built and handed back, and the runner commits it.
Reporting the user-visible phase rather than the internal one is the right call
for a progress label.

```python
    async def build_context(self, cores: List[KnowledgeCore]) -> KnowledgeCore:
        """Collapse several cores into the one the generator reads."""
        if not cores:
            raise ValueError("No knowledge cores to generate from")
        if len(cores) == 1:
            return cores[0]
```

`generate_handler.py:76-81`. Public rather than `_`-prefixed, and the two early
exits are the common cases. The single-source case is by far the most frequent —
one core, generate from it, no merge and no extra model call.

```python
        if all(not core.concepts and core.summary for core in cores):
            return self._concatenate(cores)
```

`generate_handler.py:83-84`. The chained-sources detection, and the most subtle
line in the file.

Recall `SourceResolver._synthetic` (`sources.py:192`): a chained artifact becomes
a core with everything empty except `summary`, which holds the whole flattened
text. So "no concepts and a non-empty summary" is the fingerprint of a synthetic
core. If *every* source has that fingerprint, they are all chained artifacts, and
they should be concatenated rather than merged.

Why it matters: `CoreMerger.merge` compresses each source to at most seven
concepts and seven facts before synthesising (`merger.py:17-19`). Run that over a
chained core and you are compressing the user's notes down to seven bullet
points and throwing away the rest — the exact content they explicitly wired in.

The `all(...)` rather than `any(...)` is deliberate. A mix of one real core and
one chained artifact goes to the LLM merge, which is right: real cores have
structure worth merging, and the merger can handle a summary-heavy source.

This is a valid inference given the current code, because
`KnowledgeCoreValidator.REQUIRED_FIELDS` includes `concepts`
(`ingest_handler.py:42`), so a genuine knowledge core can never have an empty
concepts list. The coupling is implicit and undocumented at the `sources.py` end,
which is the honest criticism of it — if someone relaxed the validator, this
branch would silently start firing for real cores.

```python
        combined = await self._merger.merge(cores)
        if combined.conflict_notes:
            logger.warning("Sources disagree: %s", combined.conflict_notes)
```

`generate_handler.py:86-88`. The real merge, for multiple genuine cores.

`CoreMerger` compresses each source concurrently, then synthesises the summaries;
past three sources the synthesis runs pairwise up a tree so the prompt stays a
bounded size however many sources are wired in (`merger.py:70-116`). The
synthesis prompt explicitly instructs the model that if two sources disagree,
keep both and record the disagreement in `conflict_notes` rather than silently
picking a winner (`merger.py:41`).

Those notes are logged here and then dropped — they are not put in front of the
generator and not surfaced to the user. That is a genuine gap and a fair thing to
volunteer: the system detects that two lectures contradict each other and the
only place that shows up is a server log line.

```python
        return KnowledgeCore(
            title=f"Combined: {', '.join(combined.source_titles)}",
            summary=combined.unified_summary,
            concepts=[
                Concept(name=name, description="", importance_score=7)
                for name in combined.all_concepts
            ],
            key_facts=[KeyFact(fact=fact, category="Combined") for fact in combined.all_facts],
            section_hierarchy=[], notes=[], definitions=[], examples=[],
        )
```

`generate_handler.py:90-99`. The adapter back from `CombinedContext` to
`KnowledgeCore`, because the generator's only input type is a core.

The lossy parts are visible. `CombinedContext.all_concepts` is a list of strings,
while `Concept` needs a name, a description and an importance score — so the
description is empty and the score is a flat `7` for everything. Likewise every
merged fact gets `category="Combined"`. The hierarchy, notes, definitions and
examples are dropped entirely, because merging those across sources was not worth
the tokens.

If asked why 7: it is a mid-high constant chosen so merged concepts are not
ranked below single-source ones, and nothing downstream currently reads the score
except `CoreMerger._structural_summary` (`merger.py:168`), which sorts by it. An
arbitrary constant, and honest to call it that.

```python
    def bundle(
        self,
        job: JobModel,
        source_ids: List[str],
        target_type: str,
        model: BaseModel,
        instructions: Optional[str] = None,
    ) -> JobBundle:
        """Assemble the artifact, its export and one edge per source."""
        artifact_id = uuid.uuid4()
```

`generate_handler.py:101-110`. Not a `@staticmethod`, unlike the ingest version,
because it uses `self._exporter`.

```python
        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
        }
        if instructions:
            content["instructions"] = instructions
```

`generate_handler.py:112-118`. The content blob. `data` holds the serialised
artifact model — this is the key `ArtifactFlattener.flatten` reads at
`sources.py:48`, which is what makes this artifact chainable later.

`instructions` is stored only when present, so the key's absence means "not
steered" rather than "steered with nothing". The frontend uses it to show what
the user asked for on a regenerated artifact.

```python
        export = self._exporter.export(target_type, model, job.project_id, artifact_id)
        if export:
            content["binary"] = export.as_dict()
```

`generate_handler.py:120-122`. Rendering to a file, when the type has a file form.
Exams render to PDF via LaTeX, slides to PPTX, and notes/study guides/cheat
sheets to Markdown (`services/exports/__init__.py:78-83`). Other types return
`None` and get no `binary` key.

The critical property is that this cannot fail the job. `ExportService.export`
wraps everything in `try/except Exception` and logs a warning
(`exports/__init__.py:84-86`). The docstring gives the reasoning: an artifact is
defined by its content, and the file is a convenience, so a missing LaTeX install
should cost the download and not the entire generation the user just waited a
minute for.

The export is written to the file store *here*, inside the handler — which is the
one place where "handlers write nothing" needs a qualifier. Handlers write no
*database* state. Writing a file to the store is idempotent (the key is derived
from the artifact id, which is fresh), and a file left behind by a job that later
fails is an orphan blob, not an orphan graph node. Worth being precise about if
challenged, because someone reading carefully will spot it.

```python
        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[ArtifactPayload(
                id=artifact_id,
                project_id=job.project_id,
                type=target_type,
                content=content,
            )],
```

`generate_handler.py:124-132`. One artifact. Its `type` is the target type, so
`quiz` and `notes` are first-class artifact types in the same table as
`knowledge_core` and `pdf`.

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

`generate_handler.py:133-140`. **One edge per source. This is fan-in in code.**

Three sources produce three `EdgePayload`s, all with the same child. The
`relationship_type` defaults to `"derived_from"` (`models/graph.py:39`). The
`artifact_edges` table has `UNIQUE (parent_artifact_id, child_artifact_id,
relationship_type)` (`database.py:76`) and `commit_bundle` uses `INSERT OR
IGNORE` (`database.py:325`), so a duplicate edge is a no-op rather than an error
— belt and braces on top of `_unique`. There is a test:
`test_multi_input_records_one_edge_per_source` (`test_pipeline.py:254`).

`as_uuid(source_id)` on line 135 is the fix for a specific defect, and it is one
of the better ones to be able to tell. The old code parsed source ids like this:

```python
uuid.uuid4() if isinstance(source_id, str) else source_id
```

inside a bare `except: pass`. Read what that does: given a string id — which is
what every id is, since they come out of a JSON payload — it *discarded* the
value and generated a brand new random UUID. So a malformed id did not fail. It
became a valid-looking id for an artifact that had never existed, and the edge
pointed at nothing. The error then surfaced three layers away, as a dangling
parent on the canvas or an unresolvable source in a later generation, with no
trace of where it came from.

`as_uuid` (`models/graph.py:12-19`) does the opposite: it accepts a `UUID`
unchanged, tries `uuid.UUID(str(value))` otherwise, and on failure raises
`ValueError(f"Not a valid artifact id: {value!r}")`. It fails immediately, at the
point of the bad data, naming the value. The `!r` is deliberate so an empty
string or `None` is visible in the message rather than rendering as nothing.

```python
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "source_count": len(source_ids),
            },
        )
```

`generate_handler.py:141-147`. `artifact_id` is the key `_notify_flow` reads
(`job_runner.py:149`) to record which artifact this flow node produced, so the
node below it knows what to consume. Unlike ingest, this handler is dispatched by
the flow engine, so that key is load-bearing here.

```python
    @staticmethod
    def _concatenate(cores: List[KnowledgeCore]) -> KnowledgeCore:
        """
        Join chained sources rather than summarising them.

        Chained cores carry their whole payload in `summary`, so compressing
        them would discard the very content the user wired in.
        """
        logger.info("Concatenating %d chained sources", len(cores))
        return KnowledgeCore(
            title=f"Combined: {', '.join(core.title for core in cores)}",
            summary="\n\n".join(f"### From {core.title}:\n{core.summary}" for core in cores),
            concepts=[], section_hierarchy=[], notes=[],
            definitions=[], examples=[], key_facts=[],
        )
```

`generate_handler.py:149-163`. The alternative to merging. Every source's full
text, joined with blank lines, each under a `### From <title>:` heading so the
model can tell where one source ends and the next begins.

The result is itself a synthetic-shaped core (empty everything, content in
`summary`), which is consistent with what `_synthetic` produces.

The obvious risk is context length: three long chained artifacts concatenated in
full could overrun the model's window. That is a real limit and the honest answer
is that it is accepted deliberately — losing the user's explicit input is a worse
failure than a long prompt, and the merge path exists for the case where sources
are genuine cores and compression is appropriate.

```python
    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        """The same sources in the order they were wired, each counted once."""
        return list(dict.fromkeys(str(value) for value in values))
```

`generate_handler.py:165-168`. `dict.fromkeys` de-duplicates while preserving
insertion order, since Python 3.7 guarantees dict ordering. `set()` would
de-duplicate and scramble, and the order matters because edges and merge labels
follow it.

The `str(value)` normalises everything to strings so `UUID("abc...")` and
`"abc..."` are recognised as the same source.

Duplicates arise naturally on a canvas: two paths through the graph can converge
on the same upstream node. Without this, that node would be resolved twice, sent
to the merger twice (paying for two summarisation calls on identical content),
and counted twice in `source_count`. Tested at `test_pipeline.py:279`,
`test_duplicate_sources_collapse_to_one_edge`.

### The security hole, and where it is actually fixed

This is the question most likely to be asked about this handler, so it is worth
answering precisely.

**What was wrong.** `create_job` checked that the caller owned the *project* the
job would be written to, and stopped there. It never checked the artifacts named
in `source_artifact_ids`. So a caller could post a `generate` job to their own
project naming another user's artifact ids. The job passed validation, was
queued, and this handler did exactly what it is designed to do: `resolve` fetched
those artifacts by id, `to_core` read their content, the generator wrote a new
artifact from that content, and `bundle` filed it under `job.project_id` — the
attacker's project. A read of somebody else's material, laundered into an
artifact you own.

**Where the fix lives: in the route, not the handler.** `api/routes/jobs.py:57-58`:

```python
    for artifact_id in _source_ids(payload):
        require_project_artifact(artifact_id, request.project_id, user_id, database)
```

`_source_ids` (`jobs.py:142-148`) returns `payload.sources()` for a generate
request and `[payload.source_artifact_id]` for a refine request, and an empty
list for ingest, which names no artifacts. `require_project_artifact`
(`api/deps.py:70`) loads the artifact, 404s if it is missing, checks the caller
owns the project it lives in (403 if not), and then checks it sits in *this*
project (400 if not).

The last of those three is not paranoia. Provenance edges carry a single
`project_id`, so an edge to a parent living in another project would render as a
dangling link on the canvas — a correctness problem on top of the access one.

Note the placement: the check happens *before* the job row is inserted, so a
refused request leaves nothing behind. The tests assert exactly that
(`test_api.py:296`: `assert database.select("jobs", ...) == []`).

**Why the route and not the handler.** Three reasons worth giving.

1. Ownership is a property of the *request*, and by the time a handler runs there
   is no request — only a job row. `user_id` does not exist in the worker's world.
2. Failing at the API returns a 403 the user can see. Failing in the handler
   produces a failed job the user has to go and look at.
3. It is cheaper: refuse before any model tokens are spent.

**And the doors it took three attempts to close.** Fixing `create_job` did not
fix the problem, because the same handler is reachable by other routes:

- `POST /api/projects/{id}/flow/run` takes the canvas *in the request body*. The
  compiler lifts artifact ids out of `artifactNode` nodes into `plan.seed_artifacts`,
  and the engine writes them straight into a generate job's `source_artifact_ids`
  (`_queue_job`, `services/flow/engine.py:255-273`). Same hole, different door. Closed by
  `_require_owned_seeds` (`api/routes/flows.py:35-57`), called from both
  `run_flow` (line 109) and `validate_flow` (line 76) — validate has to refuse
  identically, or it would report a flow as runnable that will be refused.
- **Running with an empty body uses the project's saved canvas**, and
  `canvas_state` is caller-written through `PATCH /api/projects/{id}`. So the
  stored canvas was a third door into the same place. `_require_owned_seeds` runs
  against the compiled plan regardless of where the graph came from, which closes
  it. Test: `test_a_saved_canvas_cannot_smuggle_a_foreign_seed_into_a_run`
  (`test_api.py:357`).
- `POST /api/chat` can queue a refine job for the artifact in view. It checks
  with the same helper at `api/routes/chat.py:111`.

Note the docstring on `_require_owned_seeds` (`flows.py:41-49`): *"Handlers
resolve those ids without an ownership check, which makes this the last point
where naming somebody else's artifact can be refused."* That is the threat model
written into the code — the handler is trusted, so every door into it must not
be.

**The thing to volunteer unprompted.** `resolve_user` (`api/deps.py:14-23`)
returns the same `"local-user"` for every caller, because this deployment has no
identity provider. So today nobody can *be* a second user and none of this is
exploitable. The ownership model is real in the queries and vacuous in practice
until accounts exist. Saying that yourself is the difference between "I found
bugs" and "I understand my own threat model".

---

## Part 5 — `backend/handlers/refine_handler.py`

144 lines, and the simplest of the three: one source, one output, no merge.

```python
"""Rebuilds an existing artifact against a plain-English request."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel

from backend.handlers.base import JobHandler
from backend.handlers.sources import ArtifactFlattener, SourceResolutionError, SourceResolver
from backend.models.artifacts import GENERATED_TYPES
from backend.models.graph import ArtifactPayload, EdgePayload, JobBundle, as_uuid
from backend.models.jobs import JobModel, RefinePayload
from backend.pipeline.knowledge import KnowledgeCore
from backend.services.database import Database, get_database
from backend.services.exports import ExportService
from backend.services.generators import ArtifactGenerator

logger = logging.getLogger(__name__)

MAX_INSTRUCTION_LENGTH = 4_000
```

`refine_handler.py:1-23`. No `CoreMerger` import — there is only ever one source.

`MAX_INSTRUCTION_LENGTH = 4_000` matches the `max_length=4000` on
`RefineRequest.instructions` (`api/schemas.py:91`) and on
`GenerateRequest.instructions` (`:69`). The underscore separator is just
readability. The bound exists because instructions go straight into a prompt, and
an unbounded string there is both a cost problem and a way to swamp the system
instructions.

```python
class RefineHandler(JobHandler):
    """
    Regenerates an artifact with the user's request and the current version in view.

    Refinement appends a new artifact linked back to the old one rather than
    editing in place, so every revision stays visible and nothing already
    exported changes underneath the user.
    """
```

`refine_handler.py:26-33`. The append-not-edit decision, which is the whole
design of this handler.

Three reasons it is right. First, exports: a generated exam already has a PDF in
the file store under a key derived from its artifact id. Editing the artifact in
place would leave the PDF stale, and anyone holding a signed link would download
content that no longer matches. Appending gives the revision its own id and its
own export. Second, provenance: the edge from old to new means the canvas can
show the revision chain, and a user can go back. Third, it composes with the rest
of the system — a revision is just another artifact, so it can itself be refined
or wired into a generator with no special cases.

The cost is storage: every "make it harder" produces a full new artifact plus a
full new export. Accepted deliberately, and there is no garbage collection of
superseded revisions.

```python
    def __init__(
        self,
        database: Optional[Database] = None,
        resolver: Optional[SourceResolver] = None,
        generator: Optional[ArtifactGenerator] = None,
        exporter: Optional[ExportService] = None,
        flattener: Optional[ArtifactFlattener] = None,
    ) -> None:
        self._database = database or get_database()
        self._resolver = resolver or SourceResolver(self._database)
        self._generator = generator or ArtifactGenerator()
        self._exporter = exporter or ExportService()
        self._flattener = flattener or ArtifactFlattener()
```

`refine_handler.py:35-47`. Same pattern again. Note it holds *both* a resolver and
a flattener, and the resolver holds a flattener of its own. That is deliberate:
this handler uses them for two different purposes. The resolver's flattener is
used to build the base core from the artifact; this handler's flattener is used
separately to render the *current version* for the prompt (line 89). They happen
to be different instances and it does not matter, because `ArtifactFlattener` is
stateless.

```python
    async def run(self, job: JobModel) -> JobBundle:
        payload = RefinePayload(**job.payload)
        instructions = payload.instructions.strip()
```

`refine_handler.py:49-51`. Parse, then strip. The strip is why the next check can
be a simple truthiness test — a payload of `"   "` becomes `""`.

```python
        if not instructions:
            raise ValueError("instructions is required: refinement needs something to act on")
        if len(instructions) > MAX_INSTRUCTION_LENGTH:
            raise ValueError(f"instructions must be under {MAX_INSTRUCTION_LENGTH} characters")
```

`refine_handler.py:53-56`. The first check is the one with content behind it.
Generation without instructions is meaningful — write me a quiz. Refinement
without instructions is not: there is no such thing as "revise this" with no
direction, and running it would spend a model call to produce a near-identical
artifact. The message says why, not just what. Tested at
`test_refine_without_instructions_is_rejected` (`test_pipeline.py:352`).

The length check duplicates the API's `max_length`, for the same reason as
everywhere else: the job row can arrive by more than one route, and the chat
route (`api/routes/chat.py:135`) builds a refine payload from a model's output,
not from a validated request body.

```python
        artifact = self._database.get_artifact(payload.source_artifact_id)
        if not artifact:
            raise SourceResolutionError(f"Artifact not found: {payload.source_artifact_id}")
```

`refine_handler.py:58-60`. A direct database read, bypassing `SourceResolver.resolve`
because there is exactly one source and the transition check does not apply here.

**This is the line to point at when discussing the security hole from the
handler's side.** Note what it does not do: it does not check who owns this
artifact, and it does not check the artifact is in `job.project_id`. It just
reads it. And then `_bundle` files the resulting artifact under `job.project_id`
(line 125). That is precisely the shape of the vulnerability — the handler is
trusted with a caller-supplied id, so the check has to happen before the job row
exists. It does, at `api/routes/jobs.py:58` and `api/routes/chat.py:111`. The
test is `test_a_refine_source_from_another_users_project_is_refused`
(`test_api.py:298`).

`SourceResolutionError` is used rather than a bare `ValueError` for consistency
with the resolver — the caller cannot tell whether the id was resolved through
`resolve` or fetched directly, and the error type should not leak that.

```python
        target_type = payload.target_type or artifact.get("type")
        if target_type not in GENERATED_TYPES:
            raise ValueError(
                f"'{target_type}' cannot be refined. "
                f"Refinable types: {', '.join(sorted(GENERATED_TYPES))}"
            )
```

`refine_handler.py:62-67`. `target_type` is optional on the payload
(`models/jobs.py:59`), defaulting to whatever the artifact already is. Refining
notes gives you notes.

Allowing an explicit override means refine can also *convert* — refine a quiz
"as flashcards" and get flashcards with the quiz's content in view. That is what
the chat route uses when the model's intent classifier returns a different type
(`chat.py:129`).

The membership check rules out refining a `knowledge_core` or a raw source
artifact. Both would be meaningless: there is no generator for either type
(`ARTIFACT_MODELS` at `models/artifacts.py:137` has entries only for the eight
generated types), so `ArtifactGenerator.generate` would fail at
`generators.py:228` anyway. Catching it here gives a message that names the
refinable types instead of "Unknown artifact type".

```python
        logger.info("Refining %s artifact %s", target_type, artifact["id"])

        self.report("loading source material", 25)
        context = self._revision_context(artifact)

        self.report(f"revising {target_type}", 50)
        model = await self._generator.generate(target_type, context, instructions)

        self.report("saving revision", 90)
        return self._bundle(job, str(artifact["id"]), target_type, model, instructions)
```

`refine_handler.py:69-78`. Three stages: build the context, generate, bundle.
Shorter than generate's five, because there is no merge and no multi-source
resolve.

The generator call is identical in shape to `generate_handler.py:71` — same
method, same three arguments. Refinement is not a different generation mechanism;
it is the same generator with a different context and the user's instructions in
the steering slot. That is why "make it harder" works at all: `_steer`
(`generators.py:332`) appends the instructions under a header saying they take
precedence over the rules above.

`str(artifact["id"])` normalises the row's id before it becomes an edge parent
and a result field.

```python
    def _revision_context(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """
        Build the core to revise from.

        The current artifact is folded in so the model revises this version;
        without it, "make it harder" produces a different artifact rather than a
        harder version of this one.
        """
```

`refine_handler.py:80-87`. The docstring describes an observed failure, and it is
the clearest example in the codebase of a bug that is not a crash.

An earlier version resolved the artifact to its core and generated with the
instructions attached. The model saw the original lecture material and the words
"make it harder", and produced a harder quiz — about the same material, with
entirely different questions. Nothing errored. The user asked for a harder
version of *their* quiz and got a different quiz. Which is, from their point of
view, the feature not working.

```python
        base = self._resolver.to_core(artifact)
        current = self._flattener.flatten(artifact)
        if not current:
            return base
```

`refine_handler.py:88-91`. Two reads of the same artifact for two different
purposes.

`to_core` gives the material to work from. For a generated artifact this is the
synthetic core built from its own flattened text (`sources.py:160-164`), and for
an artifact that cannot be flattened it walks to the parent core.

`flatten` gives the current version verbatim, to show the model what it is
revising.

If flattening produced nothing, return the base unchanged — a degraded refinement
is better than a failed one, and this only happens for artifact types with no
renderer, which the `GENERATED_TYPES` check above has already mostly excluded.

**Worth knowing.** For a normal generated artifact these two calls produce
overlapping content: `to_core` internally flattens the same artifact and puts the
text in `summary`, then the code below appends the same text again under a
header. So the artifact appears twice in the prompt. That is wasteful in tokens
and arguably helpful in effect — the second copy is explicitly labelled as "the
current version, revise this", which is what gives the model the instruction it
needs. Worth being able to say "yes, I know it appears twice, and the labelled
copy is the one doing the work".

```python
        return base.model_copy(update={
            "summary": (
                f"{base.summary}\n\n"
                "--- CURRENT VERSION OF THE ARTIFACT (revise this) ---\n"
                f"{current}"
            )
        })
```

`refine_handler.py:93-99`. `model_copy(update=...)` is Pydantic's non-mutating
copy-with-changes. Using it rather than assigning to `base.summary` means the
core that came out of the resolver is untouched, which matters because it may
have been constructed from a cached or shared object.

The delimiter line is prompt engineering in the plainest form. The core is
serialised to JSON and handed to the model as context (`generators.py:232`), so
the model sees this text inside the `summary` field. A loud all-caps banner with
an explicit imperative — "revise this" — is what separates "here is the material"
from "here is the thing you are editing". It is stuffed into `summary` rather than
added as a new field because `KnowledgeCore` has a fixed schema and adding a field
for this would change the model that every generator reads.

```python
    def _bundle(
        self,
        job: JobModel,
        source_id: str,
        target_type: str,
        model: BaseModel,
        instructions: str,
    ) -> JobBundle:
        artifact_id = uuid.uuid4()

        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
            "refined_from": source_id,
            "instructions": instructions,
        }
```

`refine_handler.py:101-117`. `"kind": "generated"`, the same discriminator the
generate handler uses — a refined artifact is a generated artifact as far as
every reader is concerned, which is what lets `ArtifactFlattener` handle it with
no special case.

Two extra keys. `refined_from` duplicates information that is already in the edge,
so the frontend can render "revision of …" without querying the edge table.
`instructions` is unconditional here, unlike `generate_handler.py:117` where it is
conditional — a refine always has instructions, because line 53 refused otherwise.

```python
        export = self._exporter.export(target_type, model, job.project_id, artifact_id)
        if export:
            content["binary"] = export.as_dict()
```

`refine_handler.py:119-121`. Identical to `generate_handler.py:120-122`. The new
artifact id means a new storage key, so the previous version's export is
untouched — which is the "nothing already exported changes underneath the user"
claim from the class docstring, in code.

```python
        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[ArtifactPayload(
                id=artifact_id,
                project_id=job.project_id,
                type=target_type,
                content=content,
            )],
            edges=[EdgePayload(
                parent_artifact_id=as_uuid(source_id),
                child_artifact_id=artifact_id,
                project_id=job.project_id,
            )],
```

`refine_handler.py:123-136`. One artifact and exactly one edge — the singular
counterpart to generate's list comprehension. `as_uuid` again, same reasoning as
`generate_handler.py:135`.

The edge is a plain `derived_from`, the same relationship type a generation uses,
even though the semantics are "revision of" rather than "derived from". The
`EdgePayload` model supports a custom `relationship_type` (`models/graph.py:39`)
and this does not use it. The reason is that graph traversal — `_parent_core`,
the flow engine's parent lookup, the canvas renderer — treats all edges alike,
and introducing a second relationship type would mean auditing every one of those
readers. The distinction is preserved in `content["refined_from"]` instead, where
only the code that cares about it looks.

```python
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "refined_from": source_id,
            },
        )
```

`refine_handler.py:137-143`. The result. `artifact_id` so the frontend can open
the new version, `refined_from` so it can show what it replaced. Tested at
`test_refine_appends_a_version_linked_to_the_original` (`test_pipeline.py:330`).

---

## Appendix — a short list of questions and the honest answers

**Why do handlers not write to the database?**
Because model calls fail routinely, and a handler that wrote as it went could
leave an artifact with no edges, or a completed artifact on a job still marked
`running` that the reaper then re-runs. Returning a bundle and committing it in
one transaction makes both impossible.

**Where does fan-in happen?**
The flow engine collects each parent node's produced artifact id
(`_input_artifacts`, `services/flow/engine.py:283-289`) and writes them all into
one generate job's `source_artifact_ids` (`_queue_job`, `:255-273`).
`SourceResolver.resolve` fetches them in one query,
`build_context` collapses them into one core via `CoreMerger`, and `bundle`
emits one `derived_from` edge per source.

**What does `ArtifactFlattener` flatten and why?**
Any generated artifact, back into plain text. It exists because a downstream node
can receive artifacts of mixed types and the generator takes exactly one
`KnowledgeCore`, so the mixed inputs have to be reduced to one shared
representation — and text is the only representation all eight types have.

**Where is the ownership check on source artifacts?**
In the routes: `api/routes/jobs.py:57-58`, `api/routes/flows.py:35-57`, and
`api/routes/chat.py:111`, all through `require_project_artifact` in
`api/deps.py:70`. Not in the handler, because by the time a handler runs there is
no request and therefore no user. The handler is trusted, so every door into it
has to check.

**What is the weakest part of these files?**
Three candidates, all worth naming before being asked. `build_context`'s
chained-source detection depends on an implicit fingerprint — "no concepts and a
non-empty summary" — which `_synthetic` in `sources.py` produces and does not
document (`generate_handler.py:83`); relax the core validator and that branch
starts firing for real cores. `merger.conflict_notes`, the system's own detection
that two sources contradict each other, is logged and then dropped
(`generate_handler.py:88`), so the only place it surfaces is a server log. And
the collaborator seams have no `Protocol`, which is not theoretical:
`StubCleaner` in `test_seams.py:223` still carries a `use_model` argument that
`TextCleaner.clean` no longer has, and the tests pass anyway.

**Two jobs of the same type run at once. What do they share?**
Everything except the progress reporter, and that is deliberate on both counts.
They share the handler instance and all of its collaborators, because
construction builds that whole graph of objects and paying for it per job would
be waste. They
do not share the reporter, because it is the one thing that is per job:
`with_progress` returns `copy.copy(self)` with the reporter set on the copy
(`base.py:37-52`). It used to assign to the shared instance, and the result was
that the job which attached last owned the callback — so a job still in flight
published its progress into another project under another job's id. The
in-process worker pool was affected and Celery was not, because `tasks.py:44`
builds a fresh `JobExecutor` per task, which is also why the tests did not catch
it until one was written that ran two jobs through a single executor
(`test_seams.py:448`).
