# Backend walkthrough

This is a guided read of every Python file in `backend/`. It is not a summary and
it is not an architecture document — `docs/ARCHITECTURE.md` is the architecture
document and `docs/INTERVIEW_GUIDE.md` is the one that tells you what to say.
This set tells you what the code *is*, line by line, so that you can open any
file, land on any line, and say what it does and why it is there.

Each document quotes the real code in short blocks and explains underneath.
Line numbers are given in the form `database.py:120` so you can jump straight
to a line while someone is watching.

## Reading order

If you read all of it, read it in numeric order — the numbers follow the
dependency direction, so nothing forward-references much.

If you only have time for part of it, read it in this order instead. It is
ordered by how likely a question is to land there and how hard the answer is to
improvise.

1. **[09-flow-engine.md](09-flow-engine.md)** — the canvas compiler and the
   scheduler. This is the headline of the project and the hardest part to fake
   understanding of. It also holds the concurrency bug, which is the best
   engineering story you have.
2. **[03-database.md](03-database.md)** — one file, four separate correctness
   invariants. `BEGIN IMMEDIATE`, the atomic claim, the terminal guard, the
   transaction helper. Expect to be asked why SQLite.
3. **[10-jobs-and-workers.md](10-jobs-and-workers.md)** — the transaction
   boundary. Where the handler stops and the commit starts, and why that line is
   drawn there and not somewhere else.
4. **[07-handlers.md](07-handlers.md)** — the contract that shapes everything
   above it. Handlers do not write to the database. Once you can say why, most of
   the rest of the design explains itself.
5. **[05-llm.md](05-llm.md)** — the subtlest bug in the project lives here, and
   `llm/schema.py` is short enough to put on screen and read aloud.
6. Everything else, in numeric order.

## The documents

| | Covers |
|---|---|
| [01-config-and-startup.md](01-config-and-startup.md) | `core/config.py`, `env.py`, `main.py`, `celery_app.py` |
| [02-models.md](02-models.md) | `models/artifacts.py`, `models/jobs.py`, `models/graph.py` |
| [03-database.md](03-database.md) | `services/database.py` |
| [04-files.md](04-files.md) | `services/files.py`, `api/routes/files.py` |
| [05-llm.md](05-llm.md) | `llm/base.py`, `schema.py`, `openrouter.py`, `offline.py`, `factory.py` |
| [06-pipeline.md](06-pipeline.md) | `pipeline/ingestion.py`, `extraction.py`, `media.py`, `cleaning.py`, `knowledge.py` |
| [07-handlers.md](07-handlers.md) | `handlers/base.py`, `sources.py`, `ingest_handler.py`, `generate_handler.py`, `refine_handler.py` |
| [08-generation.md](08-generation.md) | `services/generators.py`, `services/merger.py`, `services/exports/` |
| [09-flow-engine.md](09-flow-engine.md) | `services/flow/plan.py`, `services/flow/engine.py` |
| [10-jobs-and-workers.md](10-jobs-and-workers.md) | `services/job_runner.py`, `dispatcher.py`, `events.py`, `tasks.py` |
| [11-api.md](11-api.md) | `api/deps.py`, `api/schemas.py`, `api/routes/*` |
| [12-tests.md](12-tests.md) | `tests/conftest.py` and the four test modules |

## The shape of the system, in one paragraph

A request arrives at FastAPI. If it creates work, the route writes a job row to
SQLite and commits it *before* dispatching anything, then hands the job to
either Celery or an in-process worker pool. A worker claims the row atomically,
runs a handler, and the handler returns a bundle of artifacts and edges without
writing anything itself. The runner commits that bundle in one transaction, marks
the job complete, publishes an event, and tells the flow engine, which decides
what the completed job just unblocked and queues the next wave. The browser sees
all of it over a WebSocket.

The dependency direction is one-way: `api` depends on `handlers`, `handlers`
depend on `services` and `pipeline`, and those depend on `llm` and `models`.
Nothing lower ever imports anything higher. If you are ever unsure which
direction an import should go, that sentence is the answer.

## Two things to have ready before you open any file

**Why the job row is written before dispatch.** A job that existed only as a
broker message would disappear if the broker were down. As a row it survives, and
`drain_queue` re-dispatches anything that was never enqueued.

**Why handlers do not write.** LLM calls fail often enough that a handler
throwing halfway through is the common case, not the edge case. If handlers wrote
as they went, that would leave a half-written graph behind. Returning a bundle
and committing it once makes partial failure impossible to observe.

## Verification commands

```bash
backend/venv/bin/python -m pytest -q -p no:warnings          # 172 passed
backend/venv/bin/python -m pyflakes $(find backend -name "*.py" -not -path "*/venv/*")
```

The virtualenv is at `backend/venv/`. The system `python3` does not have the
dependencies, so always invoke it as `backend/venv/bin/python`.
