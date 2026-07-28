# 10 — Jobs and workers

Files covered, in the order they are walked:

- `backend/services/job_runner.py` — `is_transient`, `JobExecutor`, `WorkerPool` (314 lines)
- `backend/services/dispatcher.py` — picks Celery or the in-process pool (61 lines)
- `backend/services/events.py` — the event bus, Redis or in-process (210 lines)
- `backend/tasks.py` — `run_job`, `drain_queue`, `reap_stale_jobs` (79 lines)
- `backend/celery_app.py` — touched on only far enough to explain dispatch

This is the package that owns the transaction boundary. If an interviewer wants to
find out whether you understand your own system rather than whether you can read
your own README, this is where they will dig. The whole thing rests on one
sentence, and it is worth being able to say it cold:

> A handler does the work and returns a description of what it produced. It never
> writes. The runner takes that description and commits it in a single database
> transaction. So a job either fully happened or fully did not.

Everything else in this document is the machinery that makes that sentence true
when processes crash, when Redis is missing, and when four workers are racing on
the same queue.

---

## Part 1 — one job, end to end, with line numbers

Before walking the files, here is the whole lifecycle traced once. If you get
asked "walk me through what happens when I click generate", this is the answer,
and every step has a place you can open.

### Step 1 — the row is written, and committed, before anything is dispatched

`backend/api/routes/jobs.py:69`

```python
rows = database.insert("jobs", {
    "project_id": request.project_id,
    "type": request.type,
    "status": "pending",
    "payload": stored,
})
```

`Database.insert` opens its own transaction and commits before it returns
(`database.py:239`). By the time line 74 finishes, the job exists on disk with
status `pending`. Nothing has been told about it yet.

The same shape appears everywhere a job is born: `api/routes/chat.py:135`,
`api/routes/projects.py:148`, and inside the flow engine at
`services/flow/engine.py:262`. There is no path that creates a job any other way.

The reason to insist on this order is the one thing a queue built on a message
broker gets wrong by default. If the job existed only as a Redis message, then a
Redis restart, an eviction, or a broker that was simply down at the moment of the
request would destroy the work with no record that it was ever asked for. The user
sees a spinner that never resolves and there is nothing to look at afterwards. As
a row, the job survives every one of those, and `drain_queue` (Part 5) can notice
later that a pending row has no broker message and re-dispatch it.

### Step 2 — dispatch, which is allowed to fail

`backend/api/routes/jobs.py:82`

```python
return JobAccepted(job_id=job_id, dispatch=enqueue(job_id))
```

`enqueue` is `services/dispatcher.py:36`. It returns one of three strings:
`"local"`, `"celery"`, or `"deferred"`. Crucially it does not raise. If the broker
refuses the message, `dispatcher.py:52-54` logs it and returns `"deferred"`, and
the HTTP request still returns 200 with a job id. The row is pending, and pending
rows always get picked up eventually.

For the flow canvas the same discipline is enforced structurally:
`services/flow/engine.py:177-183` is a method literally called `_hand_off` whose
docstring is "Tell the workers about jobs only once their rows are committed", and
it is called at `engine.py:240` — *after* the `with self._database.transaction()`
block that started at line 207 has closed.

### Step 3 — the claim, which is atomic

`backend/services/job_runner.py:160` (targeted) and `job_runner.py:168` (queue head)

```python
job = self._database.claim_job(job_id)
```

The implementation is `services/database.py:276-299`. It runs inside
`_transaction()`, which issues `BEGIN IMMEDIATE` (`database.py:176`). `IMMEDIATE`
takes SQLite's write lock at the start of the transaction rather than lazily on
first write, which means the `SELECT ... WHERE status='pending'` at line 287 and
the `UPDATE ... SET status='running'` at line 294 cannot be interleaved by another
worker. One worker gets the row; every other worker gets `None`.

Without this you get the failure that costs actual money: two workers read the
same pending row, both call the LLM, you pay twice, and then both try to commit an
artifact for the same job. There is a test that pins it with six real threads
draining twenty-four jobs and asserting every job was claimed exactly once
(`tests/test_pipeline.py:448-469`).

`claim_job` also does `attempts=attempts+1` on line 294. Attempts are counted at
claim time, not at failure time. That matters because a worker that dies without
recording anything still burned an attempt, which is what stops the reaper from
recycling a poisoned job forever.

### Step 4 — the handler runs and returns a bundle. It does not write.

`backend/services/job_runner.py:135`

```python
bundle = await asyncio.wait_for(
    handler.run(job), timeout=get_settings().job_timeout_seconds
)
```

`handler.run` is declared at `handlers/base.py:66-68` and returns a `JobBundle`
(`models/graph.py:42-54`): a job id, a project id, a list of artifacts, a list of
edges, and a result dict. That is a *description* of what should be written, not a
write.

You can check the claim rather than asserting it. Grepping the handler package for
`insert(`, `update(`, `delete(` or `commit_bundle` returns nothing. The only
database calls in `backend/handlers/` are reads:
`refine_handler.py:58` (`get_artifact`), `sources.py:140` (`get_artifacts`),
`sources.py:175-176` (`get_parent_edges`, `get_artifact`). `GenerateHandler.bundle`
at `generate_handler.py:101-147` builds the artifact, builds one `EdgePayload` per
source, and returns — it never touches the database.

The reason is a statement about how often this code fails. These handlers make LLM
calls. Upstream rate limits, model timeouts, and schema-validation failures on
generated JSON are not exotic edge cases here, they are the ordinary weather. If
handlers wrote as they went, then the common case — a handler throwing halfway —
would leave an artifact row with no edges, or edges pointing at an artifact that
was never written, and the canvas would render a graph that is not a graph. Making
the handler pure means the failure mode is "nothing happened", which is a state
the rest of the system already knows how to display.

### Step 5 — the commit. This is the transaction boundary.

`backend/services/job_runner.py:138`

```python
self._database.commit_bundle(bundle)
```

One line. That is the entire boundary. `services/database.py:301-339`:

```python
with self._transaction() as connection:
    ...
    for artifact in bundle.artifacts: INSERT OR REPLACE INTO artifacts ...
    for edge in bundle.edges:         INSERT OR IGNORE INTO artifact_edges ...
    UPDATE jobs SET status='completed', result=?, completed_at=? ...
    UPDATE projects SET updated_at=? ...
```

Artifacts, edges, the job's terminal status and the project's timestamp all land
inside one `BEGIN IMMEDIATE ... COMMIT`. Either the graph gained a node, its
parent links, and a completed job row, or it gained none of those.

Two guards sit at the top of that transaction, at `database.py:306-312`. It
re-reads the job's status inside the transaction and raises if the row is gone, or
if the row is already in a terminal state. That is not paranoia: the reaper can
requeue a job whose original worker was merely slow rather than dead, so two
workers really can be holding the same job. The second one to arrive must not
overwrite the first one's committed result. `tests/test_pipeline.py:430-437`
covers the double-commit case.

### Step 6 — publish, then tell the flow engine

`backend/services/job_runner.py:141-149`

```python
for artifact in bundle.artifacts:
    publish(project_id, ARTIFACT_CREATED, {...})
publish(project_id, JOB_COMPLETED, {...})

self._notify_flow(job, artifact_id=bundle.result.get("artifact_id"))
```

Both of these happen strictly after the commit. The ordering is load-bearing. The
frontend reacts to `artifact.created` by fetching the artifact over HTTP; if the
event went out before the commit, that fetch races the transaction and can 404 on
an artifact the user was just told about. Publishing after the commit means every
event the client sees refers to state that is already durable.

This file got that right from the start — `commit_bundle` on line 138 opens and
closes its own transaction, so by line 141 there is nothing open. The flow engine
did not: it published from inside its own write transaction until recently, and the
fix there was an `EventOutbox` that reproduces this same ordering
(`flow/engine.py:27-49`, and `09-flow-engine.md` Part 4). Worth knowing the contrast,
because "why is it safe here and not there" is a fair question and the answer is
just: here the transaction had already closed.

`_notify_flow` (`job_runner.py:223-242`) hands control back to the flow engine,
which marks the node complete and schedules whatever that unblocked. That is the
loop: a completed job schedules the next wave, and those jobs re-enter at step 1.

---

## Part 2 — `backend/services/job_runner.py`

### Header and imports, lines 1-32

```python
"""Executes claimed jobs and commits what they produced."""
```

Line 3, `from __future__ import annotations`, is the usual postponed-evaluation
import; it lets the file write `list[asyncio.Task]` at line 263 without caring
about the Python version. Lines 5-11 pull in `asyncio`, `logging`, `re`,
`traceback`, typing, and `httpx`. `httpx` is imported for one purpose only — its
exception classes, used in the transient tuple below.

Lines 13-30 import settings, the three handlers, the job model, the database, five
event-type constants plus `publish`, `FlowEngine`, and two things that are newer
than the rest: `enqueue` from `dispatcher` on line 20 and the `Dispatch` type alias
from `flow.engine` on line 30. Line 32 is the module logger.

**`enqueue` is imported at module top, and that used to be impossible.** It was
previously imported lazily, inside `_notify_flow`, with a comment explaining that a
top-level import would close the cycle
`job_runner` → `dispatcher` → `celery_app` → `tasks` → `job_runner`. That cycle is
real, but it is broken one level down rather than here: `dispatcher.py` imports
`celery_app` inside `dispatch_mode` (`dispatcher.py:29`) and `backend.tasks` inside
`enqueue` (`dispatcher.py:48`), so importing `dispatcher` itself pulls in nothing
but `logging` and `threading`. With the deferral living in `dispatcher`, this file
can name `enqueue` at the top and use it as a constructor default, which is what
`__init__` now does. If asked, the honest framing is that the lazy import here was
belt on top of braces — the braces are in `dispatcher`.

### The transient exception tuple, lines 34-42

```python
TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)
```

These are the failures where the type alone tells you it is worth trying again. A
socket that timed out, a connection that was refused, a response that was cut off
mid-stream — none of those say anything about whether the request was valid. The
last two matter for a specific case: `asyncio.wait_for` at line 135 raises
`TimeoutError` when a job exceeds `job_timeout_seconds`, so a job that ran too long
classifies as transient and is requeued rather than burned.

### The transient phrase list, lines 44-52

```python
TRANSIENT_PHRASES = (
    "rate limit", "timed out", "timeout", "temporarily unavailable",
    "connection reset", "overloaded", "service unavailable",
)
```

Substring matching on the lowercased message. This exists because the LLM provider
does not hand back typed exceptions — it hands back a `RuntimeError` whose text is
whatever the upstream said. These phrases are the vocabulary of "we are busy, come
back".

### The status-code regex, lines 54-74 — and the bug that produced it

```python
TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")
```

This is the line worth stopping on, and the docstring underneath it at lines 63-66
tells you why:

> Status codes are matched only where they are labelled as one. A bare
> three-digit match would classify any message that happened to contain those
> digits, including artifact identifiers, as retryable.

The original version of this was a bare alternation of the status codes, matching
anywhere in the message. It worked in every hand-written test. What it did not
survive was a real error message. `GenerateHandler` raises
`Source artifacts not found: 429e4567-e89b-12d3-a456-426614174000` when a source
artifact has been deleted. A UUID is thirty-two hex digits; the odds that one of
`408 409 425 429 500 502 503 504` appears somewhere in it are not small. When it
did, a permanently broken job — the artifact does not exist and never will — was
classified as transient, requeued, re-claimed, and re-run, three times, each
attempt failing identically after doing real work. In the test suite this showed
up as roughly one flaky run in six, which is exactly the frequency that wastes the
most time: often enough to keep appearing, rare enough that re-running the suite
makes it "go away".

The fix requires the digits to be *labelled*: preceded by `http`, `status`, or
`code`, with optional whitespace and an optional `:` or `=`. So `HTTP 429`,
`status: 503` and `code=500` all match; the digits inside a UUID do not. The three
regression cases are pinned at `tests/test_pipeline.py:384-391`, and the one at
line 385 is the literal UUID that caused the flake.

The trade-off, and be ready to name it: a provider that returns a message
consisting of the bare number `429` with no label is now classified as permanent
and will not be retried. That was judged the cheaper mistake. Retrying a permanent
failure costs tokens and delays the user's error message by three attempts;
failing a transient one costs one retry the user can trigger themselves.

```python
def is_transient(error: BaseException) -> bool:
```

Line 57. Note the parameter type is `BaseException`, not `Exception`. That is
consistent with the rest of the codebase's stance on `CancelledError` (more on
this below) even though the only caller passes an `Exception`.

Lines 68-69 check the type tuple first, because a type match is cheap and certain.
Lines 71-74 fall back to text: lowercase the message once, then try the regex, then
try the phrase list. Worth noticing that the regex has no `re.IGNORECASE` flag —
it does not need one, because line 71 already lowercased the message.

A small thing an interviewer might poke at: the test case `"503 Service
Unavailable"` at `tests/test_pipeline.py:370` passes, but *not* via the regex —
there is no `http`/`status`/`code` label in front of that `503`. It passes because
`"service unavailable"` is in `TRANSIENT_PHRASES`. The two mechanisms overlap on
purpose; the phrase list is the more forgiving of the two and the regex is the
precise one.

### `class JobExecutor`, lines 77-115

```python
class JobExecutor:
    """
    Runs one job: claim, execute, commit, notify.
    ...
    """
```

The docstring at 78-83 states the invariant: this is the only place a job becomes
committed state.

```python
HANDLERS: Dict[str, Callable[[], JobHandler]] = {
    JobType.INGEST.value: IngestHandler,
    JobType.GENERATE.value: GenerateHandler,
    JobType.REFINE.value: RefineHandler,
}
```

Lines 85-89. A registry keyed by the string value of the job type. The values are
the *classes*, used as zero-argument factories — every handler's `__init__` has
defaults for all its collaborators (see `generate_handler.py:33-45`), which is what
makes `IngestHandler()` valid while still allowing tests to inject fakes.

```python
    def __init__(
        self,
        database: Optional[Database] = None,
        dispatch: Optional[Dispatch] = None,
    ) -> None:
        self._database = database or get_database()
        self._flow = FlowEngine(self._database)
        self._dispatch = dispatch or enqueue
        self._handlers: Dict[str, JobHandler] = {}
```

Lines 91-99, the constructor. `database or get_database()` is the injection seam
used throughout this codebase — tests pass a temp-file database, production passes
nothing. Line 97 builds a `FlowEngine` over the same database handle so step 6 does
not open a second one. Line 99 initialises the per-type handler cache.

**Line 98 is the newer one.** `dispatch` follows exactly the same
constructor-injection pattern as `database`: a caller may supply one, and the
default is the module-level `enqueue`. It was added for `_redispatch` (below), and
it also means `_notify_flow` now hands the flow engine `self._dispatch` rather than
reaching for the module-level `enqueue` directly — so a test that injects a
recording dispatcher sees *every* dispatch this executor makes, whether it came
from a retry or from the flow advancing. `RecordingDispatcher`
(`test_seams.py:398`) is that test double.

```python
    def handler_for(self, job_type: str) -> JobHandler:
        """
        Build one handler per type and reuse it; construction opens clients.

        The instance returned is shared by every job this executor runs, and one
        executor serves the whole worker pool. Callers get a handler to read, not
        one to write to: anything per job comes from `with_progress`, which
        copies rather than mutates.
        """
```

Lines 101-115. Lazy, memoised construction. The first line of the docstring gives
the reason for the cache: constructing a handler constructs an `ArtifactGenerator`,
which constructs the OpenRouter client, which opens an `httpx` client with a
connection pool. Doing that per job would throw away every warm connection. Line
113 raises `ValueError` for an unknown type, which — importantly — is *not*
transient, so a job with a corrupt type fails once instead of three times.

The second paragraph of that docstring is newer, and it is there because the
docstring used to be one line and that one line was misleading. It presented reuse
as a harmless optimisation. It is not harmless; it is a sharing contract, and until
recently the contract was being broken. That is the next section.

### The second concurrency bug: one handler, four workers, one reporter

This is the strongest thing in this file to have ready for "have you found any
other concurrency bugs?", because the answer is yes, in the same class as the flow
engine one, found by going looking rather than by being told.

**The setup.** `WorkerPool.__init__` builds exactly one `JobExecutor` (line 262)
and then starts `worker_concurrency` worker tasks against it — four by default
(lines 272-276). `handler_for` caches one handler instance per job type. So all
four workers, running four different jobs in four different projects, share one
`GenerateHandler`.

**The bug.** `execute` called `.with_progress(lambda ...)` on that shared instance,
and `with_progress` did `self.progress = reporter`. That is a write to an object
three other jobs are in the middle of using. Trace it:

1. Worker 0 claims generate job A in project P1. `with_progress` sets
   `handler.progress` to a closure that publishes to P1 with A's job id.
2. Worker 0 awaits the LLM. It is I/O-bound, so this is where it spends almost all
   of its time.
3. Worker 1 claims generate job B in project P2. Same handler instance.
   `with_progress` overwrites `handler.progress` with a closure for P2 and B.
4. Job A's coroutine resumes and calls `self.report("writing the quiz", 70)`.
5. That progress event is published **to project P2, carrying job B's id.**

The result is cross-project event misattribution. It is not a data-integrity bug —
the `JobBundle` is built entirely from the `job` argument, so what gets committed is
always correct — but a user watching project P2 sees progress for work they did not
start, and the node in P1 that really is at 70% never moves. On a canvas that is a
node stuck at "queued" while a different project's node jumps around.

**Why no test ever saw it.** Celery mode is unaffected, because `backend/tasks.py`
constructs a fresh `JobExecutor()` per task (`tasks.py:44`), so each task gets its
own handler cache. Every test of the executor ran one job at a time. The bug needed
two jobs, in two projects, overlapping in a single process — which is exactly the
local `WorkerPool` deployment and nothing else.

**The fix**, at `handlers/base.py:37-52`:

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

`copy.copy` is a **shallow** copy and that is the whole point of the fix. The
expensive things a handler owns — the generator, the LLM client, the resolver, the
exporter — are copied by reference, so the connection pool is still shared and
`handler_for`'s "construction opens clients" justification still holds. What is not
shared is the thin wrapper object the reporter is written to. One small allocation
per job buys per-job isolation.

**The precondition, and say it before you are asked.** A shallow copy is only safe
if `progress` is the *only* per-job mutable state on a handler. All three were
checked before the change: `IngestHandler`, `GenerateHandler` and `RefineHandler`
each take their collaborators in `__init__` and read everything else off the `job`
argument. If a handler later cached something per job on `self`, the shallow copy
would share it again and the bug would come back in a new shape. That is the
assumption the docstring's last sentence records, and it is why it is written down
rather than left implicit.

**The two docstrings that were lying were fixed in the same pass**, which is worth
mentioning because a wrong docstring is how the next person reintroduces the bug.
`handler_for`'s said reuse was an optimisation and stopped there; it now states the
sharing contract. `JobHandler`'s class docstring (`handlers/base.py:20-33`) said
progress was "injected", which sounds like something handed in per call; it was a
mutation of shared instance state, and it now says so:

> The callback is per job and the instance is not: a handler is built once and
> shared by every worker, so it is attached by `with_progress` on a copy and never
> written to the shared instance.

**Pinned by two tests**, both in `test_seams.py` under `TestProgressAttribution`
(`test_seams.py:417`):

- `test_concurrent_jobs_report_under_their_own_identity` (`test_seams.py:448`) is
  the reproduction. It runs two `execute` calls concurrently in two different
  projects against one shared `PausingHandler` (`test_seams.py:369`) that reports a
  stage, blocks on a `Rendezvous` (`test_seams.py:349`) until *both* jobs have
  reached the same point, then reports again. The rendezvous is what forces the
  interleaving deterministically instead of hoping for it. It then asserts the
  exact set of four `(project_id, job_id, stage)` triples. Against the pre-fix
  code the two "after the pause" events both carry whichever job attached last.
- `test_attaching_a_reporter_leaves_the_shared_handler_alone` (`test_seams.py:476`)
  is the unit-level guard: `with_progress` returns a different object, the shared
  instance has no `progress` in its `vars()` — that is, nothing was written to the
  instance dictionary and it still resolves to the class-level `_ignore` — and
  `handler_for` still returns the same cached instance afterwards, so the copy did
  not accidentally defeat the cache.

### `execute`, lines 117-156 — the core method

```python
async def execute(self, job: JobModel) -> bool:
    """
    Run a job to completion. Returns whether it committed.

    Never raises: a failed job is an outcome, and the worker loop stays up.
    """
```

"Never raises" is the contract. A worker loop that can be killed by one bad job is
not a worker loop. Every failure becomes a recorded outcome and a `False` return.

Lines 123-124 pull the two values used repeatedly into locals. Boring.

```python
publish(project_id, JOB_STARTED, {"job_id": str(job.id), "type": job_type})
```

Line 126. The first thing the client hears after `job.created`. Note it is outside
the `try` — if publishing fails the job should not run, because something is badly
wrong with the process. In practice `publish` swallows its own errors
(`events.py:145`), so this effectively never throws.

```python
handler = self.handler_for(job_type).with_progress(
    lambda stage, percent: publish(project_id, JOB_PROGRESS, {
        "job_id": str(job.id), "stage": stage, "percent": percent,
    })
)
```

Lines 129-133. The handler is given a closure, not the event bus. That is the
seam described in `handlers/base.py:26-32`: the handler knows how to say "I am 55%
through, writing the quiz" and knows nothing about WebSockets, Redis, or event
envelopes. A test can pass a list-appending function and assert on the exact
sequence of stages, which is much easier than asserting on published events.

Note what `handler` is bound to on line 129: **not** the cached instance. It is the
per-job copy `with_progress` returns. Everything from here down — the `wait_for`,
the `run(job)`, every `report()` inside it — runs against an object nothing else
holds a reference to. The closure captures `project_id` and `job.id` from this
call's locals, so the copy and the closure agree by construction. That was the
subject of the previous section, and line 129 is the line to point at when telling
it.

`report()` at `handlers/base.py:54-64` clamps the percentage to 0-100 and swallows
any exception from the reporter, on the grounds that progress is decoration and a
WebSocket dropping mid-run must not fail work that is otherwise succeeding.

```python
bundle = await asyncio.wait_for(
    handler.run(job), timeout=get_settings().job_timeout_seconds
)
```

Lines 135-137. The default is 900 seconds (`core/config.py:137`). The timeout is
here rather than inside the handler because it is a property of the *job*, not of
any one upstream call — the LLM client has its own per-request timeout of 180s
(`config.py:128`) and its own retries, and this is the outer bound on the whole
thing. On expiry `wait_for` cancels the inner coroutine and raises `TimeoutError`,
which `is_transient` classifies as retryable, so a job that hangs gets one more
shot rather than being written off.

```python
self._database.commit_bundle(bundle)
logger.info("Job %s (%s) completed", job.id, job_type)
```

Lines 138-139. The boundary, discussed at length in Part 1 step 5. If an
interviewer asks you to point at the transaction boundary, point at line 138.

Lines 141-147 publish one `artifact.created` per artifact in the bundle, then one
`job.completed` carrying the whole `bundle.result`. The result dict is what
`GenerateHandler` built at `generate_handler.py:141-147`: status, artifact id,
artifact type, source count. That is enough for the frontend to update the node
without a follow-up request in the common case.

```python
self._notify_flow(job, artifact_id=bundle.result.get("artifact_id"))
return True
```

Lines 149-150. `.get` rather than `[...]` because not every job type puts an
artifact id in its result, and a flow node that produced nothing should be reported
as such rather than crashing the notify.

```python
except asyncio.CancelledError:
    raise
except Exception as error:
    self._record_failure(job, job_type, project_id, error)
    return False
```

Lines 152-156. Order matters: the `CancelledError` clause must come first.

Since Python 3.8, `asyncio.CancelledError` inherits from `BaseException`, not
`Exception`, so strictly speaking `except Exception` on line 154 would not catch it
anyway and line 152 is belt-and-braces. It is kept for two reasons. First, it
documents the intent, so nobody later "simplifies" line 154 into
`except BaseException` and silently converts every shutdown into a recorded job
failure. Second, it is the same pattern this codebase uses in the places where it
is genuinely load-bearing.

Those places are the `asyncio.gather(..., return_exceptions=True)` calls. `gather`
with `return_exceptions=True` does not raise — it puts the exception object into
the results list. Because `CancelledError` is a `BaseException`, code that filtered
those results with `isinstance(result, Exception)` let cancellation objects through
as if they were data. That was wrong in three places, and the fixes are all still
visible with comments explaining themselves:

- `services/generators.py:254-268` — a cancelled exam batch would have been passed
  to `list.extend` as though it were a list of questions. Now `CancelledError` is
  re-raised explicitly at line 267 and other failures are dropped.
- `services/merger.py:97-102` — same shape, same fix.
- `pipeline/cleaning.py:149-158` — a cancelled chunk would have been joined into
  the output text, literally putting `CancelledError()` into a transcript. Fixed by
  filtering on `BaseException` at line 155.
- `pipeline/knowledge.py:115-128` — filters results by `isinstance(result,
  KnowledgeCore)` and reports failures via `BaseException`, so it is correct by
  construction.

In *this* file the classification is handled the other way, by clause ordering
rather than by isinstance, at lines 152, 267 and 280. There is one `gather` here,
at line 284, and it is safe because its results are discarded — see `stop()` below.

### `run_job` and `run_next`, lines 158-172

```python
async def run_job(self, job_id: str) -> bool:
    job = self._database.claim_job(job_id)
    if job is None:
        logger.info("Job %s was not claimable; another worker has it", job_id)
        return False
    return await self.execute(job)
```

Lines 158-164. Claim a specific job. This is what the Celery task calls
(`tasks.py:44`). Returning `False` on an unclaimable job rather than raising is what
makes duplicate dispatch harmless — and duplicate dispatch is routine, because
`drain_queue` re-dispatches pending rows without checking whether a broker message
already exists for them.

Lines 166-172, `run_next`: claim whatever is at the head of the queue, oldest
first. This is what the in-process pool calls. It returns `True` if it ran
*anything*, and deliberately ignores `execute`'s return value on line 171 — the
caller only wants to know "was there work?", so it can decide whether to sleep. A
job that failed still counts as work done.

### `_record_failure`, lines 174-203

```python
retryable = is_transient(error)
message = str(error) or error.__class__.__name__
```

Lines 175-176. The `or` on 162 handles exceptions raised with no message, where
`str(error)` is the empty string — without it the user would see a blank error and
the log would say nothing useful.

Lines 178-181 log at ERROR with the full traceback and a `[transient]` marker. The
marker exists so that when you are reading logs you can tell at a glance whether the
job is coming back.

```python
try:
    outcome = self._database.fail_job(job.id, message, retryable=retryable)
except Exception as database_error:
    logger.critical("Could not record the failure of job %s: %s", job.id, database_error)
    outcome = "failed"
```

Lines 183-187. If even recording the failure fails, treat it as failed anyway. The
consequence of falling through here is that the flow engine still gets notified on
line 203, so the canvas node shows an error instead of spinning forever. A stuck
spinner with no explanation is a worse user experience than an error that is
slightly less accurate than it could be.

`fail_job` is `database.py:341-372` and returns a string describing what it did:

- `"pending"` — the failure was retryable and the job still has attempts left
  (`attempts < job_max_attempts`, default 3), so it was set back to `pending` with
  `started_at` cleared.
- `"failed"` — recorded as terminal.
- `"missing"` — the row is gone.
- anything else — the terminal status the job *already* held.

```python
if outcome == "pending":
    logger.info("Job %s requeued for another attempt", job.id)
    self._redispatch(job.id)
    return
```

Lines 189-192. Early return. No `job.failed` event, no flow notification. From the
outside the retry is invisible: the node stays in `running`, and the client sees a
second `job.started` when the retry is claimed. That is correct — the user does not
care that the provider rate-limited you.

**The `_redispatch` call on line 191 is new, and its absence was a real bug.** The
code used to log "requeued for another attempt" and return. `fail_job` had flipped
the row back to `pending` and returned `"pending"`; nobody was told. Every other
place in this codebase is scrupulous about commit-the-row-then-dispatch —
`FlowEngine._hand_off` exists for nothing else, and `create_job` at `jobs.py:69`
then `:82` does the same — and here the dispatch was simply missing. The next
section is about why that mattered and why it took a while to notice.

```python
if outcome not in {"failed", "missing"}:
    logger.warning(
        "Job %s already finished as %s; leaving that outcome alone", job.id, outcome
    )
    return
```

Lines 194-198. This is the losing half of the reaper race. Scenario: worker A
claims a job, is slow, the reaper decides it is dead and requeues the row, worker B
claims it and commits successfully. Worker A then finally times out and calls
`fail_job`, which sees `completed` and returns `"completed"`. Without this branch,
A would publish `job.failed` and tell the flow engine the node errored, over the
top of a node that had already succeeded — the user would watch a finished artifact
turn into an error. `tests/test_pipeline.py:471-479` pins the database half of
this, and `481-489` pins the same thing for a job cancelled by the user.

Note `"missing"` falls through to the failure path rather than being skipped. If the
row was deleted, the flow run still needs to hear something or its node hangs.

Lines 200-203 publish `job.failed` with the message, then notify the flow engine
with the error, which will mark the node failed and skip everything downstream of it
(`flow/engine.py:217-218`).

### `_redispatch`, lines 205-221 — the retry nobody told anyone about

```python
    def _redispatch(self, job_id: Any) -> None:
        """
        Hand a requeued job back to the workers.

        `fail_job` has already committed the row as `pending`, which is the order
        every dispatch in this codebase follows. Without this the retry waits for
        whatever sweeps the queue next, and under Celery that is only the
        periodic drain: take the beat schedule away and the job never runs again.

        A dispatcher that raises is logged rather than propagated, because this
        runs inside the handler for a job that has already failed and `execute`
        promises not to raise.
        """
        try:
            self._dispatch(str(job_id))
        except Exception as dispatch_error:
            logger.error("Could not re-dispatch job %s: %s", job_id, dispatch_error)
```

**What was broken.** A transient failure with attempts left came back from
`fail_job` as `"pending"`, the row really was `pending` on disk, and nothing was
ever sent. The job was correctly requeued and then sat there.

**Why it looked like it worked.** Two accidents, one per mode.

- In local mode, `WorkerPool._worker` (lines 288-302) polls `claim_job` on a timer
  regardless of whether anything was dispatched. `enqueue` is a no-op in local mode
  anyway (`dispatcher.py:44-45`), so the missing call changed nothing at all. Every
  test of the retry path runs in this mode.
- In Celery mode, the `drain-pending-jobs` beat entry (`tasks.py:77`) re-dispatches
  every pending row every 120 seconds. So the retry did happen — up to two minutes
  late, with no explanation for the delay in any log.

**What it costs when the accidents are removed.** Run Celery without `celery beat`
— which is an easy deployment to end up with, since beat is a separate process and
the app functions without it — and a retryable failure strands the job as `pending`
forever. No worker polls in Celery mode. The reaper does not help: `reap_stale_jobs`
only looks at rows with `status='running'`, and this row is `pending`. It is a
silent permanent hang for the one class of failure the retry logic exists to
survive.

**Three things about the implementation worth being able to defend.**

- **It runs after `fail_job` has returned**, not inside it. `fail_job` is in
  `database.py` and knows nothing about transports; keeping dispatch out of it is
  the same separation as everywhere else. And because `fail_job` opened and closed
  its own transaction, the row is committed by the time this runs — commit the fact,
  then announce it, one more time.
- **It uses `self._dispatch`, not the module-level `enqueue`.** That is what the new
  constructor parameter is for. In production they are the same function; in a test
  they are not, which is how the behaviour became assertable at all.
- **A raising dispatcher is caught and logged.** `_record_failure` is called from
  `execute`'s `except` block, and `execute`'s docstring promises it never raises. If
  the broker were unreachable and `_dispatch` threw, propagating it would break that
  promise and take down the worker loop over a failure that had already been
  recorded correctly. Logging it degrades to the old behaviour — the row is pending
  and the drain will find it — which is exactly the right fallback.

**Pinned by `TestRetryDispatch` (`test_seams.py:490`)**, whose class docstring is
the bug report: "A requeued job only runs again if somebody is told it is queued."
Two tests, and the pair is what makes it meaningful:
`test_a_retryable_failure_is_dispatched_again` (`test_seams.py:500`) runs a handler
that raises `TimeoutError`, then asserts the row is `pending` **and** that the
injected dispatcher was called once with that job id; and
`test_a_permanent_failure_is_not_dispatched_again` (`test_seams.py:520`) runs one
that raises `ValueError("target_type is required")` and asserts the row is `failed`
and the dispatcher was called **zero** times. Without the second test the first
could be satisfied by dispatching unconditionally, which would send a message for
every dead job.

`RecordingDispatcher` (`test_seams.py:398`) records the job ids it is given *and*
the status of each row at the moment it is called, which is how
`dispatcher.statuses == ["pending"]` asserts the ordering property rather than just
the fact of the call: the row was already committed as `pending` before anyone was
told about it.

### `_notify_flow`, lines 223-242

```python
if not job.flow_run_id or not job.flow_node_id:
    return
```

Lines 230-231. Most jobs are not part of a flow — a direct "generate a quiz from
this artifact" request has neither field. Those properties are read straight off the
payload dict (`models/jobs.py:78-84`), which is why a plain job simply returns here.

This is where the lazy import of `enqueue` used to live. It is gone; the deferral
now sits inside `dispatcher` itself, and the dispatcher this executor uses is the
one it was constructed with.

```python
self._flow.on_job_finished(
    job.flow_run_id, job.flow_node_id,
    artifact_id=str(artifact_id) if artifact_id else None,
    error=error,
    dispatch=self._dispatch,
)
```

Lines 234-240. Passing the dispatcher in rather than letting the flow engine import
one is the same seam again: the engine can be tested with a `dispatch=list.append`
and never touch Celery. Inside `on_job_finished` (`flow/engine.py:185-241`) the
state read, the state write and the scheduling of the next wave all share one
transaction, and the events, the dispatch and the row returned to this caller all
happen after it closes at line 237.

```python
except Exception as flow_error:
    logger.error("Could not advance flow run %s: %s", job.flow_run_id, flow_error)
```

Lines 241-242. The whole notify is wrapped. A broken flow run must not turn a
successfully committed job into a failed one — the artifact exists, the job row says
`completed`, and that is true regardless of whether the canvas managed to advance.

### `class WorkerPool`, lines 245-314

```python
class WorkerPool:
    """
    Drains the queue inside the API process when Celery is not running.

    A reaper runs alongside the workers, because a process killed mid-job leaves
    its row `running` forever and the node would spin with no error.
    """
```

This is the "no Redis required" story. `uvicorn backend.main:app` with no broker and
no Celery worker is a complete, working install, because the API process runs its own
pool. Started from `main.py:79-84`, stopped from `main.py:89-90`, and only when
`dispatch_mode()` returned `LOCAL`.

```python
IDLE_BACKOFF_START = 0.5
IDLE_BACKOFF_LIMIT = 5.0
REAP_INTERVAL_SECONDS = 60
```

Lines 253-255. Half a second between polls when work has just been seen, growing to
a five-second ceiling when the queue has been empty for a while, and a reaper sweep
every minute.

Lines 257-264, the constructor. Concurrency defaults to `worker_concurrency`, which
is 4 (`config.py:136`). `stale_job_seconds` is 1800 — thirty minutes. Line 262 builds
the single shared `JobExecutor` mentioned in the "Worth knowing" note above. Line 263
holds the task handles, line 264 is the shutdown flag.

```python
async def start(self) -> None:
    if self._tasks:
        return
```

Lines 266-271. Idempotent: starting twice does nothing. Cheap insurance against a
double-lifespan in tests.

```python
self._tasks = [
    asyncio.create_task(self._worker(index), name=f"bee-worker-{index}")
    for index in range(self._concurrency)
]
self._tasks.append(asyncio.create_task(self._reaper(), name="bee-reaper"))
```

Lines 272-276. This is what "the worker pool" actually is: four plain asyncio tasks
on the API's own event loop, plus a fifth for the reaper. Not threads, not
processes. That is the right choice here because the work is overwhelmingly
I/O-bound — waiting on LLM responses — and the genuinely CPU-bound or blocking parts
(ffmpeg, PDF parsing) are already pushed to threads with `asyncio.to_thread`
(`pipeline/media.py:73`, `pipeline/extraction.py:158`). The named tasks are for
debugging: they show up in `asyncio` task dumps as `bee-worker-2` rather than
`Task-17`.

```python
async def stop(self) -> None:
    self._stopping.set()
    for task in self._tasks:
        task.cancel()
    await asyncio.gather(*self._tasks, return_exceptions=True)
    self._tasks = []
```

Lines 279-286. Clean shutdown in three moves: set the flag so any worker between
iterations exits its `while` naturally, cancel every task so any worker blocked in
`await` unwinds now, then gather to wait for all of them to actually finish.

`return_exceptions=True` on line 284 is what stops the gather itself from raising —
each cancelled task contributes a `CancelledError` *object* to the results list.
This is precisely the trap described earlier, and it is harmless here for one
reason only: the result of the gather is discarded. Nothing filters it, nothing
inspects it. If someone later adds `for result in ...: if isinstance(result,
Exception)`, they will reintroduce the bug.

> **Worth knowing.** A job that is mid-flight when `stop()` runs gets cancelled
> inside `execute`, hits line 152, and re-raises. It is never marked failed. Its row
> stays `running` with a `started_at` from before the shutdown. That is intentional
> — the work genuinely was interrupted, not failed — but it means recovery is the
> reaper's job, and the reaper will not touch it until it is older than
> `stale_job_seconds`, thirty minutes by default. So after a restart, in-flight jobs
> take up to half an hour to come back. Lowering `STALE_JOB_SECONDS` trades that
> latency against the risk of reaping jobs that are merely slow.

### `_worker`, lines 288-302

```python
backoff = self.IDLE_BACKOFF_START

while not self._stopping.is_set():
    try:
        if await self._executor.run_next():
            backoff = self.IDLE_BACKOFF_START
            continue
        await asyncio.sleep(backoff)
        backoff = min(backoff * 1.5, self.IDLE_BACKOFF_LIMIT)
```

Lines 289-297. The whole worker. It polls: ask the database for the next claimable
job; if you got one, reset the backoff and immediately ask again, because a busy
queue should be drained at full speed; if you did not, sleep and grow the sleep by
half each time up to five seconds.

Exponential backoff exists so that an idle instance is not hammering SQLite with
four `BEGIN IMMEDIATE` transactions a second all night. Each of those takes the
write lock, so idle polling is not free.

> **Worth knowing.** In local mode `enqueue` is a no-op (`dispatcher.py:44-45`) — it
> does not poke the pool. So a job submitted to a fully idle instance waits up to
> five seconds before a worker notices it. That is the cost of having exactly one
> queueing mechanism (rows in a table) rather than two. If asked how to fix it: have
> `enqueue` set an `asyncio.Event` the workers also wait on, so the pool wakes
> immediately and the backoff only governs the idle case. It has not been done
> because five seconds is invisible next to a job that takes thirty.

```python
except asyncio.CancelledError:
    raise
except Exception as error:
    logger.error("Worker %d error: %s", index, error, exc_info=True)
    await asyncio.sleep(5)
```

Lines 298-302. Same clause ordering as `execute`. Cancellation propagates so `stop()`
works; anything else is logged and the worker sleeps five seconds and carries on. In
principle nothing should reach here, because `execute` never raises — this catches
failures in `claim_job` itself, such as SQLite being locked beyond its 30-second busy
timeout. The five-second sleep is there so a persistently broken database produces a
readable log rather than a million lines a minute.

### `_reaper`, lines 304-314

```python
while not self._stopping.is_set():
    try:
        await asyncio.sleep(self.REAP_INTERVAL_SECONDS)
        reaped = self._database.reap_stale_jobs(self._stale_after)
        if reaped:
            logger.warning("Requeued %d stale job(s)", len(reaped))
```

Lines 305-310. Note the sleep comes *before* the sweep, so there is no reap at
startup — the first sweep is 60 seconds in. Arguably a reap on boot would be useful,
since the most likely time to have stale rows is right after a crash restart; in
practice it makes no difference because those rows will not be older than
`stale_job_seconds` yet anyway.

`reap_stale_jobs` is `database.py:389-421`. It keys off **`started_at`**, which is
set by `claim_job` at the moment of claiming (`database.py:294`). Any row with
`status='running'` and `started_at` older than the cutoff is considered abandoned.
For each one:

- if `attempts < job_max_attempts` (default 3), set it back to `pending`, clear
  `started_at`, and write `error_message='Requeued after worker timeout'`;
- otherwise mark it `failed` with `'Timed out with no attempts left'`.

Both branches append the id to the returned list.

Without any of this, a worker killed by an OOM, a deploy, or Ctrl-C leaves its row
`running` forever. `claim_job` only ever looks at `pending` rows, so nothing will
touch it again, and the canvas node sits in `running` with no error and no result —
the single worst failure mode this system has, because it looks like it is still
working.

Lines 311-314 close with the same cancellation-first pattern. Note the reaper's
generic handler does *not* sleep before continuing, because the loop's own
`sleep(60)` at the top of the next iteration provides the delay.

---

## Part 3 — `backend/services/dispatcher.py`

Sixty-one lines whose entire job is to answer one question: when a job row has been
written, who is going to run it?

```python
"""Hands a queued job to whichever worker transport is running."""
```

Lines 5-9 import `logging` and `threading` — `threading` because this decision is
cached in a module global and Celery workers and FastAPI's threadpool can both reach
it concurrently.

```python
CELERY = "celery"
LOCAL = "local"

_mode: Optional[str] = None
_lock = threading.Lock()
```

Lines 11-15. Two string constants and process-global state.

```python
def dispatch_mode() -> str:
    global _mode
    if _mode is None:
        with _lock:
            if _mode is None:
                from backend.celery_app import broker_available

                _mode = CELERY if broker_available() else LOCAL
                logger.info("Job dispatch: %s", _mode)
    return _mode
```

Lines 18-33. Double-checked locking: the outer `if` is the fast path that avoids
taking the lock on every call, and the inner `if` is the correctness check for two
threads that both got past the outer one. The import on line 29 is inside the
function so that importing `dispatcher` does not drag in Celery — which matters
because `job_runner` imports `dispatcher` and `celery_app`'s import chain leads back
to `job_runner`.

The decision itself is one line: use Celery if the broker answers, otherwise run
everything in this process. `broker_available()` (`celery_app.py:39-55`) requires
three things: `REDIS_URL` is set, `CELERY_ENABLED` is on, and an actual connection
attempt with `max_retries=1, timeout=2` succeeds. The connection check is the point.
Without it, a `REDIS_URL` pointing at a Redis that is not running would put the
process in Celery mode, and every job would go into a queue with nobody draining it.

Because `REDIS_URL` defaults to the empty string (`config.py:134`), a fresh clone with
no `.env` gets `LOCAL`, starts the in-process pool from `main.py:79-84`, and works.
That is the "one command install" claim, and this is the line that makes it true.

> **Worth knowing.** The mode is decided once, at startup, and cached for the life
> of the process. If Redis dies an hour later, the mode stays `CELERY`, every
> `enqueue` returns `"deferred"`, and no work runs until Redis returns — the API does
> not fall back to local execution, because `main.py:79-84` only started a `WorkerPool`
> if the mode was `LOCAL` at boot. That is a deliberate simplification, and the
> answer to "what happens if Redis goes down mid-run" is: rows accumulate as pending,
> nothing is lost, and `drain_queue` picks them all up when the broker comes back.

```python
def enqueue(job_id: str) -> str:
    if dispatch_mode() == LOCAL:
        return LOCAL

    try:
        from backend.tasks import run_job

        run_job.delay(str(job_id))
        return CELERY
    except Exception as error:
        logger.error("Could not enqueue job %s (%s); leaving it pending", job_id, error)
        return "deferred"
```

Lines 36-54. Three paths.

In local mode it does nothing and says so. It does not need to do anything: the
pool is already polling, and the row is already `pending`. This is why the same
`enqueue` function can be handed to the flow engine as its `dispatch` callback in
both modes.

In Celery mode it sends the message. `run_job.delay(...)` is Celery's fire-and-forget
send; the return value (an `AsyncResult`) is discarded, because the job's state lives
in the database, not in Celery's result backend.

If the send throws — broker unreachable, serialisation problem — it logs and returns
`"deferred"`. It does not re-raise. The row is committed and pending; `drain_queue`
runs every two minutes (`tasks.py:15`) and will re-dispatch it. That string is
returned all the way to the HTTP client in `JobAccepted.dispatch`
(`api/routes/jobs.py:82`), so the frontend can see exactly how a job was routed,
which is genuinely useful when debugging a deployment.

```python
def reset() -> None:
    global _mode
    with _lock:
        _mode = None
```

Lines 57-61. Test hook. Cached global state and test isolation do not mix, so there
is an explicit way to clear it.

### `backend/celery_app.py` — only what you need for dispatch

Another document owns this file. Four things matter here:

- Line 17: `broker=settings.redis_url or "memory://"`. The `or` fallback means the
  module imports cleanly with no Redis configured, which it must, because
  `dispatcher` imports it in order to ask whether Redis exists.
- Lines 28-30: `worker_prefetch_multiplier=1`, `task_acks_late=True`,
  `task_reject_on_worker_lost=True`. Take one job at a time, acknowledge only after
  it completes, and requeue if the worker dies. That is Celery's own belt against
  lost work — the reaper is the braces, and it is the one that works when Celery is
  not running at all.
- Line 33: `task_max_retries=0`. Celery does not retry. Retry policy lives in
  `fail_job`, keyed on the `attempts` column, because that is the only place that
  can distinguish transient from permanent and the only place that survives a broker
  restart.
- Lines 31-32: hard time limit is `job_timeout_seconds + 60`, soft limit is
  `job_timeout_seconds`, so the in-process `wait_for` at `job_runner.py:135` is the
  one that normally fires and Celery's limits are the outer safety net.

---

## Part 4 — `backend/services/events.py`

This file replaced per-job HTTP polling. The frontend used to hit
`GET /api/jobs/{id}` on a timer for every running job; with a flow of eight nodes
that is eight pollers, most of them returning "still running", and progress within a
job was invisible because there was nothing to report between `pending` and
`completed`. Now there is one WebSocket per project and the backend pushes.

```python
"""Carries job and flow progress from whichever process runs the work."""
```

Lines 5-15 import `asyncio`, `json`, `logging`, `threading`, the ABC machinery,
datetime, typing and settings. Both `asyncio` and `threading` appear because this
module deliberately straddles both worlds.

```python
QUEUE_SIZE = 256
```

Line 17. The per-subscriber buffer for the in-process bus. See `_deliver` below for
what happens when it fills.

Lines 19-30 are the event vocabulary:

```python
JOB_CREATED = "job.created"
JOB_STARTED = "job.started"
JOB_PROGRESS = "job.progress"
JOB_COMPLETED = "job.completed"
JOB_FAILED = "job.failed"
JOB_CANCELLED = "job.cancelled"
ARTIFACT_CREATED = "artifact.created"
FLOW_STARTED = "flow.started"
FLOW_NODE = "flow.node"
FLOW_COMPLETED = "flow.completed"
FLOW_FAILED = "flow.failed"
CHAT_MESSAGE = "chat.message"
```

Constants rather than string literals so a typo is an `ImportError` at startup
instead of an event nobody ever receives. The dotted namespacing lets the frontend
switch on the prefix.

```python
def make_event(event_type: str, project_id: str, data=None) -> Dict[str, Any]:
    return {
        "type": event_type,
        "project_id": str(project_id),
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }
```

Lines 33-40. The envelope. Every message on the socket has exactly this shape, which
is what lets the frontend have one handler that switches on `type` instead of a
parser per message. Timestamps are UTC and ISO-8601 — timezone-aware, so the browser
can render local time without guessing. `data or {}` avoids a `None` the client would
have to special-case.

### `class EventBus`, lines 43-59

```python
class EventBus(ABC):
    """
    Fans project events out to whoever is listening.

    Publishing is callable from any thread because workers are not async;
    subscribing is an async iterator because WebSocket handlers are.
    """
```

That docstring is the whole design. The asymmetry is not an accident:

- `publish` (lines 53-55) is a plain synchronous method. It has to be, because it is
  called from `JobExecutor`, which under Celery is running inside
  `loop.run_until_complete` on a synchronous worker, and from handler progress
  callbacks that may be deep inside `asyncio.to_thread` work. A publisher must never
  need to know whether it is on an event loop.
- `subscribe` (lines 57-59) is declared to return an `AsyncIterator`, because its
  only consumer is `async for event in get_event_bus().subscribe(project_id)` at
  `api/routes/ws.py:71`.

Line 51, `driver: str = "unknown"`, is a label used only by the health endpoint
(`main.py:172`) and the startup log (`main.py:73-77`) — it is how you tell at a glance
which implementation you got.

### `class InProcessEventBus`, lines 62-127

```python
driver = "memory"

def __init__(self) -> None:
    self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
    self._lock = threading.Lock()
    self._loop: Optional[asyncio.AbstractEventLoop] = None
```

Lines 70-75. A dict from project id to a set of queues — one queue per open
WebSocket, so two browser tabs on the same project each get their own copy. A
`threading.Lock` rather than an `asyncio.Lock` because the mutating callers may be
threads. `_loop` is not known at construction time.

```python
def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
    self._loop = loop
```

Lines 77-79. Called once from `main.py:64-66` during lifespan startup, and only if
the bus is actually the in-process one. The bus is built lazily on first use and may
well be constructed from a non-async context, so it cannot capture the loop itself.

```python
def publish(self, project_id: str, event: Dict[str, Any]) -> None:
    loop = self._loop
    if loop is None or not loop.is_running():
        self._deliver(str(project_id), event)
        return

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is loop:
        self._deliver(str(project_id), event)
        return

    try:
        loop.call_soon_threadsafe(self._deliver, str(project_id), event)
    except RuntimeError:
        logger.debug("Event loop gone; dropping an event for project %s", project_id)
```

Lines 81-99, and this is the fiddliest function in the file. Three cases:

1. **No loop, or the loop is not running** (82-85). Deliver inline. This is the test
   path and the "bus used before the app started" path.
2. **We are already on the bus's loop** (87-94). `asyncio.get_running_loop()` raises
   `RuntimeError` when called off a loop, hence the try. If we are on the right loop,
   deliver directly — hopping via `call_soon_threadsafe` would work but would delay
   every event by a loop iteration for no reason. This is the common case: the local
   `WorkerPool` runs on the same loop as the WebSocket handlers.
3. **We are on a different thread** (96-99). `asyncio.Queue` is not thread-safe, so
   touching the subscriber queues directly from a worker thread would be a data
   race. `loop.call_soon_threadsafe` is the supported way to schedule work onto
   another loop from outside it. The `RuntimeError` catch handles the loop being
   closed between the `is_running()` check and the call — a shutdown race, downgraded
   to a debug log because dropping a progress event during shutdown is not
   interesting.

```python
async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    key = str(project_id)

    with self._lock:
        self._subscribers.setdefault(key, set()).add(queue)

    try:
        while True:
            yield await queue.get()
    finally:
        with self._lock:
            subscribers = self._subscribers.get(key)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(key, None)
```

Lines 101-117. Register a bounded queue, yield from it forever, and deregister in a
`finally`. The `finally` runs when the async generator is closed — which happens
when the WebSocket task is cancelled at `ws.py:64`. Lines 115-117 also delete the
project key once its last subscriber leaves, so `_subscribers` does not grow one
empty set per project visited for the lifetime of the process. That is a real leak in
a long-running server, small but unbounded.

```python
def _deliver(self, project_id: str, event: Dict[str, Any]) -> None:
    with self._lock:
        queues = list(self._subscribers.get(project_id, ()))

    for queue in queues:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Dropping an event for project %s: subscriber is behind", project_id)
```

Lines 119-127. Copy the queue set under the lock, then release the lock before
delivering, so a slow `put_nowait` cannot block a publisher on another thread. Then
`put_nowait` — never `await put` — so a subscriber that has stopped reading can never
apply backpressure to a worker doing real work. When a subscriber falls 256 events
behind, its events are dropped with a warning.

Dropping is the right call, and the reason is in `ws.py`: a client can send
`{"type": "resync"}` (`ws.py:107-108`) and get a fresh snapshot of current job and
flow state. The event stream is an optimisation over polling, not the source of
truth, so losing events degrades responsiveness rather than correctness.

### `class RedisEventBus`, lines 130-172

```python
def __init__(self, url: str) -> None:
    import redis

    self._url = url
    self._client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
    self._client.ping()
```

Lines 135-140. `import redis` inside the constructor so the module imports with no
redis package installed. `decode_responses=True` gives back `str` rather than
`bytes`, so `json.loads` works without an intermediate decode. The `ping()` on line
140 is the whole point of this constructor: it fails loudly, right here, if Redis is
not answering — and `build_bus` catches that and falls back. Without the ping you
would get a bus that looks fine and silently swallows every event.

```python
def publish(self, project_id: str, event: Dict[str, Any]) -> None:
    try:
        self._client.publish(self._channel(project_id), json.dumps(event))
    except Exception as error:
        logger.warning("Redis publish failed for project %s: %s", project_id, error)
```

Lines 142-146. Synchronous, matching the base class. Errors are swallowed with a
warning, which is what makes `publish` safe to call from `job_runner.py:126` outside
the try block: a Redis blip must never fail a job that is otherwise succeeding.

> **Worth knowing, and it is the answer to a question the flow engine raises.**
> This is a **blocking network round trip**. `self._client` is the *synchronous*
> redis client built on line 139 with `socket_timeout=5`, so a `publish` call takes
> however long Redis takes to answer, up to five seconds, on whatever thread called
> it. There is no queue in front of it and no fire-and-forget.
>
> That matters because until recently `FlowEngine` called `publish` from *inside*
> its write transaction. The engine holds two things across that block:
> `Database._write_lock`, a process-wide `threading.RLock`, and an open
> `BEGIN IMMEDIATE`. So a flow node completing did a blocking Redis round trip
> while every other writer in the process — every `claim_job`, every
> `commit_bundle` — waited behind the lock, and a slow broker turned that into a
> five-second stall per event. An eight-node flow finishing published nine events
> that way. The correctness problem (the browser being told about writes that could
> still roll back) is the headline and is told in `09-flow-engine.md` Part 4, but
> this is the runtime cost of the same mistake, and it is the half that gets
> forgotten. Events now go out through an `EventOutbox` after the commit, on a
> thread holding no locks.
>
> The in-process bus does not have this problem: `InProcessEventBus.publish` either
> delivers into an `asyncio.Queue` with `put_nowait` or schedules a
> `call_soon_threadsafe`, neither of which blocks. Which is exactly why the cost
> was invisible in local mode and in every test.

```python
async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
    import redis.asyncio as redis

    client = redis.from_url(self._url, decode_responses=True)
    channel = self._channel(project_id)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
```

Lines 148-154. The publish side is sync and the subscribe side is async, so they use
different clients from the same library. A fresh async client per subscriber — one
Redis connection per open WebSocket. That is fine at this scale and is the thing you
would replace with a single shared subscriber plus in-process fan-out if you ever had
thousands of sockets.

```python
while True:
    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    if message is None:
        continue
    try:
        yield json.loads(message["data"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("Discarding a malformed event on %s", channel)
```

Lines 157-164. The one-second timeout with `continue` is what makes this loop
cancellable: if it blocked forever on `get_message`, cancelling the WebSocket task
would not take effect until the next event arrived. This way there is a cancellation
point at least once a second. `ignore_subscribe_messages=True` filters out the
protocol-level confirmation Redis sends when you subscribe, which would otherwise be
yielded to the client as a garbage event. Malformed payloads are discarded rather
than allowed to kill the stream — Redis pub/sub is a shared channel and nothing
guarantees only this application publishes to it.

```python
finally:
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()
    await client.aclose()
```

Lines 165-168. Full teardown on the way out, in order, so a browser closing a tab
does not leak a Redis connection.

Lines 170-172, `_channel`, namespaces the channel as
`beeprepared:project:{project_id}`. The prefix matters if Redis is shared with
anything else; the project id in the channel is what makes subscription
project-scoped rather than everyone receiving everything and filtering client-side.

### The interchangeability, and why it holds

This is a likely question: "how do you know the two buses behave the same?"

The honest answer is structural rather than tested-by-contract. Both implement the
same two methods with the same signatures; both carry envelopes produced by the same
`make_event`; and the only consumer, `ws.py:71`, writes
`async for event in get_event_bus().subscribe(project_id)` and never asks which one
it has. The only place the difference is visible is the `driver` string on the health
endpoint. Callers of `publish` are equally blind — `job_runner.py` imports the
module-level `publish` helper at line 208 of `events.py` and never sees a bus object
at all.

Where they genuinely differ: the in-process bus only reaches subscribers in the same
process, which is exactly why the mode has to match the dispatch mode. If jobs ran
in a Celery worker and events went through the in-process bus, the worker would
publish into its own empty subscriber dict and the browser would see nothing. Both
decisions key off the same `REDIS_URL`, which is what keeps them in step —
`build_bus` checks `settings.has_redis` at line 182 and `broker_available` checks it
at `celery_app.py:46`.

### Bus construction, lines 175-210

```python
_bus: Optional[EventBus] = None
_lock = threading.Lock()
```

Lines 175-176. Same singleton-plus-lock pattern as `dispatcher`.

```python
def build_bus() -> EventBus:
    settings = get_settings()
    if settings.has_redis:
        try:
            return RedisEventBus(settings.redis_url)
        except Exception as error:
            logger.warning("Redis unavailable for events (%s). Staying in process.", error)
    return InProcessEventBus()
```

Lines 179-187. Try Redis, fall back to memory, log the reason. The fallback catches
the `ping()` failure from the constructor. Nothing here can raise, so the app always
gets a working bus.

Lines 190-198, `get_event_bus`, is double-checked locking again, with a one-time log
of the chosen driver. Lines 201-205, `reset_event_bus`, is the test hook.

```python
def publish(project_id: str, event_type: str, data=None) -> None:
    get_event_bus().publish(str(project_id), make_event(event_type, str(project_id), data))
```

Lines 208-210. The function everything else actually calls. It hides the singleton
and the envelope construction, which is why no caller in the codebase ever mentions
`EventBus` by name.

### What a client actually sees

Worth being able to describe, because it is the visible half of all this
(`api/routes/ws.py`):

1. The handshake carries the auth token as a query parameter (`ws.py:31`), because
   browsers cannot set headers on a WebSocket handshake. It is validated *before*
   `accept()` at lines 42-47, and rejection uses application close codes 4401 and
   4403 mirroring HTTP 401/403.
2. Immediately after accept, a `snapshot` event (`ws.py:52`, built at `ws.py:117-149`)
   with the last 20 jobs and last 3 flow runs. This is what makes a page refresh
   mid-run render correctly instead of showing an empty canvas until the next event
   happens to fire.
3. Then the live stream: `job.started`, `job.progress` (many), `artifact.created`,
   `job.completed` or `job.failed`, and `flow.node` as each canvas node changes
   state.
4. A `ping` envelope every 25 seconds (`ws.py:20`, `ws.py:81-90`) so idle proxies do
   not close the connection.
5. The client may send `{"type": "resync"}` at any time to get a fresh snapshot —
   the recovery path for dropped events and for a laptop coming back from sleep.

---

## Part 5 — `backend/tasks.py`

```python
"""Celery tasks. Each one delegates to the same executor the local pool uses."""
```

That docstring is the design in one line. There is no second implementation of job
execution for Celery. The Celery task is a thin synchronous wrapper around exactly
the `JobExecutor` the in-process pool uses, so the two modes cannot drift.

Lines 5-13 import asyncio, logging, typing, the Celery app, settings and the
database. Note `JobExecutor` is *not* imported at module scope — see line 41.

```python
DRAIN_INTERVAL_SECONDS = 120.0
REAP_INTERVAL_SECONDS = 300.0
```

Lines 15-16. Every two minutes, re-dispatch anything pending; every five minutes,
recover anything stranded. The reaper is slower because reaping is only relevant
after `stale_job_seconds` (1800) has elapsed anyway, so sweeping more often buys
nothing. Note these are Celery Beat intervals and are independent of
`WorkerPool.REAP_INTERVAL_SECONDS = 60` in the local pool — different transports,
different schedulers, same underlying database call.

### `_run`, lines 19-35

```python
def _run(coroutine: Coroutine) -> Any:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        asyncio.set_event_loop(None)
        loop.close()
```

Celery workers are synchronous; the executor is `async`. This bridges them: a fresh
event loop per task, run the coroutine to completion, then tear the loop down
properly.

The teardown is not boilerplate, and the docstring at lines 22-25 says why. Line 32,
`shutdown_asyncgens`, closes any async generators still suspended, running their
`finally` blocks — the same mechanism `InProcessEventBus.subscribe` relies on for
deregistration.

Line 33, `shutdown_default_executor`, is the one that came from an observed problem.
The pipeline offloads blocking work to the default thread pool via
`asyncio.to_thread`: ffmpeg audio conversion at `pipeline/media.py:73`, document
parsing at `pipeline/extraction.py:158`, file copies at `pipeline/extraction.py:173`,
the audio request at `llm/openrouter.py:113`. `asyncio.to_thread` lazily creates a
`ThreadPoolExecutor` owned by the loop, and `loop.close()` does *not* shut it down.
So every ingest task left its executor threads behind, and a Celery worker processing
ingests accumulated threads until the process was restarted. Calling
`shutdown_default_executor` before `close` joins them.

Line 34 clears the thread's current-loop reference so a later `get_event_loop` on
this thread does not hand back a closed loop.

### `run_job`, lines 38-44

```python
@celery_app.task(name="beeprepared.run_job")
def run_job(job_id: str) -> Dict[str, Any]:
    from backend.services.job_runner import JobExecutor

    logger.info("Running job %s", job_id)
    return {"job_id": job_id, "committed": _run(JobExecutor().run_job(job_id))}
```

The explicit `name=` matters: it decouples the routing key from the Python module
path, so `dispatcher` can send `beeprepared.run_job` and a future refactor that moves
the function does not orphan messages already sitting in the queue.

The import on line 41 is inside the function — `job_runner` imports `dispatcher`
which imports `celery_app`, and `celery_app` includes `backend.tasks`. Importing at
module level closes the cycle.

Line 44 constructs a fresh `JobExecutor()` with no arguments, so it resolves the
database itself. That is the whole task: claim, execute, commit, notify — the
identical code path the local pool runs. `committed` in the return value is
`execute`'s boolean, stored in Celery's result backend for one hour
(`celery_app.py:35`). Nothing reads it; the job row is the record.

This is the path that was verified end to end: a job dispatched from the API process
crossing to a separate Celery worker process through Redis, executing there, and its
progress arriving back at the browser over the Redis event bus.

### `drain_queue`, lines 47-61

```python
@celery_app.task(name="beeprepared.drain_queue")
def drain_queue() -> Dict[str, int]:
    """
    Enqueue pending jobs that no Celery task is carrying.

    Jobs are rows first and messages second, so this recovers anything written
    while the broker or the workers were down.
    """
    pending = get_database().pending_job_ids()
    for job_id in pending:
        run_job.delay(job_id)
```

This is the other half of "row before dispatch". Writing the row first only helps if
something later notices rows that never became messages. This is that something.

The ways a job ends up with a row but no message, all real:

- `enqueue` was called while the broker was unreachable and returned `"deferred"`
  (`dispatcher.py:52-54`). The row is pending; no message exists.
- The API process was killed between `database.insert` on `jobs.py:69` and
  `enqueue` on line 82. A tiny window, but a deploy that restarts the API under load
  will eventually land in it.
- Redis lost the message. The default configuration is not persistent, so a Redis
  restart or an eviction under memory pressure drops queued messages. The rows are
  untouched.
- A Celery worker was killed after acknowledging but before finishing — although
  `task_acks_late=True` plus `task_reject_on_worker_lost=True` (`celery_app.py:29-30`)
  is meant to cover that, and the reaper covers what Celery misses.

There used to be a fifth, and it is worth naming because it was the only one on the
list that was a bug rather than an environment failure: a retryable job that
`fail_job` had put back to `pending` was never re-dispatched at all, so `drain_queue`
was the *only* thing that ever picked it up, up to two minutes later. That is fixed
at `job_runner.py:205-221`; this task is now a genuine backstop for that case rather
than the mechanism.

`pending_job_ids` (`database.py:423-428`) is a plain read, oldest first, with no
transaction — it does not need one, because being wrong is safe here.

And that is the key property: `drain_queue` does not check whether a message already
exists, so it will happily re-dispatch a job that is already on its way to a worker.
That is fine, and it is fine precisely because of step 3. Two `run_job` tasks for the
same id both call `claim_job`; the atomic claim means one gets the row and the other
gets `None`, logs "was not claimable; another worker has it" (`job_runner.py:162`),
and returns `False`. The system tolerates duplicate delivery by design, which is what
lets the recovery paths be this simple.

Lines 59-61 log only when something was actually re-dispatched — this task runs 720
times a day and should be silent when there is nothing to say — and return a count
for the result backend.

### `reap_stale_jobs`, lines 64-73

```python
@celery_app.task(name="beeprepared.reap_stale_jobs")
def reap_stale_jobs() -> Dict[str, int]:
    """Return jobs stranded by a dead worker to the queue."""
    reaped = get_database().reap_stale_jobs(get_settings().stale_job_seconds)
    for job_id in reaped:
        run_job.delay(job_id)
```

The Celery-side reaper. Same database call as `WorkerPool._reaper`
(`job_runner.py:308`), same threshold from settings, but with one difference: it also
re-dispatches. It has to. In Celery mode nothing polls the database, so a row set
back to `pending` would sit there until the next `drain_queue` two minutes later. The
local pool does not need this because its workers poll.

> **Worth knowing.** `reap_stale_jobs` in the database returns *every* row it
> touched, including the ones it just marked `failed` for running out of attempts
> (`database.py:413-418`). So line 69 dispatches a `run_job` for those too. The task
> starts, `claim_job` finds a row that is no longer `pending`, returns `None`, and it
> logs and exits. Harmless, one wasted message, but it is the kind of detail an
> interviewer notices and asks about — the answer is that the atomic claim makes
> over-dispatching safe everywhere, and this is one more instance of relying on it.

Lines 71-73 log at WARNING, not INFO. A reap means a worker died; that is worth
noticing in a log even when the system recovered.

### The beat schedule, lines 76-79

```python
celery_app.conf.beat_schedule = {
    "drain-pending-jobs": {"task": "beeprepared.drain_queue", "schedule": DRAIN_INTERVAL_SECONDS},
    "reap-stale-jobs": {"task": "beeprepared.reap_stale_jobs", "schedule": REAP_INTERVAL_SECONDS},
}
```

Registered by assignment at import time. Both are periodic, both only matter when
something has gone wrong, and both are no-ops when nothing has. Note this requires a
`celery beat` process to be running; without beat, the tasks exist but nothing invokes
them, and recovery in Celery mode falls back to whatever Celery's own late-ack
behaviour catches.

That "without beat" case is worth holding on to, because it is how the missing
re-dispatch at `job_runner.py:205-221` was found: asking what still works if you
remove this file's beat schedule. The answer used to be "everything except a
retryable failure, which strands its job as `pending` forever". It is now
"everything, more slowly". A recovery mechanism that other code silently depends on
for correctness is not a recovery mechanism, it is a load-bearing part with no
label on it, and the way to find those is to ask what happens when you take them
away.

---

## The short version, for when you only have a minute

Six steps, and each one answers a specific way the system can break.

| Step | Where | The failure it prevents |
| --- | --- | --- |
| Row committed before dispatch | `jobs.py:69` then `:82` | A broker outage losing the work with no record it was asked for |
| Dispatch may fail, returns a string | `dispatcher.py:36-54` | An enqueue failure turning into a 500 on a job that is already durable |
| Atomic claim | `database.py:276-299` | Two workers running the same job, paying twice, racing on the commit |
| Handler returns, never writes | `handlers/base.py:66`, `job_runner.py:135` | An LLM failure halfway through leaving a half-written graph |
| One transaction | `job_runner.py:138` → `database.py:301-339` | Artifacts without edges, or a completed job with no artifact |
| Notify the flow after commit | `job_runner.py:149` | The next wave being scheduled against state that is not yet durable |

And three fixes worth naming separately, because they are the newest things here and
each one is a good answer to a different question:

| Fix | Where | What was wrong |
| --- | --- | --- |
| Per-job handler copy | `handlers/base.py:37-52`, used at `job_runner.py:129` | One shared handler instance, four workers, `with_progress` mutating it — progress events published to the wrong project under the wrong job id |
| Re-dispatch after a requeue | `job_runner.py:191`, `job_runner.py:205-221` | A retryable failure was put back to `pending` and never announced; it ran again only because something else happened to sweep the queue |
| Events held until commit | `flow/engine.py:27-49` | Flow events published from inside the open write transaction, so a rollback left the browser showing a node the database never recorded |

And the three recovery mechanisms that sit underneath them: failure classification so
transient failures retry and permanent ones do not (`job_runner.py:57-74`), the reaper
so a dead worker's row does not spin forever (`database.py:389-421`), and
`drain_queue` so a row that never became a message still runs (`tasks.py:47-61`).
