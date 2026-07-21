# Architecture

How BeePrepared is put together, and why. Read this before changing anything
structural.

---

## Shape

```
                    ┌──────────────────────────────────────┐
  browser ────────▶ │  FastAPI                             │
      │             │    api/routes  api/deps  api/schemas │
      │  WebSocket  └───────────────┬──────────────────────┘
      └───────────────────┐         │ writes a job row
                          │         ▼
                    ┌─────┴────────────────┐
                    │  Event bus (Redis)   │◀── progress
                    └─────▲────────────────┘         │
                          │                  ┌───────┴────────┐
                          └──────────────────│  Worker        │
                                             │   handlers/    │
                                             │   services/    │
                                             │   pipeline/    │
                                             └───────┬────────┘
                                                     │ commits a bundle
                                                     ▼
                                            ┌──────────────────┐
                                            │  SQLite + files  │
                                            └──────────────────┘
```

Three processes: an **API** that accepts work and streams progress, a **worker**
that does it, and **Redis** carrying the queue and the event stream between
them. Without Redis all three collapse into one: the API runs its own worker
pool and an in-process bus, so `uvicorn backend.main:app` is a complete install.

## Packages

| Package | Responsibility |
|---|---|
| `api/` | HTTP and WebSocket surface. One route module per resource |
| `handlers/` | One class per job type. Pure: they return work, never write it |
| `pipeline/` | Source to knowledge core: ingestion, extraction, media, cleaning |
| `services/` | Persistence, files, events, queueing, generation, flow execution |
| `llm/` | Model providers behind one interface |
| `models/` | The domain vocabulary every layer shares |

The dependency direction is one-way: `api` → `handlers` → `services`/`pipeline`
→ `llm`/`models`. Nothing lower imports anything higher.

---

## Where the SOLID principles actually show up

Not as decoration. Each one is doing a specific job here.

**Single responsibility.** `JobExecutor` owns the transaction boundary.
`FlowCompiler` compiles; `FlowEngine` schedules. `ExtractionService` routes to a
reader; `DocumentReader` reads documents; `Transcriber` handles speech. Each of
those was one class before the split, and each was hard to test because you
could not exercise one behaviour without the others.

**Open/closed.** Adding an artifact type is a new entry in `SPECS`
(`services/generators.py`) and one in `ARTIFACT_MODELS`. No handler changes, no
new branch in the runner, no new validation rule. That is why going from five
types to eight touched two dictionaries.

**Liskov.** `OfflineProvider` and `OpenRouterProvider` are interchangeable
everywhere. The test suite runs the real handlers against the offline one, which
only works because nothing downstream can tell them apart.

**Interface segregation.** `LLMProvider` has three methods, and `transcribe` is
optional with a default that raises. A caller that only generates text does not
depend on audio. `FileStore` exposes put/get/sign, not a general filesystem.

**Dependency inversion.** Every handler takes its collaborators as constructor
arguments with a sensible default:

```python
def __init__(self, database=None, resolver=None, generator=None, merger=None, exporter=None):
    self._database = database or get_database()
```

Production passes nothing; tests pass fakes. The handlers depend on
`LLMProvider` and `Database`, never on OpenRouter or SQLite directly.

---

## Data model

Five tables. The interesting one is `artifact_edges`.

| Table | Holds |
|---|---|
| `projects` | A workspace and its canvas layout |
| `jobs` | The work queue. Rows first, messages second |
| `artifacts` | Every source and every generated artifact |
| `artifact_edges` | The provenance DAG: child was derived from parent |
| `flow_runs` | One execution of a canvas graph |
| `chat_messages` | The assistant's conversation |

**Provenance is a DAG, not a tree.** An artifact generated from three lectures
has three `derived_from` edges. That is what "multiple inputs" means once it
reaches storage, and it is what lets lineage answer "where did this question
come from?".

**The knowledge core is the root.** It has indegree zero: provenance back to the
source *file* is carried by `created_by_job_id`, not by an edge, because the
core was not derived from anything already in the graph.

---

## The job lifecycle

```
   POST /api/jobs
        │
        ├─▶ 1. write the row (pending)     ── committed before dispatch
        │
        └─▶ 2. dispatch                    ── may fail; the row survives
                     │
                     ▼
              3. claim_job()               ── atomic; exactly one worker wins
                     │
                     ▼
              4. handler.run(job) ─▶ JobBundle   ── no database writes
                     │
                     ▼
              5. commit_bundle()           ── artifacts + edges + status, one txn
                     │
                     ▼
              6. notify the flow engine    ── schedule what this unblocked
```

**Why the row precedes dispatch.** A job that existed only as a message would
vanish if the broker were down, or if the API restarted between the two. As a
row it survives, and `drain_queue` re-dispatches anything that was never
enqueued.

**Why handlers do not write.** They return a `JobBundle`; the runner commits it
in one transaction. LLM calls fail often enough that a handler throwing midway
is the common case, not the edge case, and it must not leave a half-written
graph.

**Why the claim must be atomic.** Two workers polling the same queue would
otherwise both see the same pending row, pay for the same generation twice and
race on the commit. `BEGIN IMMEDIATE` takes the write lock before the read.

**Why failures are classified.** `is_transient()` separates "the upstream was
busy" from "this payload is wrong". The first is requeued; the second is final,
because retrying it fails identically while spending tokens. Status codes are
matched only where labelled as such — a bare digit match would retry any error
whose text happened to contain `502`, including artifact identifiers.

**Why there is a reaper.** A worker killed mid-job leaves its row `running`
forever, so `claim_job` skips it and the node spins with no error ever
surfacing.

---

## The flow engine

This is what makes the canvas a program rather than a diagram.

### Compile

`FlowCompiler` classifies each node as a **source** (already points at an
artifact) or a **generator** (will produce one), builds the adjacency and
topologically sorts with Kahn's algorithm. The result is a `FlowPlan`: ordered
steps, each with its parents and a wave depth.

Validation happens here, and every message names the offending node:

- cycles (Kahn terminates with nodes left over)
- self-loops
- generators with no input
- generators with no output type

The canvas calls this as you wire nodes together, so a broken graph is visible
before any tokens are spent.

### Schedule

Steps are grouped by depth into waves. Everything in a wave has its inputs
satisfied, so it dispatches at once and independent branches run concurrently.

When a job finishes, `on_job_finished` records the artifact against its node and
calls `advance`, which dispatches every step whose parents are now complete.
`advance` is idempotent, so a repeated completion cannot double-run a step. A
failed step marks its entire downstream subtree `skipped` rather than leaving
those nodes pending forever.

### Fan-in and fan-out

The same mechanism from opposite ends:

- **Fan-in** — a node with three incoming edges is dispatched with three
  `source_artifact_ids`, merged by `CoreMerger`.
- **Fan-out** — a node with three outgoing edges satisfies three downstream
  steps when it completes; all three dispatch in the next wave.

### Why the engine is stateless

Everything lives in the `flow_runs` row. The job that unblocks a step may finish
in a worker that never saw the process which started the run, so progress has to
be readable from the database.

---

## Multi-source merging

Concatenating three transcripts does not work: the combined text overruns the
context window and the model attends mostly to whichever came first.

`CoreMerger` map/reduces instead — compress each source concurrently, then
synthesise. Past three sources the synthesis runs pairwise up a tree, so prompt
size stays constant however many lectures are wired in.

When sources disagree, both facts are kept and the disagreement is recorded in
`conflict_notes`. Silently picking one would be a quiet correctness bug in
something a student is about to revise from.

---

## Structured output

Pydantic emits nested models as `$defs` plus `$ref`. Providers accept that but
cannot enforce it strictly, and a model given a reference-heavy schema drifts:
it stops treating field bounds as binding and runs one string field until it
hits the output limit. A mind map generated that way burned 100k characters and
failed three retries.

`strict_schema()` inlines the definitions, marks every object closed and
fully-required, and sends `strict: true`. Same tree, two-second response.
Truncation is detected explicitly — `finish_reason == "length"` raises rather
than surfacing later as an unterminated-string parse error.

---

## One model, two jobs

OpenRouter serves both generation and transcription. Audio is normalised to
16 kHz mono WAV and sent as an `input_audio` content part, so there is no
separate speech vendor, no second key and no second failure mode.

---

## Deliberately not built

- **No vector store.** A lecture fits in a modern context window, and the
  knowledge core is a better summary than top-k chunks.
- **No streaming generation.** Artifacts are validated before they are shown; a
  half-rendered quiz is not useful.
- **No multi-tenancy.** The backend serves one local workspace. Ownership checks
  exist and are enforced, but there is no identity provider to integrate.
- **Artifacts are append-only.** Refining produces a new artifact linked to the
  old one, so nothing already exported changes underneath the user.
