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
> I rewrote the whole backend since I last showed it to you. Happy to start
> anywhere — the flow compiler is probably the most interesting file.

Three things that opener is doing deliberately:

1. **Leads with the executable canvas.** Everyone at a hackathon built a prompt
   in a box. Almost nobody built a scheduler.
2. **Names a correctness invariant unprompted** (handlers are pure). That is the
   signal that separates "I wired an API" from "I designed a system".
3. **Volunteers the rewrite in the last line**, and hands them the steering
   wheel. It invites the question you most want to answer.

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
| 4 | Press Run | "First wave dispatches. Everything downstream stays pending until its inputs actually exist — the engine only dispatches a step whose parents are all complete." Nodes light up over a WebSocket, one socket for the whole project, no polling. | 45s |
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
  `pytest backend/tests -q`, 87 tests, no network, no API keys." That takes a
  few seconds and it exercises real handlers, real transactions and real DAG
  traversal, so it is a legitimate substitute for the demo rather than a
  consolation prize.
- **Frontend is broken.** Fall back to `curl` against
  `POST /api/projects/{id}/flow/validate`, which returns the compiled plan with
  each step's parents and wave depth without running anything. That is the
  clearest possible view of what the compiler does.

---

## 3. What changed since last time

This is the section that matters. Last time the canvas was decorative and the
backend was one file. The list below is ordered by how much it says about
engineering judgement, not by how hard it was to fix.

### The headline: the canvas became executable

Before, the "Run" button POSTed to `/run`, an endpoint that did not exist. Each
generator node independently fetched the project's knowledge core, so the edges
you drew changed nothing — the graph was decoration over a set of independent
buttons.

Now `backend/services/flow/plan.py` and `backend/services/flow/engine.py` make
the graph load-bearing:

- `FlowCompiler.compile()` classifies each node as a **source** (already points
  at an artifact) or a **generator** (will produce one), builds adjacency,
  and runs Kahn's algorithm in `_topological_order`. Each step gets a **wave
  depth** — `depth[child] = max(depth[child], depth[node] + 1)` — so siblings
  land in the same wave and dispatch together.
- Validation happens before dispatch and every message names the offending node:
  cycles (Kahn terminates with nodes left over), self-loops, generators with no
  input (`_require_inputs`), generators with no output type (`_classify`).
- `FlowEngine.advance()` dispatches every step whose parents are complete, and
  is idempotent — a repeated completion notification cannot double-run a step.
- **Fan-in and fan-out are one mechanism seen from two ends.** A node with three
  incoming edges is dispatched with three `source_artifact_ids`, merged by
  `CoreMerger`. A node with three outgoing edges satisfies three downstream
  steps when it completes.
- The engine holds **nothing in memory between calls**. Everything lives in the
  `flow_runs` row, because the job that unblocks a step may finish in a
  different process from the one that started the run.

### Defects found and fixed during the rewrite

| # | What was broken | Why it mattered | What I did |
|---|---|---|---|
| 1 | **Effective concurrency was 1.** Async handlers called the *synchronous* LLM client, blocking the event loop for the entire model call. | Worker count was decorative. Four workers and one worker performed identically. Nobody would have found this by reading the config. | Made generation async end to end — `LLMProvider.complete` / `complete_as` are coroutines, `httpx.AsyncClient` throughout. The exam's three question batches now run under `asyncio.gather` in `ArtifactGenerator._exam`. |
| 2 | **Authentication bypass.** Any request whose `Authorization` header merely *contained* the substring `mock-token` was accepted as a fixed user — in every deployment, not just dev. | A test convenience that shipped. This is the one I am least proud of and most willing to talk about. | Removed entirely. `backend/api/deps.py::resolve_user` now returns one documented local user, ownership is still recorded per project and checked on every read via `require_project` / `require_artifact`, so there is exactly one seam to replace when accounts arrive. |
| 3 | **Structured-output drift.** Pydantic emits nested models as `$defs` + `$ref`. Providers accept that but cannot enforce it strictly, and a model handed a reference-heavy schema stops treating field bounds as binding. A mind map generated this way ran one string field until it hit the output limit — 100k characters, three failed retries. | Silent, expensive, and looked like the model "just being bad". It was the schema. | `strict_schema()` in `backend/llm/schema.py` inlines every `$ref`, sets `additionalProperties: false` and marks every object fully-required, and the request sends `strict: true`. Same tree, two-second response. Truncation is now also detected explicitly: `finish_reason == "length"` raises `TruncatedResponse` rather than surfacing later as an unterminated-string parse error. |
| 4 | **Retry classification matched bare status codes.** `is_transient()` looked for `"429"`, `"502"` and friends *anywhere* in the error text. | `"Source artifacts not found: 429e4567-e89b-…"` — the digits are part of a UUID — was retried as transient. Roughly one flaky test run in six, and in production it meant paying three times for a request that could never succeed. | `TRANSIENT_STATUS` in `backend/services/job_runner.py` now only matches a code where it is *labelled* as one: `\b(?:http\|status\|code)\s*[:=]?\s*(408\|429\|500\|502\|…)\b`. There is a named regression test — `TestRetryPolicy::test_status_digits_inside_identifiers_do_not_trigger_a_retry`. |
| 5 | **Idempotency returned *completed* jobs.** | Pressing "regenerate" silently handed back the old artifact. It looked exactly like a broken button, and the logs said the request succeeded. | `_find_in_flight_duplicate` in `backend/api/routes/jobs.py` deduplicates only `pending` and `running` jobs, and returns `None` immediately if the request carries instructions, because different instructions are different work. |
| 6 | **Source ids were parsed as `uuid.uuid4() if isinstance(x, str) else x` inside a bare `except: pass`.** | A malformed id became a *fresh random* id, which then became a lookup for an artifact that had never existed. The error surfaced three layers away from its cause. | `as_uuid()` in `backend/models/graph.py` parses and raises `ValueError` naming the offending value. Failing loudly at the boundary is the whole point. |
| 7 | **No stale-job reaper.** A worker killed mid-job left its row `running` forever, and `claim_job` skips running rows. | The user's node spun indefinitely with no error ever surfacing. The single worst failure mode, because it is invisible. | `Database.reap_stale_jobs()` requeues rows stuck `running` past `STALE_JOB_SECONDS`, or fails them if attempts are exhausted. Run by `WorkerPool._reaper` locally and by a Celery beat task in Celery mode. |
| 8 | **`ALLOWED_GENERATIONS` was checked and the failure branch was `pass`.** | The type map documented a rule it did not enforce. A comment pretending to be a constraint is worse than no constraint. | `ALLOWED_TARGETS` in `backend/handlers/sources.py`; `_check_transition` raises `SourceResolutionError` listing what *is* allowed. |
| 9 | **CORS was `allow_origins=["*"]` with `allow_credentials=True`.** | Browsers reject that combination outright, so there was effectively no CORS at all — it only ever worked same-origin. | `backend/main.py` uses an explicit origin list from settings plus an `allow_origin_regex` for localhost, with credentials enabled. |
| 10 | **Uploads were read whole into memory.** A 600 MB recording became 600 MB resident. | Two concurrent uploads on a small box is an OOM kill, not a slow request. | `_buffer_upload` in `backend/api/routes/projects.py` streams to a temp file in chunks and enforces the size limit *as it goes*, aborting and unlinking at the threshold rather than after the full read. |
| 11 | **The knowledge-core validator required every collection to be populated.** | A short recording that legitimately contained no worked examples failed ingest, and an otherwise usable extraction was discarded. Strictness that costs the user their upload is a bug. | `KnowledgeCoreValidator.REQUIRED_FIELDS` is now `("title", "summary", "concepts", "key_facts")` — only the fields every generator actually reads. Markup rejection stayed, because stray LaTeX in the core corrupts every artifact derived from it. |

### And the shape of it changed

| Before | After |
|---|---|
| One 1,060-line `main.py`: hand-rolled Supabase HTTP client, auth, every endpoint | `main.py` is ~180 lines of assembly. Six packages with a one-way dependency rule |
| Jobs on an `asyncio.create_task` loop inside the API process | A job table, an atomic claim, a reaper, and a pluggable transport (Celery, or an in-process pool through the same executor) |
| Supabase, Cloudflare R2, Vertex, Gemini, Deepgram — 96 packages | SQLite, a local file store with signed links, OpenRouter — 52 pinned packages |
| Tests: effectively none | 87, no network, no keys |

**The local-first reasoning, in his words:** personal projects rot when a free
tier lapses or a key gets rotated, which is exactly what happened here — the
Deepgram key started returning 401 on both the transcription and the project
endpoints. The instinct is to add another vendor. Instead I checked and
OpenRouter already accepts audio as an `input_audio` content part, so one key
now covers generation *and* transcription. One vendor, one key, one failure
mode. Verified live end to end.

---

## 4. Architecture at a glance

This is the diagram to redraw on a whiteboard. Practise it once — it takes about
40 seconds.

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
        │   6. flow.on_job_finished│  schedule whatever this unblocked
        └──────────┬───────────────┘
                   ▼
          ┌──────────────────┐
          │  SQLite + files  │
          └──────────────────┘
```

Three processes: an API that accepts work, a worker that does it, Redis between
them. **Without Redis all three collapse into one** — the API runs its own
worker pool and an in-process bus, so `uvicorn backend.main:app` is a complete
install. `dispatch_mode()` decides once, at startup, by asking whether the
broker answers.

### Packages

| Package | Responsibility | The one file to know |
|---|---|---|
| `api/` | HTTP and WebSocket surface, one route module per resource | `api/routes/jobs.py` |
| `handlers/` | One class per job type. Pure — they return work, never write it | `handlers/base.py` |
| `pipeline/` | Source → knowledge core: ingestion, extraction, media, cleaning | `pipeline/knowledge.py` |
| `services/` | Persistence, files, events, queueing, generation, flow execution | `services/flow/plan.py` |
| `llm/` | Model providers behind one interface | `llm/base.py` |
| `models/` | The domain vocabulary every layer shares | `models/graph.py` |

**The dependency direction is one-way:**
`api` → `handlers` → `services`/`pipeline` → `llm`/`models`. Nothing lower ever
imports anything higher. Say this out loud — it is the sentence that makes the
package table mean something rather than being folder names.

### Data model — six tables

`projects`, `jobs`, `artifacts`, `artifact_edges`, `flow_runs`, `chat_messages`.
The interesting one is `artifact_edges`, and there are exactly two things to say
about it:

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
walkthrough below is about 30 seconds.

### 1. `backend/services/flow/plan.py` — the algorithm

*Why this one:* it is the only file in the project containing a classical
algorithm applied to a real product problem, and it is short enough to read on
screen.

> `FlowCompiler.compile` takes React Flow's nodes and edges. First `_classify`
> splits nodes into sources — already pointing at an artifact — and generators,
> which will produce one; a generator with no resolvable output type is rejected
> here with the list of valid types. `_adjacency` builds incoming and outgoing
> maps and rejects self-loops as it goes. `_require_inputs` rejects any
> generator nothing feeds. Then `_topological_order` is Kahn: seed the queue
> with indegree zero, pop, decrement children, and carry a depth as
> `max(existing, parent + 1)` so a node sits one wave below its *deepest*
> parent, not its first. If the order comes out shorter than the runnable set,
> what is left is a cycle, and I name up to five of the nodes involved. The
> canvas calls this as you wire nodes together, so a broken graph is visible
> before any tokens are spent.

If they push: `MAX_NODES = 100` is a deliberate cost ceiling, and
`FlowPlan.waves` is a derived property rather than stored state, so it cannot
drift from `steps`.

### 2. `backend/services/job_runner.py` — the transaction boundary

*Why this one:* it holds the two invariants that make the system correct under
failure, and it pairs naturally with `services/database.py`.

> `JobExecutor.execute` is the only place a job becomes committed state. It
> gets a handler, attaches a progress reporter, awaits `handler.run(job)` under
> a timeout, and calls `commit_bundle`. The handler returned a `JobBundle` — it
> wrote nothing. `Database.commit_bundle` writes the artifacts, the edges and
> the terminal job status inside one `BEGIN IMMEDIATE` transaction, and refuses
> outright if the job is already terminal, so a duplicate delivery cannot
> double-write.
>
> The other half is `is_transient`. A busy upstream will succeed on the next
> attempt; a malformed payload will fail identically while spending tokens. The
> subtlety is `TRANSIENT_STATUS` — it only matches a status code where it is
> *labelled* as one, because I had a bug where `"artifacts not found:
> 429e4567-…"` was retried three times purely because a UUID happened to start
> with 429.

Then jump one file across to `Database.claim_job` — see Q3 below.

### 3. `backend/llm/schema.py` — the subtlest bug

*Why this one:* 43 lines, and it is the fix nobody would guess. It shows you
read a provider's constraints rather than assuming the library did the right
thing.

> Pydantic's `model_json_schema()` factors nested models into `$defs` and
> references them with `$ref`. Providers accept that but cannot police it in
> strict mode, and a model handed a reference-heavy schema stops treating field
> bounds as binding — my mind map ran a single string field to 100k characters
> and failed three retries. `strict_schema` walks the tree, splices each `$ref`
> back inline, and on every object sets `additionalProperties: false` and marks
> every property required. That is what strict mode needs to actually enforce
> a shape. Same tree, two-second response.

Pair it with `OpenRouterProvider._content_of`, three lines lower down the stack:
`finish_reason == "length"` raises `TruncatedResponse` with a message that says
what to change, instead of letting a truncated document surface later as a JSON
parse error pointing at the wrong place.

### 4. `backend/handlers/base.py` — the contract

*Why this one:* 48 lines including docstrings, and it is the decision the whole
backend is shaped around. Short files that carry a lot of weight are the best
possible thing to show.

> `JobHandler` is an ABC with one abstract method: `async run(job) -> JobBundle`.
> Handlers never write to the database. They describe what they produced and the
> runner commits it in a single transaction. My reasoning is that LLM calls fail
> often enough that a handler throwing partway through is the *common* case, not
> the edge case — and a half-written knowledge graph is unrecoverable, because
> there is no way to tell afterwards which edges were meant to exist. Progress
> is reported through an injected callback rather than published directly, which
> keeps the event transport out of the handler and lets a test assert on the
> sequence of stages.

Then show any handler — `handlers/generate_handler.py` is the clearest — and
point out that every collaborator is a constructor argument with a working
default, so production passes nothing and tests pass fakes.

### 5. `backend/tests/test_seams.py` — the evidence

*Why this one:* it turns "I applied SOLID" from an assertion into something they
can watch execute.

> This file tests the abstraction boundaries rather than the features.
> `RecordingProvider` is a fake `LLMProvider` that answers from a script and
> remembers what it was asked, and the tests then drive `ArtifactGenerator` and
> `GenerateHandler` through it — real handler, real database, real transaction,
> fake model. `test_a_generate_handler_uses_the_injected_generator` asserts the
> committed artifact came from the fake and that exactly one provenance edge was
> written. That test only passes because nothing downstream can tell one
> provider from another, which is Liskov doing actual work rather than being
> cited. The `TestFileStoreContract` block is the same idea for storage: a link
> signed by a different secret is refused, an expired link is refused, and a key
> containing `../../etc/passwd` raises.

---

## 6. Where SOLID actually shows up

Not a definition list. Point at the file.

**Single responsibility.** `JobExecutor` owns the transaction boundary and
nothing else. `FlowCompiler` compiles; `FlowEngine` schedules — separate files,
and the compiler has no database handle at all, which is exactly why
`POST /flow/validate` can typecheck a canvas without touching storage.
`ExtractionService` routes to a reader, `DocumentReader` reads documents,
`Transcriber` handles speech. Each of those was one class before the split, and
each was hard to test because you could not exercise one behaviour without
dragging in the others.

**Open/closed.** Adding an artifact type is one entry in `SPECS`
(`services/generators.py`) and one in `ARTIFACT_MODELS` (`models/artifacts.py`).
No handler change, no new branch in the runner, no new validation rule —
`GeneratorSpec.validate` reads its thresholds from the spec. That is why going
from five types to eight touched two dictionaries. The canvas even builds its
palette from `/api/capabilities`, which is derived from `GENERATED_TYPES`, so
the UI picks up a new type without a frontend change.

**Liskov.** `OfflineProvider` and `OpenRouterProvider` are interchangeable
everywhere. The proof is that the entire test suite runs the real handlers
against the offline one — which is only possible because nothing downstream can
tell them apart. If that substitution were leaky, 87 tests would fail.

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

Production passes nothing; tests pass fakes. The handlers depend on
`LLMProvider` and `Database` — the abstractions — never on OpenRouter or SQLite
directly. `llm/factory.py` is the single place that decides which concrete
provider exists, and it degrades to offline rather than raising when a key is
absent or the client fails to construct.

---

## 7. Anticipated questions

Answers are 2–4 sentences. Say them roughly like this, not verbatim.

**"Did you write this?"**
> I used AI assistance, and I'd rather be direct about that than have it come up
> awkwardly. What I drove was every architectural decision: the handler-returns-
> a-bundle contract, the wave-depth scheduler, making the queue a table instead
> of a message, the strict-schema fix. I can tell you why each of those exists
> and what breaks without it — and most of them exist because the previous
> version broke in a specific way I had to debug. Open any file and I'll walk
> you through it.

If they follow up on a specific file, go to the code, do not paraphrase. The
five walkthroughs in §5 exist so there is always a concrete place to land.

**"Why SQLite and not Postgres?"**
> Because the workload is one local workspace with a handful of concurrent jobs,
> and the entire persistence surface is behind `Database`. WAL mode plus
> `BEGIN IMMEDIATE` gives me a real atomic claim, which is the only concurrency
> primitive I actually needed. The honest reason is that the previous version
> died when its Supabase free tier lapsed, and a project that stops running when
> a key rotates is not a project. If I needed real multi-tenancy I'd swap the
> implementation behind `Database`, not restructure anything above it.

**"How do you know the atomic claim works?"**
> `claim_job` opens with `BEGIN IMMEDIATE`, which takes SQLite's write lock
> *before* the read — the equivalent of `SELECT … FOR UPDATE SKIP LOCKED`. So
> the select-then-update is one critical section and two workers cannot see the
> same pending row. `test_a_job_is_claimed_exactly_once` inserts one job, calls
> `claim_job` twice, and asserts the second returns `None`. Without that lock
> ordering, two workers both claim it, you pay for the same generation twice,
> and they race on the commit.

**"What happens when the model returns garbage?"**
> Three layers. First, structured output — `strict_schema` sends a closed,
> fully-required, `$ref`-free schema with `strict: true`, and the response is
> parsed with `parse_as`, which strips code fences and prose wrappers before
> validating. Second, semantic validation in `GeneratorSpec.validate`: a quiz
> with two questions parses perfectly and is useless, so it is rejected with
> "expected at least 5 questions, got 2". Third, `is_transient` classifies the
> failure — a schema violation is permanent, so the job fails cleanly rather
> than burning three attempts producing the same garbage.

**"Why not stream generation?"**
> Because I validate before I display. A quiz is not useful half-rendered, and
> if I streamed I'd have to show output that `GeneratorSpec.validate` might then
> reject — so the user watches something appear and then vanish. Instead I
> stream *progress*: every handler reports named stages over the WebSocket, so
> you see "merging sources", "writing quiz", "saving". That gives the same
> perceived responsiveness without showing anything I might have to retract.

**"How would you scale this to 1,000 users?"**
> Three changes, in order. Swap the `Database` implementation for Postgres —
> `claim_job` becomes `SELECT … FOR UPDATE SKIP LOCKED`, which is the same
> semantics I'm already relying on, and nothing above the class changes. Then
> the local file store becomes S3 or R2; `FileStore` already exposes exactly the
> put/get/sign surface an object store gives you, and the signed URLs become
> presigned ones. Then Celery workers scale horizontally, which they already can
> — `docker compose up --scale worker=3` today. The genuinely new work is
> multi-tenancy: `resolve_user` becomes a real token check and every query grows
> a tenant predicate. The ownership checks are already in place and enforced,
> they just all resolve to one user.

**"What would you do differently?"**
> Two things. I'd write the tests before the rewrite, not alongside it — the
> retry-classification bug had been live for weeks and I only found it because a
> test flaked about one run in six, which means I got lucky rather than being
> thorough. And I'd have built the offline provider first. It ended up being the
> thing that made the test suite possible and made `docker compose up` work with
> an empty `.env`, and I built it late, as a fallback, without realising it was
> load-bearing infrastructure.

**"Why is the knowledge core the root of the graph?"**
> Because it has indegree zero — it wasn't derived from anything already in the
> graph. The source *file* is an artifact too, but the edge would be lying: the
> core comes from the file's extracted text, not from the file as a graph node.
> So the ingest handler emits exactly two artifacts and zero edges, and the link
> back to the file is carried by `created_by_job_id`. That keeps `artifact_edges`
> meaning one thing only — "this was generated from that" — so lineage queries
> stay honest.

**"How do you test something that calls an LLM?"**
> I don't mock the LLM; I substitute the provider. `OfflineProvider` implements
> the same interface and derives artifacts from the source text with frequency
> analysis, so the tests run the *real* handlers, the real transactions and the
> real DAG traversal against a temp SQLite database — 87 tests, no network, no
> keys. Where I need to assert on what the model was *asked*, `test_seams.py`
> uses `RecordingProvider`, which answers from a script and records the prompts,
> so I can assert that user instructions actually reach the prompt and are
> marked as taking precedence. Mocking `httpx` would only have tested my mock.

**"What was the hardest bug?"**
> The structured-output drift. A mind map would burn 100k characters on a single
> string field and fail all three retries, and everything pointed at the model
> being bad. It was the schema: Pydantic factors nested models into `$defs` and
> `$ref`, providers accept that but can't enforce it in strict mode, and given a
> reference-heavy schema the model stops treating field bounds as binding. The
> fix was `strict_schema` — inline every reference, close every object, mark
> everything required. Same tree, two-second response. What made it hard is that
> nothing in the error said "schema"; it said "unterminated string".

If you only remember one, remember this one. It is the best story in the
project: a wrong hypothesis, a real diagnosis, a small fix, a measurable result.

---

## 8. Honest limitations

Volunteer these before you are asked. Naming your own gaps reads as judgement;
being caught out by them reads as the opposite. Two or three is enough — pick
the ones that fit the conversation.

| Limitation | The line to say |
|---|---|
| **Single-user, no multi-tenancy** | "`resolve_user` returns one local user. Ownership is recorded and enforced on every read, so the queries are already correct — there's just no identity provider behind it. That's deliberate: one seam to replace, not a refactor." |
| **No vector store / RAG** | "A lecture fits in a modern context window, and the knowledge core is a better summary than top-k chunks would be — it's structured, and every generator reads the same one, which is what keeps artifacts consistent. RAG would have been resume-driven." |
| **No streaming generation** | "Deliberate, for the reason above: I validate before I display, so I stream progress instead of tokens." |
| **The frontend is weaker than the backend** | "That's where I'd go next, and I'd say it's genuinely the weak half. The canvas works and the WebSocket wiring is clean, but there's duplicated state between the React Flow store and the fetched artifacts, and the dashboard pages accumulated during the hackathon and never got the same treatment the backend did." |
| **Uploaded temp files are not cleaned up after a successful ingest** | "I found this preparing to talk about it. `_buffer_upload` streams to a `NamedTemporaryFile(delete=False)` and unlinks it on every *failure* path, but after a successful ingest the source is copied into the file store and the temp file stays. One-line fix in the ingest handler's `finally`, and it should be a test." |
| **`OfflineProvider` output is genuinely poor** | "It's frequency analysis, not a model. Its job is to prove the pipeline runs, not to be useful — but it's not a stub either. It goes through every stage." |
| **Exports depend on a LaTeX install** | "`ExportService` catches render failures rather than failing the job, because an artifact is defined by its content and the file is a convenience. A missing LaTeX install costs you the PDF, not the generation." |

---

## Cheat sheet

Sixty seconds before the call.

### The three sentences

1. **"The graph you draw is the program that runs."** `FlowCompiler` compiles
   the canvas to a DAG, Kahn's algorithm assigns wave depths, `FlowEngine`
   dispatches wave by wave. Fan-in and fan-out are one mechanism from two ends.
2. **"Handlers never write to the database."** They return a `JobBundle`;
   `JobExecutor` commits it in one transaction. LLM calls fail often enough that
   a handler throwing midway is the common case.
3. **"The queue is a table, not a message."** The row is committed before
   dispatch, `claim_job` is atomic via `BEGIN IMMEDIATE`, and a reaper returns
   jobs stranded by a dead worker.

### The numbers

| | |
|---|---|
| Tests | **87** — no network, no API keys, temp SQLite + offline provider |
| Dependencies | **52** pinned (was 96) |
| Artifact types | **8** — quiz, exam, notes, slides, flashcards, study guide, cheat sheet, mind map |
| Source types | **6** — youtube, audio, video, pdf, pptx, md |
| Tables | **6** — projects, jobs, artifacts, artifact_edges, flow_runs, chat_messages |
| Handlers | **3** — ingest, generate, refine |
| Node ceiling | 100 per flow |
| Defaults | 3 attempts, 900s job timeout, 1800s stale cutoff, 4 workers, 6 concurrent LLM calls |
| Verified live | audio → transcript → core → 8-node flow in 2 waves → all 8 types → PDF/PPTX/MD via signed links → refine → assistant Q&A classified as *answer*, not *refine* |

### The file paths

| | |
|---|---|
| The algorithm | `backend/services/flow/plan.py` — `FlowCompiler._topological_order` |
| The scheduler | `backend/services/flow/engine.py` — `FlowEngine.advance` |
| The transaction boundary | `backend/services/job_runner.py` — `JobExecutor.execute`, `is_transient` |
| The atomic claim | `backend/services/database.py` — `claim_job`, `commit_bundle`, `reap_stale_jobs` |
| The contract | `backend/handlers/base.py` — `JobHandler`, `JobBundle` |
| The subtlest bug | `backend/llm/schema.py` — `strict_schema` |
| The SOLID evidence | `backend/tests/test_seams.py` — `RecordingProvider` |
| The interface | `backend/llm/base.py` — `LLMProvider` (3 methods, `transcribe` optional) |
| The fallback | `backend/llm/offline.py` — `OfflineProvider` |
| Extension points | `services/generators.py::SPECS`, `models/artifacts.py::ARTIFACT_MODELS` |

### If it goes wrong

- Demo fails → blank the key, `/health` shows `"model": "offline"`, everything
  still runs.
- Anything else fails → `pytest backend/tests -q`, 87 tests, a few seconds.
- Asked something you don't know → "I don't know off the top of my head, let me
  look" and open the file. Reading your own code in front of them is a *good*
  outcome; guessing is not.

### Last thing

Lead with the canvas. Volunteer the rewrite. When they ask about AI assistance,
answer in one honest sentence and immediately offer to open a file — the offer
is the proof.
