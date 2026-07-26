# Interview Guide

Everything needed to walk someone through this backend at a glance, and to show
what changed since the last time it was reviewed.

Read once end to end the night before. Read [the cheat sheet](#cheat-sheet) 60
seconds before the call.

---

## 1. The opener

When they say "tell me about your project", say this. It is about 90 seconds at
a normal speaking pace.

> BeePrepared turns lecture material into study artifacts, but the part I care
> about is the canvas. You drag nodes onto an infinite canvas — a lecture
> recording, a notes generator, a quiz generator — and you wire them together.
> When you press Run, that graph is not a diagram of what happens. It *is* the
> program. The backend compiles your nodes and edges into a DAG, topologically
> sorts it with Kahn's algorithm, assigns each step a wave depth, and dispatches
> wave by wave, so independent branches run concurrently and a node with three
> inputs waits for all three.
>
> Underneath that, everything derives from one thing I call the knowledge core.
> A source gets ingested once and distilled into a structured representation of
> what the material actually says, and every artifact is generated from that
> core rather than from the raw text. That is why the quiz, the notes and the
> mock exam agree with each other instead of each hallucinating separately.
>
> The thing I would point at architecturally is that handlers never touch the
> database. A handler does the work and returns a `JobBundle`; the job runner
> commits it in one transaction. LLM calls fail often enough that a handler
> throwing halfway through is the common case, not the edge case, and it must
> not be able to leave a half-written knowledge graph behind.
>
> I rewrote the backend since I last showed it to you, and the most interesting
> thing I found doing it was a real concurrency bug in my own scheduler — eight
> simultaneous completions were queueing nine jobs where there should have been
> one. Happy to start there, or anywhere.

Four things that opener is doing deliberately:

1. **Leads with the executable canvas.** Everyone at a hackathon built a prompt
   in a box. Almost nobody built a scheduler.
2. **Names a correctness invariant unprompted** (handlers are pure). That is the
   signal that separates "I wired an API" from "I designed a system".
3. **Closes on a measured bug**, not on "I refactored things". A number is a
   claim they can test; "cleaner architecture" is not.
4. **Hands them the steering wheel.** It invites the question you most want to
   answer.

---

## 2. The demo path

Under three minutes. Rehearse it twice. Have the project already ingested — do
not burn 90 seconds watching a transcription bar.

**Before the call:** `docker compose up`, ingest one lecture, build the 8-node
graph on the canvas, leave the browser on that tab. Have a second tab on
`localhost:8000/health`.

| # | Screen | What to say | Time |
|---|---|---|---|
| 1 | `localhost:8000/health` | "Every deployment tells you what it actually resolved to — which database file, which file store, which event bus, whether jobs are running in Celery or in-process, and which model provider. I got tired of guessing why a machine behaved differently." | 15s |
| 2 | Canvas, `/dashboard/canvas?id=…` | "This is a real graph. One source, fanning out into notes and a quiz, then the quiz fanning out into flashcards, an exam and a cheat sheet." Trace the edges with the cursor. | 20s |
| 3 | Draw an edge from a downstream node back to an upstream one, hit Run | "It refuses before spending a single token, and it names the node. Cycles, self-loops, generators with no input and generators with no output type are all rejected at compile time by `FlowCompiler`." Then delete the bad edge. | 25s |
| 4 | Press Run | "First wave dispatches. Everything downstream stays pending until its inputs actually exist. And the scheduling is transactional — that's where I found my best bug, which I'll show you in the code." | 45s |
| 5 | Open the exam artifact, download the PDF | "Exams typeset to real PDF through LaTeX, decks to PPTX. The download goes through an HMAC-signed link with an expiry, because an `<img>` tag or a download manager can't send a bearer token." | 25s |
| 6 | Assistant panel: "make question 3 harder" | "It classifies intent first — refine versus answer. If I'd asked *why* question 3 was hard, it would have answered instead of regenerating. Regenerating something the user didn't ask you to regenerate is worse than one extra clarifying question." | 30s |
| 7 | Point at the two quiz versions in the library | "Refinement appends. The old artifact is still there, linked, because something already exported must not change underneath you." | 15s |

Total: about 2:55. If you are running long, cut step 7 and say the line over
step 6's result instead.

### If the demo breaks live

Do not apologise and start debugging. Say one sentence and move to code.

- **Model returns an error or the key is dead.** "That is actually the case I
  designed for — let me show you." Stop the stack, blank `OPENROUTER_API_KEY`,
  restart. `/health` now reports `"model": "offline"`, and the entire pipeline
  still runs on `OfflineProvider`, which derives artifacts from the source text
  with frequency analysis. The output is dull; every stage executes. That is
  also what lets `docker compose up` work with an empty `.env`.
- **Anything else.** "Let me show you the tests instead —
  `pytest backend/tests -q`, 96 tests, no network, no API keys." That takes a
  few seconds and it exercises real handlers, real transactions, real threads
  and real DAG traversal, so it is a legitimate substitute for the demo rather
  than a consolation prize.
- **Frontend is broken.** Fall back to `curl` against
  `POST /api/projects/{id}/flow/validate`, which returns the compiled plan with
  each step's parents and wave depth without running anything. That is the
  clearest possible view of what the compiler does.

---

## 3. What changed since last time

This is the section that matters. Last time the canvas was decorative and the
backend was one file.

### 3.1 The headline: a concurrency bug, found and measured

**Lead with this.** It is the single most impressive thing in the repository,
because it is a genuine distributed-systems bug in his own code, diagnosed from
first principles, fixed, and *measured*.

The story, in his words:

> `FlowEngine.advance` was supposed to be idempotent, and I had a test asserting
> it was — but the test called it twice in a row on one thread, which proves
> nothing. What was actually happening: `on_job_finished` did a
> read-modify-write of the entire `node_states` JSON blob outside any
> transaction, then called `advance`, which re-read the row, inserted job rows
> for anything now ready, and only wrote the states back at the very end. So
> there is a long window between "I read this step as pending" and "I marked it
> running".
>
> That window gets hit for two reasons. FastAPI runs sync routes on a threadpool
> while the workers run on the event loop, so two callers genuinely overlap. And
> with fan-in, two parents of the same child finishing at once each read the
> blob and each wrote their own completion back over the other's, so the child
> ended up waiting forever on a parent the row no longer remembered finishing.
>
> The fix is that the read, the job insert and the write-back now happen inside
> one `Database.transaction()`, and dispatch moved to *after* the commit — you
> must not tell a worker about a job row that might still roll back. I measured
> it with eight threads on a barrier all reporting the same step complete: nine
> dispatches and nine job rows before, two after. There's a regression test,
> `TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once`,
> and it fails 9≠2 against the old engine.

**The numbers to say out loud: 8 concurrent completions → 9 dispatches and 9 job
rows before, 2 after.** Nine, because eight racing threads each thought they were
first, plus the one legitimate dispatch.

Three follow-ups worth having ready:

- *"Why did your old idempotence test not catch it?"* — Because it tested
  sequential idempotence, which is a different property. `advance` twice in a
  row on one thread genuinely was idempotent. Concurrent idempotence needs
  concurrency in the test, which is why the new one uses a `threading.Barrier`
  to make eight threads arrive at the same instant.
- *"Why is dispatch outside the transaction?"* — `_schedule` returns the job ids
  it queued and `_hand_off` dispatches them only once the transaction has
  committed. Telling a worker about a row that is still uncommitted means the
  worker can look it up and not find it.
- *"How does the nested transaction work?"* — `Database._transaction` checks
  `connection.in_transaction` and joins the open transaction rather than issuing
  a second `BEGIN`, which SQLite rejects. That is what lets `on_job_finished`
  wrap `update`, `insert` and `select` calls that each transact on their own.

There is a second, related fix in the same file worth one sentence: rollback in
`_transaction` is on `BaseException`, not `Exception`. A `CancelledError`
escaping with `BEGIN IMMEDIATE` still open left the connection unusable for
every later write on that thread.

### 3.2 The canvas became executable

Before, the "Run" button POSTed to `/run`, an endpoint that did not exist. Each
generator node independently fetched the project's knowledge core, so the edges
you drew changed nothing — the graph was decoration over a set of independent
buttons.

Now `backend/services/flow/plan.py` and `backend/services/flow/engine.py` make
the graph load-bearing:

- `FlowCompiler.compile()` classifies each node as a **source** (already points
  at an artifact) or a **generator** (will produce one), builds adjacency, and
  runs Kahn's algorithm in `_topological_order`. Each step gets a **wave
  depth** — `depth[child] = max(depth[child], depth[node] + 1)` — so a node sits
  one wave below its *deepest* parent and siblings dispatch together.
- Validation happens before dispatch and every message names the offending node:
  cycles (Kahn terminates with nodes left over), self-loops, generators with no
  input (`_require_inputs`), generators with no output type (`_classify`).
- **Fan-in and fan-out are one mechanism seen from two ends.** A node with three
  incoming edges is dispatched with three `source_artifact_ids`, merged by
  `CoreMerger`. A node with three outgoing edges satisfies three downstream
  steps when it completes.
- The engine holds **nothing in memory between calls**. Everything lives in the
  `flow_runs` row, because the job that unblocks a step may finish in a
  different process from the one that started the run.
- A failed step marks its whole downstream subtree `skipped` rather than leaving
  it `pending` forever — including the case where a step's inputs produced no
  artifacts at all, which previously hung the run with no error anywhere.

### 3.3 Security: four holes found auditing my own API

All four were in `backend/api/`. The framing matters: these were found by going
back over his own code looking for them.

| Hole | What it gets you | The fix |
|---|---|---|
| **`create_job` never checked the source artifacts.** It checked that you owned the *project* and stopped there. | Queue a generate or refine naming artifact ids from someone else's project. The handler resolves them, reads their content, and writes it into a new artifact in *your* project — a clean cross-tenant read, laundered through the generator. | Every source id now goes through `require_project_artifact` before the row is written: it asserts you own the artifact *and* that it lives in the project you named. `_source_ids` extracts them per request type. |
| **`deps.py` used `if owner and owner != user_id`.** | A project with a NULL `user_id` was readable by anyone, while `list_projects` filtered on `user_id` and hid it. Read said yes, list said no — the two disagreeing is how this kind of hole survives review. | `require_project` is now `if project.get("user_id") != user_id`. Absent ownership is denial, not permission. |
| **`update_artifact` merged client `content` wholesale.** | Rewrite `content.binary.storage_path` to any key in the store, then call `/download` and have the server sign a valid link to it. Escalation through the *export metadata*, not through the file server. | The `binary` block is renderer-owned. `update_artifact` drops whatever the client sent and restores it from the existing row, so the storage key is never client-writable. |
| **`IngestRequest` with `source_type: "youtube"` and a filesystem `source_ref`** went straight to `yt_dlp.extract_info`, which reads local files as happily as URLs. | Arbitrary local file read, dressed as a video download. | A `model_validator` on `IngestRequest` requires `http://` or `https://` for youtube sources. |

The line to say if they ask how he found them: *"I went back through the API
looking specifically for places where I'd checked the obvious thing and stopped.
Three of the four are that exact shape — I checked the project and forgot the
artifact, I checked the owner and forgot that NULL isn't a match, I validated the
type and forgot the value."*

### 3.4 The other defects worth naming

| # | What was broken | Why it mattered | What he did |
|---|---|---|---|
| 1 | **Effective concurrency was 1.** Async handlers called the *synchronous* LLM client, blocking the event loop for the entire model call. | Worker count was decorative. Four workers and one worker performed identically. | Generation is async end to end. The exam's three question batches run under `asyncio.gather` in `ArtifactGenerator._exam`. |
| 2 | **Authentication bypass.** Any request whose `Authorization` header merely *contained* the substring `mock-token` was accepted as a fixed user, in every deployment. | A test convenience that shipped. The one he is least proud of and most willing to talk about. | Removed. `resolve_user` returns one documented local user; ownership is recorded per project and checked on every read, so there is exactly one seam to replace when accounts arrive. |
| 3 | **Structured-output drift.** Pydantic emits nested models as `$defs` + `$ref`. Providers accept that but cannot enforce it strictly, and a model handed a reference-heavy schema stops treating field bounds as binding — one mind map ran a single string field to 100k characters and failed three retries. | Silent, expensive, and it looked like the model "just being bad". It was the schema. | `strict_schema()` in `backend/llm/schema.py` inlines every `$ref`, sets `additionalProperties: false`, marks every object fully-required, and the request sends `strict: true`. Same tree, two-second response. |
| 4 | **Retry classification matched bare status codes** anywhere in the error text. | `"Source artifacts not found: 429e4567-e89b-…"` — the digits are part of a UUID — was retried as transient. Roughly one flaky test run in six, and in production it paid three times for a request that could never succeed. | `TRANSIENT_STATUS` matches a code only where it is *labelled* as one. Named regression test: `TestRetryPolicy::test_status_digits_inside_identifiers_do_not_trigger_a_retry`. |
| 5 | **`RETRYABLE_STATUS` was inert.** Every HTTP error was retried identically. | A 401 from a rejected key burned three full attempts, and the actionable truncation message — "raise `LLM_MAX_OUTPUT_TOKENS`" — never reached the user, because it was retried away and replaced by a generic "failed after 3 attempts". | A `PermanentFailure` class, with `TruncatedResponse` as a subclass. `_checked` raises it for any non-retryable 4xx/5xx and `_send` re-raises it immediately instead of retrying. |
| 6 | **`fail_job` had no terminal guard.** | A job reclaimed by the reaper runs twice. The loser finishing late flipped a `completed` job to `failed`, and the flow engine then skipped a subtree that had already succeeded. | `fail_job` returns the existing terminal status untouched, and `_record_failure` leaves that outcome alone rather than notifying the flow. Two tests: a late failure cannot undo a committed result, or a cancellation. |
| 7 | **Idempotency returned *completed* jobs.** | "Regenerate" silently handed back the old artifact. It looked exactly like a broken button, and the logs said success. | `_find_in_flight_duplicate` deduplicates only `pending` and `running`, and returns `None` immediately for a steered request, because different instructions are different work. |
| 8 | **No stale-job reaper.** A worker killed mid-job left its row `running` forever, and `claim_job` skips running rows. | The node spun indefinitely with no error ever surfacing. The worst failure mode, because it is invisible. | `reap_stale_jobs()` requeues rows stuck past `STALE_JOB_SECONDS`, or fails them if attempts are exhausted. Run by `WorkerPool._reaper` locally and a Celery beat task otherwise. |
| 9 | **Source ids parsed as `uuid.uuid4() if isinstance(x, str) else x` inside a bare `except: pass`.** | A malformed id became a *fresh random* id, which became a lookup for an artifact that had never existed. The error surfaced three layers from its cause. | `as_uuid()` parses and raises, naming the offending value. |
| 10 | **`ALLOWED_GENERATIONS` was checked and the failure branch was `pass`.** | The type map documented a rule it did not enforce. A comment pretending to be a constraint is worse than no constraint. | `ALLOWED_TARGETS`; `_check_transition` raises, listing what *is* allowed. |
| 11 | **CORS was `allow_origins=["*"]` with `allow_credentials=True`.** | Browsers reject that combination outright, so there was effectively no CORS — it only ever worked same-origin. | Explicit origin list from settings, plus an `allow_origin_regex` for localhost. |
| 12 | **Uploads were read whole into memory**; a 600 MB recording became 600 MB resident. | Two concurrent uploads on a small box is an OOM kill, not a slow request. | `_buffer_upload` streams in chunks and enforces the limit *as it goes*. `IngestHandler` deletes the staged file in a `finally` — see [3.5](#35-also-fixed). |
| 13 | **The knowledge-core validator required every collection to be populated.** | A short recording with no worked examples failed ingest, discarding an otherwise usable extraction. Strictness that costs the user their upload is a bug. | `REQUIRED_FIELDS` is now only the fields every generator actually reads. Markup rejection stayed — stray LaTeX in the core corrupts everything derived from it. |

### 3.5 Also fixed

A family of bugs with one root cause: **things that were not `Exception`, and
things that should not have been on the event loop.**

- **`asyncio.CancelledError` is a `BaseException`, not an `Exception`.** Under
  `gather(return_exceptions=True)` it comes back as a *value*, so an
  `isinstance(result, Exception)` check misses it. In three places a cancelled
  task was treated as a successful result — most visibly in the text cleaner,
  where a cancelled chunk was `" ".join()`'d into the transcript and raised a
  `TypeError`. Now `cleaning.py` and `knowledge.py` classify on `BaseException`,
  and `generators.py` and `merger.py` re-raise a `CancelledError` rather than
  absorbing it into a partial result, because a cancellation means teardown, not
  a failed batch.
- **ffmpeg, pypdf and a ~150 MB base64 encode all ran on the API's event loop**,
  stalling every other request and every WebSocket for their duration. All three
  are now behind `asyncio.to_thread` (`pipeline/media.py`,
  `pipeline/extraction.py`, `OpenRouterProvider.transcribe`).
- **The OpenRouter semaphore was keyed by `id(loop)`, and `id()` is recycled.**
  Celery creates a fresh event loop per task; once the old loop was collected a
  new one could be handed the dead loop's semaphore, and a semaphore bound to a
  dead loop raises — outside the retry loop, so it was not even retried. It is
  now a `weakref.WeakKeyDictionary` keyed by the loop object itself, which also
  stops the table growing for the life of the process.
- **The staged upload leaked.** `_buffer_upload` unlinked on every failure path,
  but nothing deleted the file after a *successful* ingest, so every ingested
  lecture left a full-size duplicate in `/tmp` until reboot.
  `IngestHandler._discard_staged_upload` now deletes it in a `finally`, guarded
  by shape-matching what the upload endpoint actually creates: the name starts
  with `tempfile.gettempprefix()`, the parent is exactly `tempfile.gettempdir()`,
  and it is a regular file. A YouTube URL and a developer's own file path both
  fail that guard, because deleting the wrong file is far worse than leaking one.
  Three tests cover it, including `test_a_callers_own_file_is_never_deleted`.

### 3.6 And the shape of it changed

| Before | After |
|---|---|
| One 1,060-line `main.py`: hand-rolled Supabase HTTP client, auth, every endpoint | `main.py` is ~180 lines of assembly. Six packages with a one-way dependency rule |
| Jobs on an `asyncio.create_task` loop inside the API process | A job table, an atomic claim, a reaper, and a pluggable transport (Celery, or an in-process pool through the same executor) |
| Supabase, Cloudflare R2, Vertex, Gemini, Deepgram — 96 packages | SQLite, a local file store with signed links, OpenRouter — 52 pinned packages |
| Tests: effectively none | 96, no network, no keys, including two real-thread concurrency tests |

**The local-first reasoning, in his words:** personal projects rot when a free
tier lapses or a key gets rotated, which is exactly what happened here — the
Deepgram key started returning 401 on both the transcription and the project
endpoints. The instinct is to add another vendor. Instead I checked and
OpenRouter already accepts audio as an `input_audio` content part, so one key now
covers generation *and* transcription. One vendor, one key, one failure mode.
Verified live end to end.

---

## 4. Architecture at a glance

This is the diagram to redraw on a whiteboard. Practise it once — about 40
seconds.

```
   browser
     │  HTTP                          WebSocket (one per project)
     ▼                                        ▲
  ┌──────────────────────────┐                │
  │ FastAPI                  │                │
  │  api/routes  api/deps    │                │
  └────────────┬─────────────┘                │
               │ 1. write the job row  ── committed BEFORE dispatch
               │ 2. dispatch           ── may fail; the row survives
               ▼                                │
        ┌──────────────┐   progress events      │
        │  Redis / bus │────────────────────────┘
        └──────┬───────┘
               ▼
        ┌──────────────────────────┐
        │ Worker                   │
        │   3. claim_job()         │  atomic — exactly one worker wins
        │   4. handler.run(job)    │  → JobBundle. NO database writes
        │   5. commit_bundle()     │  artifacts + edges + status, one txn
        │   6. flow.on_job_finished│  one txn: read → queue → write back,
        └──────────┬───────────────┘  then dispatch, after commit
                   ▼
          ┌──────────────────┐
          │  SQLite + files  │
          └──────────────────┘
```

Three processes: an API that accepts work, a worker that does it, Redis between
them. **Without Redis all three collapse into one** — the API runs its own worker
pool and an in-process bus, so `uvicorn backend.main:app` is a complete install.
`dispatch_mode()` decides once, at startup, by asking whether the broker answers.

### Packages

| Package | Responsibility | The one file to know |
|---|---|---|
| `api/` | HTTP and WebSocket surface, one route module per resource | `api/deps.py` |
| `handlers/` | One class per job type. Pure — they return work, never write it | `handlers/base.py` |
| `pipeline/` | Source → knowledge core: ingestion, extraction, media, cleaning | `pipeline/knowledge.py` |
| `services/` | Persistence, files, events, queueing, generation, flow execution | `services/flow/engine.py` |
| `llm/` | Model providers behind one interface | `llm/base.py` |
| `models/` | The domain vocabulary every layer shares | `models/graph.py` |

**The dependency direction is one-way:**
`api` → `handlers` → `services`/`pipeline` → `llm`/`models`. Nothing lower ever
imports anything higher. Say this out loud — it is what makes the package table
mean something rather than being folder names.

### Data model — six tables

`projects`, `jobs`, `artifacts`, `artifact_edges`, `flow_runs`, `chat_messages`.
The interesting one is `artifact_edges`, and there are two things to say:

- **Provenance is a DAG, not a tree.** An artifact generated from three lectures
  gets three `derived_from` edges. That is what "multiple inputs" means once it
  reaches storage, and it is what lets lineage answer "where did this question
  come from?".
- **The knowledge core has indegree zero.** It is the root. Provenance back to
  the source *file* is carried by `created_by_job_id`, not by an edge, because
  the core was not derived from anything already in the graph.

---

## 5. The five files to show

If they ask "walk me through a piece of it", open these, in this order. Each
walkthrough is about 30 seconds.

### 1. `backend/services/flow/engine.py` — the concurrency bug

*Why first:* it is the strongest thing in the repository. A real race, in his own
code, with a number attached.

> `on_job_finished` records a step's outcome and schedules what it unblocked.
> The whole body is inside `with self._database.transaction()`: read the run,
> merge the completion into `node_states`, write it back, then `_schedule` queues
> every step whose parents are now complete — all one atomic unit. It returns the
> job ids it queued, and `_hand_off` dispatches them *after* the transaction
> commits, because telling a worker about an uncommitted row means the worker can
> look it up and not find it.
>
> Before, all of that was outside a transaction, and the read-modify-write of the
> `node_states` blob meant two overlapping callers each saw a step as pending and
> each queued a job. FastAPI's sync routes run on the threadpool while workers
> run on the event loop, so they genuinely overlap. Eight threads reporting the
> same step complete produced nine dispatches; now it produces two.

Then open `test_pipeline.py::TestFlowConcurrency` in the next tab and show the
`threading.Barrier(8)`. The assertions are `len(dispatched) == 2` and two job
rows in the database.

### 2. `backend/services/flow/plan.py` — the algorithm

*Why:* the only file containing a classical algorithm applied to a real product
problem, and short enough to read on screen.

> `FlowCompiler.compile` takes React Flow's nodes and edges. `_classify` splits
> nodes into sources — already pointing at an artifact — and generators, which
> will produce one; a generator with no resolvable output type is rejected here
> with the list of valid types. `_adjacency` builds incoming and outgoing maps
> and rejects self-loops as it goes. `_require_inputs` rejects any generator
> nothing feeds. Then `_topological_order` is Kahn: seed the queue with indegree
> zero, pop, decrement children, carrying a depth as `max(existing, parent + 1)`
> so a node sits one wave below its *deepest* parent, not its first. If the order
> comes out shorter than the runnable set, what is left is a cycle, and I name up
> to five of the nodes involved. The canvas calls this as you wire nodes
> together, so a broken graph is visible before any tokens are spent.

If they push: `MAX_NODES = 100` is a deliberate cost ceiling, and
`FlowPlan.waves` is a derived property rather than stored state, so it cannot
drift from `steps`. And the compiler has no database handle at all — which is
exactly why `POST /flow/validate` can typecheck a canvas without touching
storage.

### 3. `backend/services/database.py` — the correctness primitives

*Why:* four of the system's invariants live in one file, and it is the natural
second half of the handler contract.

> `_transaction` takes the write lock, issues `BEGIN IMMEDIATE`, and rolls back
> on `BaseException` — not `Exception`, because a cancellation escaping with the
> transaction open leaves the connection unusable for every later write on that
> thread. It also joins an already-open transaction instead of issuing a second
> `BEGIN`, which is what lets the flow engine wrap several calls that each
> transact on their own.
>
> `claim_job` is the atomic claim: `BEGIN IMMEDIATE` takes the write lock
> *before* the read, so the select-then-update is one critical section and two
> workers cannot see the same pending row. `commit_bundle` is the other half of
> the handler contract — the handler returned a `JobBundle` and wrote nothing;
> this writes the artifacts, the edges and the terminal status in one
> transaction, and refuses outright if the job is already terminal.
>
> And `fail_job` has a terminal guard. A job reclaimed by the reaper runs twice,
> and I had the loser flipping a `completed` job to `failed` and then skipping a
> subtree that had already succeeded.

Then jump one file across to `job_runner.py` for `is_transient` — see the retry
question below.

### 4. `backend/llm/schema.py` — the subtlest bug

*Why:* 43 lines, and the fix nobody would guess. It shows he read a provider's
constraints rather than assuming the library did the right thing.

> Pydantic's `model_json_schema()` factors nested models into `$defs` and
> references them with `$ref`. Providers accept that but cannot police it in
> strict mode, and a model handed a reference-heavy schema stops treating field
> bounds as binding — my mind map ran a single string field to 100k characters
> and failed three retries. `strict_schema` walks the tree, splices each `$ref`
> back inline, and on every object sets `additionalProperties: false` and marks
> every property required. That is what strict mode needs to actually enforce a
> shape. Same tree, two-second response.

Pair it with `OpenRouterProvider._content_of` one file down:
`finish_reason == "length"` raises `TruncatedResponse`, which subclasses
`PermanentFailure`, so `_send` surfaces it immediately instead of retrying away
the one error message that told the user what to change.

### 5. `backend/tests/test_seams.py` — the evidence

*Why:* it turns "I applied SOLID" from an assertion into something they can watch
execute.

> This file tests the abstraction boundaries rather than the features.
> `RecordingProvider` is a fake `LLMProvider` that answers from a script and
> remembers what it was asked, and the tests drive `ArtifactGenerator` and
> `GenerateHandler` through it — real handler, real database, real transaction,
> fake model. `test_a_generate_handler_uses_the_injected_generator` asserts the
> committed artifact came from the fake and that exactly one provenance edge was
> written. That only passes because nothing downstream can tell one provider from
> another, which is Liskov doing work rather than being cited. `TestStagedUploads`
> is the same idea with stub pipeline stages, and it includes the one I care
> about most — `test_a_callers_own_file_is_never_deleted` — because the cleanup I
> added is an `unlink`, and I wanted a test standing between it and someone's
> actual files.

---

## 6. Where SOLID actually shows up

Not a definition list. Point at the file.

**Single responsibility.** `JobExecutor` owns the transaction boundary and
nothing else. `FlowCompiler` compiles; `FlowEngine` schedules — separate files,
and the compiler has no database handle, which is why validation is free.
`ExtractionService` routes to a reader, `DocumentReader` reads documents,
`Transcriber` handles speech. Each was one class before the split, and each was
hard to test because you could not exercise one behaviour without the others.

**Open/closed.** Adding an artifact type is one entry in `SPECS`
(`services/generators.py`) and one in `ARTIFACT_MODELS` (`models/artifacts.py`).
No handler change, no new branch in the runner, no new validation rule —
`GeneratorSpec.validate` reads its thresholds from the spec. That is why going
from five types to eight touched two dictionaries. The canvas even builds its
palette from `/api/capabilities`, derived from `GENERATED_TYPES`, so the UI picks
up a new type without a frontend change.

**Liskov.** `OfflineProvider` and `OpenRouterProvider` are interchangeable
everywhere. The proof is that the entire suite runs the real handlers against the
offline one — only possible because nothing downstream can tell them apart. If
that substitution were leaky, 96 tests would fail.

**Interface segregation.** `LLMProvider` has three methods and `transcribe` is
optional with a default that raises, so a caller that only generates text does
not depend on audio; `supports_audio` is a class attribute callers check rather
than a method they must implement. `FileStore` exposes put/get/sign/resolve, not
a general filesystem.

**Dependency inversion.** Every handler takes its collaborators as constructor
arguments with a sensible default:

```python
def __init__(self, database=None, resolver=None, generator=None, merger=None, exporter=None):
    self._database = database or get_database()
```

Production passes nothing; tests pass fakes. Handlers depend on `LLMProvider` and
`Database` — the abstractions — never on OpenRouter or SQLite. `llm/factory.py`
is the single place that decides which concrete provider exists, and it degrades
to offline rather than raising when a key is absent.

---

## 7. Anticipated questions

Answers are 2–4 sentences. Say them roughly like this, not verbatim.

**"Did you write this?"**
> I used AI assistance, and I'd rather be direct about that than have it come up
> awkwardly. What I drove was every architectural decision: the handler-returns-
> a-bundle contract, the wave-depth scheduler, making the queue a table instead
> of a message, the strict-schema fix. The clearest evidence is the concurrency
> bug — nothing generated that race for me. I found it reasoning about where
> FastAPI's threadpool and the event loop overlap, and I wrote a barrier test to
> prove it. Open any file and I'll walk you through it.

If they follow up on a specific file, go to the code, do not paraphrase. The five
walkthroughs in §5 exist so there is always a concrete place to land.

**"What was the hardest bug?"**

Two good answers. Lead with the first; offer the second if they want more.

> The one that cost me most was a locale mismatch. My offline provider — the
> no-API-key fallback — decides whether a prompt wants its input edited or wants
> something new derived from it, and the gate was "does the prompt contain *do
> NOT summarize*". American spelling. My cleaning prompt says *summarise*.
> British. So the check never matched, and the cleaning pass — whose entire job
> is to hand the transcript back repaired — replaced the whole lecture with a
> synthetic study document instead, and every artifact downstream was then built
> on that stub rather than on the actual lecture. Nothing errored. The output was
> just quietly, plausibly wrong. It's now a tuple of markers covering both
> spellings and the phrases that actually appear in the prompt, behind a named
> method with a docstring saying what it's for.

Why that story is good: silent data corruption from a one-word difference,
plausible output masking it, no exception anywhere. If they seem to want
something more technical:

> The other one was structured-output drift. A mind map would burn 100k
> characters on a single string field and fail all three retries, and everything
> pointed at the model being bad. It was the schema: Pydantic factors nested
> models into `$defs` and `$ref`, providers accept that but can't enforce it in
> strict mode, and given a reference-heavy schema the model stops treating field
> bounds as binding. Inline every reference, close every object, mark everything
> required — same tree, two-second response. What made it hard is that nothing in
> the error said "schema"; it said "unterminated string".

**"How do you know the atomic claim works?"**
> `claim_job` opens with `BEGIN IMMEDIATE`, which takes SQLite's write lock
> *before* the read — the equivalent of `SELECT … FOR UPDATE SKIP LOCKED`. So the
> select-then-update is one critical section. There are two tests: one inserts a
> job and asserts the second `claim_job` returns `None`, and
> `test_racing_workers_partition_the_queue` puts six real threads on a barrier
> against a 24-job queue and asserts every job was claimed exactly once. That
> second one is the honest test — the first would pass on a broken
> implementation, which is the same mistake my old idempotence test made.

**"Why SQLite and not Postgres?"**
> Because the workload is one local workspace with a handful of concurrent jobs,
> and the whole persistence surface is behind `Database`. WAL mode plus
> `BEGIN IMMEDIATE` gives me a real atomic claim and real transactions, which is
> the only concurrency primitive I actually needed. The honest reason is that the
> previous version died when its Supabase free tier lapsed, and a project that
> stops running when a key rotates is not a project. If I needed multi-tenancy
> I'd swap the implementation behind `Database`, not restructure anything above.

**"What happens when the model returns garbage?"**
> Three layers. Structured output — `strict_schema` sends a closed,
> fully-required, `$ref`-free schema with `strict: true`, and `parse_as` strips
> code fences and prose wrappers before validating. Then semantic validation in
> `GeneratorSpec.validate`: a quiz with two questions parses perfectly and is
> useless, so it's rejected with "expected at least 5 questions, got 2". Then
> classification — a schema violation is permanent, so the job fails cleanly
> rather than burning three attempts producing the same garbage. That last part
> is a fix: `RETRYABLE_STATUS` used to be inert, so a 401 burned three attempts
> and the useful error got retried away.

**"Why not stream generation?"**
> Because I validate before I display. A quiz is not useful half-rendered, and if
> I streamed I'd have to show output that `GeneratorSpec.validate` might then
> reject — so the user watches something appear and then vanish. Instead I stream
> *progress*: every handler reports named stages over the WebSocket, so you see
> "merging sources", "writing quiz", "saving". Same perceived responsiveness,
> nothing I have to retract.

**"How would you scale this to 1,000 users?"**
> Three changes, in order. Swap the `Database` implementation for Postgres —
> `claim_job` becomes `SELECT … FOR UPDATE SKIP LOCKED`, which is the same
> semantics I already rely on, and nothing above the class changes. Then the
> local file store becomes S3 or R2; `FileStore` already exposes exactly the
> put/get/sign surface an object store gives you. Then Celery workers scale
> horizontally, which they already can. The genuinely new work is multi-tenancy:
> `resolve_user` becomes a real token check and every query grows a tenant
> predicate — and I'd be careful there, because three of the four security holes
> I found were exactly the shape of "checked one level of ownership and stopped".

**"How do you test something that calls an LLM?"**
> I don't mock the LLM; I substitute the provider. `OfflineProvider` implements
> the same interface and derives artifacts from the source text with frequency
> analysis, so the tests run the *real* handlers, the real transactions and the
> real DAG traversal against a temp SQLite database — 96 tests, no network, no
> keys. Where I need to assert on what the model was *asked*, `test_seams.py`
> uses `RecordingProvider`, which answers from a script and records the prompts.
> Mocking `httpx` would only have tested my mock.

**"Why is the knowledge core the root of the graph?"**
> Because it has indegree zero — it wasn't derived from anything already in the
> graph. The source *file* is an artifact too, but the edge would be lying: the
> core comes from the file's extracted text, not from the file as a graph node.
> So ingest emits exactly two artifacts and zero edges, and the link back to the
> file is `created_by_job_id`. That keeps `artifact_edges` meaning one thing
> only — "this was generated from that" — so lineage queries stay honest.

**"What would you do differently?"**
> Two things. I'd write the concurrency tests first. My old idempotence test
> called `advance` twice on one thread and passed, which gave me false confidence
> in exactly the property that was broken — a test that proves a weaker claim
> than you think it does is worse than no test. And I'd have built the offline
> provider first. It ended up being what made the test suite possible and what
> makes `docker compose up` work with an empty `.env`, and I built it late, as a
> fallback, without realising it was load-bearing infrastructure.

---

## 8. Honest limitations

Volunteer these before you are asked. Naming your own gaps reads as judgement;
being caught out by them reads as the opposite. Two or three is enough — pick
what fits the conversation. The first is the strongest thing on this list.

| Limitation | The line to say |
|---|---|
| **`ingest` submitted directly to `POST /api/jobs` with a non-YouTube `source_ref` is an arbitrary local file read** | "This is the sharpest edge I know about. The sanctioned upload route sets `source_ref` server-side, and I closed the YouTube variant with a URL validator, but a caller can still name a local path for the other source types and the handler will read it. It's single-user and local-only, so today the 'attacker' is the operator — and the workspace page deliberately lets a developer type a local path. But it's the first thing I'd lock down before any multi-user deployment, probably by making `source_ref` a storage key rather than a filesystem path." |
| **Single-user, no multi-tenancy** | "`resolve_user` returns one local user. Ownership is recorded and enforced on every read, so the queries are already correct — there's just no identity provider behind it. Deliberate: one seam to replace, not a refactor." |
| **The security fixes have thinner tests than the concurrency work** | "The four API holes are fixed in code and I can show you each one, but only the ownership behaviour has a named regression test — nothing yet asserts that a cross-project source id is rejected, or that a client can't rewrite `binary.storage_path`. That's the next thing I'd write, because a security fix without a test is a fix that comes back." |
| **A retried ingest orphans its first copy** | "`store_upload` mints a fresh uuid key per attempt, so a failed-then-retried ingest leaves the first attempt's copy in the file store referenced by nothing. Small, but it's unbounded growth, and the fix is either keying on job id or sweeping artifacts with no row." |
| **No vector store / RAG** | "A lecture fits in a modern context window, and the knowledge core is a better summary than top-k chunks — it's structured, and every generator reads the same one, which is what keeps artifacts consistent. RAG would have been resume-driven." |
| **No streaming generation** | "Deliberate, for the reason above: I validate before I display, so I stream progress instead of tokens." |
| **The frontend is weaker than the backend** | "That's where I'd go next, and it's genuinely the weak half. The canvas works and the WebSocket wiring is clean, but there's duplicated state between the React Flow store and the fetched artifacts, and the dashboard pages accumulated during the hackathon and never got the treatment the backend did." |
| **`OfflineProvider` output is genuinely poor** | "It's frequency analysis, not a model. Its job is to prove the pipeline runs, not to be useful — but it's not a stub either. It goes through every stage." |
| **Exports depend on a LaTeX install** | "`ExportService` catches render failures rather than failing the job, because an artifact is defined by its content and the file is a convenience. A missing LaTeX install costs you the PDF, not the generation." |

---

## Cheat sheet

Sixty seconds before the call.

### The three sentences

1. **"The graph you draw is the program that runs."** `FlowCompiler` compiles the
   canvas to a DAG, Kahn's algorithm assigns wave depths, `FlowEngine` dispatches
   wave by wave. Fan-in and fan-out are one mechanism from two ends.
2. **"Handlers never write to the database."** They return a `JobBundle`;
   `JobExecutor` commits it in one transaction. LLM calls fail often enough that
   a handler throwing midway is the common case.
3. **"Scheduling a step is transactional, and dispatch happens after commit."**
   Read → queue → write back, one transaction. Eight concurrent completions
   produced 9 dispatches before, 2 after.

### The numbers

| | |
|---|---|
| Tests | **96** — no network, no API keys, temp SQLite + offline provider |
| The measurement | 8 concurrent completions → **9 dispatches before, 2 after** |
| Racing-workers test | 6 threads, 24 jobs, every job claimed exactly once |
| Dependencies | **52** pinned (was 96) |
| Artifact types | **8** — quiz, exam, notes, slides, flashcards, study guide, cheat sheet, mind map |
| Source types | **6** — youtube, audio, video, pdf, pptx, md |
| Tables | **6** — projects, jobs, artifacts, artifact_edges, flow_runs, chat_messages |
| Security holes found and fixed | **4**, all in `backend/api/` |
| Node ceiling | 100 per flow |
| Defaults | 3 attempts, 900s job timeout, 1800s stale cutoff, 4 workers, 6 concurrent LLM calls |

### The file paths

| | |
|---|---|
| The concurrency fix | `backend/services/flow/engine.py` — `on_job_finished`, `_schedule`, `_hand_off` |
| Its test | `backend/tests/test_pipeline.py` — `TestFlowConcurrency` |
| The algorithm | `backend/services/flow/plan.py` — `FlowCompiler._topological_order` |
| The primitives | `backend/services/database.py` — `_transaction`, `claim_job`, `commit_bundle`, `fail_job` |
| Retry classification | `backend/services/job_runner.py` — `is_transient`, `TRANSIENT_STATUS` |
| The contract | `backend/handlers/base.py` — `JobHandler`, `JobBundle` |
| The subtlest bug | `backend/llm/schema.py` — `strict_schema` |
| Permanent vs retryable | `backend/llm/openrouter.py` — `PermanentFailure`, `_limiter` |
| The locale bug | `backend/llm/offline.py` — `PASS_THROUGH_MARKERS`, `_wants_the_source_back` |
| Ownership | `backend/api/deps.py` — `require_project`, `require_project_artifact` |
| The SOLID evidence | `backend/tests/test_seams.py` — `RecordingProvider`, `TestStagedUploads` |

### If it goes wrong

- Demo fails → blank the key, `/health` shows `"model": "offline"`, everything
  still runs.
- Anything else fails → `pytest backend/tests -q`, 96 tests, a few seconds.
- Asked something you don't know → "I don't know off the top of my head, let me
  look" and open the file. Reading your own code in front of them is a *good*
  outcome; guessing is not.

### Last thing

Lead with the canvas, close the opener on the concurrency bug. When they ask
about AI assistance, answer in one honest sentence and immediately offer to open
a file — the offer is the proof.
