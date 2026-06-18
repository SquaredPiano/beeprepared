# Architecture

How BeePrepared is put together, and why. This is the document to read before
changing anything structural.

---

## The shape of the system

```
                    ┌──────────────────────────────────────────┐
  browser ────────▶ │  FastAPI                                 │
      │             │    routes/  deps/  schemas/              │
      │  WebSocket  └───────────────┬──────────────────────────┘
      └───────────────────┐         │ writes a job row
                          │         ▼
                    ┌─────┴──────────────────┐
                    │  Event bus (Redis)     │◀── progress
                    └─────▲──────────────────┘         │
                          │                    ┌───────┴───────┐
                          └────────────────────│  Worker       │
                                               │   handlers/   │
                                               │   services/   │
                                               └───────┬───────┘
                                                       │ commits a bundle
                                                       ▼
                                          ┌────────────────────────┐
                                          │  SQLite  or  Postgres  │
                                          └────────────────────────┘
```

Three processes: an **API** that accepts work and streams progress, a **worker**
that does the work, and **Redis** carrying both the queue and the event stream
between them. All three collapse into one process when Redis is absent - the API
runs its own worker pool and an in-memory event bus - which is what makes
`uvicorn backend.main:app` a complete, working install.

---

## Data model

Five tables. The interesting one is `artifact_edges`.

| Table | Holds |
|---|---|
| `projects` | A workspace, and the canvas layout for it |
| `jobs` | The work queue. Rows, not messages |
| `artifacts` | Every source and every generated study artifact |
| `artifact_edges` | The provenance DAG: "child was derived from parent" |
| `flow_runs` | One execution of a canvas graph |

**The knowledge graph is a DAG, not a tree.** An artifact generated from three
lectures has three `derived_from` edges. That is not decoration - it is what
"multiple inputs" means once it reaches storage, and it is what lets the lineage
view answer "where did this question come from?".

Two invariants are enforced by the database rather than by convention:

- **No cycles.** A trigger walks the lineage on insert and rejects any edge that
  would close a loop. The flow engine also rejects them at compile time; the
  trigger is the backstop for anything that bypasses the engine.
- **`knowledge_core` has indegree zero.** It is the epistemic root of a project.
  Provenance back to the source *file* is tracked by `created_by_job_id`, not by
  an edge, because the core was not *derived from* anything already in the graph.

---

## The job lifecycle

```
   POST /api/jobs
        │
        ├─▶ 1. write the row (status = pending)   ── committed before dispatch
        │
        └─▶ 2. dispatch to Celery ─────────────── may fail; the row survives
                     │
                     ▼
              3. claim_job()  ── atomic; exactly one worker wins
                     │
                     ▼
              4. handler.run(job) ─▶ JobBundle    ── no database writes
                     │
                     ▼
              5. commit_bundle()  ── artifacts + edges + status, one transaction
                     │
                     ▼
              6. notify the flow engine ─▶ schedule whatever this unblocked
```

**Why the row is written before dispatch.** If the broker is down, or the API
restarts between the two, a job that lived only as a message would simply
vanish. As a row it is still there, and a periodic `drain_queue` task enqueues
anything that was never dispatched.

**Why handlers do not write to the database.** A handler returns a `JobBundle`
describing everything it produced. The runner commits it in one transaction. A
handler that throws halfway through - and LLM calls fail often enough that this
is the common case, not the edge case - cannot leave a half-written graph
behind.

**Why the claim must be atomic.** Two workers polling the same queue will
otherwise both see the same pending row and both run it, which means paying for
the same generation twice and racing on the commit. SQLite gets `BEGIN
IMMEDIATE` (take the write lock before the SELECT); Postgres gets `FOR UPDATE
SKIP LOCKED`.

**Why failures are classified.** `is_transient()` separates "the upstream was
busy" from "this payload is wrong". The first goes back on the queue with an
attempt burned; the second is recorded as final, because retrying it would fail
identically while spending tokens.

**Why there is a reaper.** A worker killed mid-job leaves its row in `running`
forever - `claim_job` skips it, so the user's node spins indefinitely with no
error. A periodic task returns jobs stuck past `STALE_JOB_SECONDS` to the queue.

---

## The flow engine

This is what turns the canvas from a diagram into a program.

### Compile

`compile_flow(nodes, edges)` classifies each canvas node as a **source** (it
already points at an artifact) or a **generator** (it will produce one), builds
the adjacency, and topologically sorts with Kahn's algorithm. The result is a
`FlowPlan`: ordered steps, each with its parents and a wave depth.

Validation happens here, before anything runs, and every message names the
offending node so the UI can point at it:

- cycles (Kahn terminates with nodes left over)
- self-loops
- generators with no input
- generators with no output type

The canvas calls this as you wire nodes together, so a broken graph is visible
immediately rather than three failed jobs later.

### Schedule

Steps are grouped by depth into waves. Everything in a wave has all its inputs
satisfied, so it is all dispatched at once - independent branches run
concurrently instead of in draw order.

When a job finishes, `on_job_finished` records the artifact against its node and
calls `advance`, which dispatches every step whose parents are now all complete.
`advance` is idempotent: a step already dispatched is skipped, so a duplicate
completion notification cannot double-run it.

A failed step marks its entire downstream subtree `skipped` rather than leaving
those nodes pending forever.

### Where fan-in and fan-out come from

Both are the same mechanism seen from opposite ends:

- **Fan-in**: a node with three incoming edges is dispatched with three
  `source_artifact_ids`. `CoreMerger` map/reduces them into one context.
- **Fan-out**: a node with three outgoing edges satisfies three downstream steps
  when it completes, and all three dispatch in the next wave.

### Why the engine is stateless

Everything it needs lives in the `flow_runs` row. The job that unblocks a step
may finish in a Celery worker that never saw the API process that started the
run, so progress has to be readable from the database - not from memory.

---

## Multi-source merging

Concatenating three lecture transcripts does not work: the combined document
overruns the context window, and the model attends mostly to whichever source
came first.

`CoreMerger` does map/reduce instead:

1. **Map** - compress each source to a bounded summary, concurrently.
2. **Reduce** - synthesise the summaries into one context, de-duplicating
   concepts.
3. Past `DIRECT_MERGE_LIMIT` sources, reduce pairwise up a tree, so the prompt
   size stays constant no matter how many lectures are wired in.

When two sources disagree, both facts are kept and the disagreement is recorded
in `conflict_notes`. Silently picking one would be a quiet correctness bug in
something a student is about to revise from.

---

## Seams

Three interfaces, each with a local implementation and a hosted one. The choice
is made once at startup and logged; nothing downstream branches on it.

| Interface | Local | Hosted |
|---|---|---|
| `DBInterface` | SQLite (WAL) | Supabase / PostgREST |
| `ObjectStore` | Disk + signed `/api/files` URLs | Cloudflare R2 |
| `LLMProvider` | Offline heuristic engine | OpenRouter, Gemini, Vertex |

The offline provider is not a stub. It derives real output from the source
material with regex and frequency analysis, so the whole pipeline - ingest,
extraction, DAG execution, validation, rendering - runs end to end with no
credentials. That is what the test suite exercises, which is why the tests need
neither a network nor an API key.

---

## Realtime

One WebSocket per project, at `/ws/projects/{id}`.

The client is authenticated and the project ownership checked *before* the
socket is accepted. On connect the server sends a `snapshot` of current job and
flow state, so a client that connects mid-run renders correctly instead of
waiting for the next event.

Three tasks run per connection: an event pump, a heartbeat (idle proxies cut
connections around 60s), and a reader. The reader is what makes a dead
connection detectable - without it a half-open socket holds a subscription
forever.

Events are published to Redis pub/sub, so a Celery worker's progress reaches an
API process it has never met. Without Redis the bus is in-process, and publishing
hops onto the event loop via `call_soon_threadsafe` because worker threads
cannot touch an `asyncio.Queue` directly.

---

## Structured output

Pydantic emits nested models as `$defs` plus `$ref` pointers. Providers accept
that, but cannot enforce it strictly - and a model handed a `$ref`-heavy schema
drifts: it stops treating field bounds as binding and runs a single string field
until it hits the output limit. A mind map generated this way burned 100k
characters and failed.

`_strict_schema()` inlines the definitions, marks every object closed and
fully-required, and sends `strict: true`. Same tree, bounded depth, two-second
response.

Truncation is also detected explicitly: `finish_reason == "length"` raises
`TruncatedResponse` rather than surfacing three retries later as a confusing
"unterminated string" JSON parse error.

---

## Things deliberately not done

- **No vector store.** Retrieval is not the bottleneck; a lecture fits in a
  modern context window, and the Knowledge Core is a better summary than
  top-k chunks would be.
- **No streaming generation.** Artifacts are structured documents that are
  validated before they are shown. A half-rendered quiz is not useful.
- **Artifacts are append-only.** Refining produces a new artifact with an edge
  back to the old one, so nothing a user already exported changes underneath
  them.
