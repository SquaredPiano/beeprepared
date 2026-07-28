# backend/services/database.py — line-by-line

## What this file is for

This is the only place in the backend that talks to SQLite. Nothing else opens a connection, nothing else writes SQL. Every route handler, every job handler, the flow engine and the Celery tasks all go through this one class. That is deliberate: if persistence is one file, then the rules about persistence are enforceable in one file, and you can point at them.

The file does two quite different things. The first half is a small generic table layer — `select`, `insert`, `update`, `delete` — which exists so the rest of the codebase can keep the query style it had when the store was Supabase. The second half is the job queue, and that is where the interesting code is.

There are four correctness invariants held here. If an interviewer asks "what does this file actually guarantee", these are the four sentences:

1. **A pending job is claimed by exactly one worker.** `claim_job` takes SQLite's write lock before it reads, so two workers polling the same queue cannot both walk away with the same row. Without this you run the same generation twice and pay for the same model call twice.
2. **A job's output lands whole or not at all.** `commit_bundle` writes the artifacts, the provenance edges and the job's terminal status inside one transaction. There is no state where the artifact exists but the job still says running, and no state where the job says completed but the edge that puts the artifact on the canvas is missing.
3. **A terminal status is final.** Once a job is `completed`, `failed` or `cancelled`, nothing can move it. `commit_bundle`, `fail_job` and `cancel_job` each check this before writing. This is what stops a slow duplicate worker from marking a job failed after the real one already succeeded.
4. **No job stays `running` forever.** `claim_job` stamps `started_at`; the requeue paths clear it. A reaper elsewhere in the codebase uses that timestamp to find rows whose worker died, and puts them back on the queue.

Everything below walks the file in order.

---

## The header: lines 1 to 29

```python
"""SQLite persistence: projects, the job queue, and the artifact graph."""

from __future__ import annotations
```

`database.py:3`. `from __future__ import annotations` makes every type annotation in the file a string that is never evaluated at import time. Two practical effects: forward references like `-> JobModel` work without quotes, and annotations cost nothing at runtime. It is boilerplate in a modern Python file, but it is why `Optional[Path]` on line 130 does not need to be quoted.

```python
import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
```

`database.py:5-13`. Standard library only. Worth noticing that there is no SQLAlchemy, no ORM, no migration framework. The whole persistence layer is `sqlite3` plus about five hundred lines. That is a defensible choice for a project this size and it is worth being able to say why: an ORM would add a mapping layer between you and the exact SQL that `claim_job` depends on, and the correctness of `claim_job` is a property of the exact SQL.

```python
from backend.core.config import get_settings
from backend.models.graph import JobBundle
from backend.models.jobs import TERMINAL_STATUSES, JobModel
```

`database.py:15-17`. Three internal imports and they tell you what this file couples to. `get_settings` for the database path and the retry limit. `JobBundle` is the object a handler returns — artifacts, edges and a result dict, defined in `backend/models/graph.py:42`. `TERMINAL_STATUSES` is a frozenset of `{"completed", "failed", "cancelled"}` defined in `backend/models/jobs.py`. That frozenset is invariant three; it is imported rather than written out here so the queue and the API cannot drift apart on what "finished" means.

```python
logger = logging.getLogger(__name__)

Filters = Iterable[Tuple[str, Any]]
```

`database.py:19-21`. `Filters` is a type alias for the filter format used everywhere below: a sequence of `(column, expression)` pairs like `("id", "eq.abc-123")`. Naming it once means the five methods that take filters all agree on the shape.

```python
JSON_COLUMNS = {
    "projects": {"canvas_state"},
    "jobs": {"payload", "result"},
    "artifacts": {"content"},
    "flow_runs": {"plan", "node_states", "result"},
    "chat_messages": {"metadata"},
}
```

`database.py:23-29`. SQLite has no JSON column type — everything is TEXT. This table is the manual replacement: it says which columns hold a JSON document and therefore need `json.dumps` on the way in and `json.loads` on the way out. `_encode` (line 479) and `_decode` (line 496) are the only two functions that read it.

This matters more than it looks. A whole knowledge core is a `content` blob on an artifact row. A flow plan and the per-node state of a running flow are `plan` and `node_states` on a `flow_runs` row. If this dict were missing an entry, the caller would silently get back a JSON string where it expected a dict, and the failure would surface somewhere far away.

---

## The schema: lines 31 to 110

```python
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

`database.py:31-33`. The schema is one big string executed once at startup with `executescript`.

`journal_mode=WAL` is write-ahead logging. The default SQLite journal mode is `DELETE`, and in that mode a writer blocks every reader for the duration of its transaction. This backend has an API process serving reads — polling a job's status, listing a project's artifacts — while a worker process is writing. In `DELETE` mode a `commit_bundle` writing a large knowledge core would make a concurrent `GET /api/jobs/{id}` fail with "database is locked". In WAL mode readers read from the main database file while the writer appends to a separate WAL file, so reads never block on a write and a write never blocks on a read. Only writers block writers.

Note that `journal_mode` is a persistent property of the database file, not of the connection. Setting it here once is enough; the repeat on line 147 is belt and braces.

`foreign_keys=ON` is the opposite. SQLite ships with foreign key enforcement **off** by default, for backward compatibility, and the setting is **per connection** — it is not stored in the file. That is why line 148 sets it again on every new connection, and why setting it only here would have been a bug. Every table below declares `ON DELETE CASCADE` on its project reference; without the pragma on the connection doing the delete, those cascades do nothing and deleting a project leaves behind orphaned artifacts that still turn up in scans.

```sql
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    user_id       TEXT,
    canvas_state  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

`database.py:35-43`. Ids are TEXT holding a UUID string, not integers. This is why `insert` can generate an id in Python (line 463) instead of waiting for the database to assign one, which in turn is what lets a handler build a whole `JobBundle` of artifacts with ids already set, before any of them are written.

`user_id` is **nullable**. That is worth knowing because ownership is checked elsewhere, and the nullability is the reason the check has to be written carefully. The check lives in `backend/api/deps.py:48`:

```python
if project.get("user_id") != user_id:
    raise HTTPException(status_code=403, detail="Access denied")
```

An earlier version of that check was `if owner and owner != user_id`, which short-circuits when `owner` is `None`. A project with a NULL owner was therefore readable by anybody, while `list_projects` — which filters with `("user_id", f"eq.{user_id}")` and so never matches NULL — hid it. Read said yes and list said no, for the same row. The current form is a plain inequality, so a NULL owner matches nobody and the two agree. There are tests for exactly this at `backend/tests/test_api.py:379` and `:392`.

To be precise about this file's role: `database.py` does not enforce ownership. It stores the column, indexes it (line 107), and supports the `eq.` filter that the list query uses. The policy is in `deps.py`. If an interviewer asks where authorisation happens, that is the honest answer.

`canvas_state` holds the entire React Flow document — nodes, edges, viewport — as a JSON blob on the project row.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    payload        TEXT NOT NULL DEFAULT '{}',
    result         TEXT NOT NULL DEFAULT '{}',
    attempts       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    completed_at   TEXT,
    error_message  TEXT
);
```

`database.py:45-57`. This is the queue. There is no separate queue table and no broker-of-record — Redis carries a *notification* that a job exists, but the job row in SQLite is the truth. That is the whole point of step one of the lifecycle: the row is written and committed before anything is dispatched, so if Redis is down or the dispatch call throws, the work is still recorded and the drain task at `backend/tasks.py:55` will pick it up later.

Three columns carry the invariants:

- `status` — the state machine. `pending` → `running` → one of `completed` / `failed` / `cancelled`, with a `running` → `pending` edge for retries.
- `attempts` — incremented on every claim, not on every failure. Read that again, because it changes the arithmetic: a job that has been claimed three times has `attempts = 3` even if it has never been retried. `fail_job` and `reap_stale_jobs` both compare against `job_max_attempts` (default 3).
- `started_at` — nullable, and this is the column the reaper keys off. It is set on claim and cleared on requeue.

There is no `updated_at` on jobs. The lifecycle timestamps (`created_at`, `started_at`, `completed_at`) carry the information instead, and `update` on line 250 knows not to add one.

```sql
CREATE TABLE IF NOT EXISTS artifacts (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type              TEXT NOT NULL,
    content           TEXT NOT NULL DEFAULT '{}',
    created_by_job_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT
);
```

`database.py:59-67`. One row per study artifact, including the knowledge core itself. `type` distinguishes them — `knowledge_core`, `quiz`, `flashcards`, `notes`, and so on. `content` is the JSON blob.

`created_by_job_id` is provenance in the simple direction: which job produced this. It is a plain TEXT column with no foreign key, deliberately — if a job row were ever removed, you would rather keep the artifact with a dangling job reference than cascade the artifact away.

```sql
CREATE TABLE IF NOT EXISTS artifact_edges (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_artifact_id TEXT NOT NULL,
    child_artifact_id  TEXT NOT NULL,
    relationship_type  TEXT NOT NULL DEFAULT 'derived_from',
    created_at         TEXT NOT NULL,
    UNIQUE (parent_artifact_id, child_artifact_id, relationship_type)
);
```

`database.py:69-77`. This is the artifact graph — the record of what was derived from what. A quiz generated from a knowledge core gets an edge with the core as parent and the quiz as child.

The `UNIQUE` constraint on line 76 is load-bearing. It is what makes edge writing idempotent: `commit_bundle` uses `INSERT OR IGNORE` (line 325), and the combination means that re-committing the same bundle, or two paths in a flow both recording the same derivation, produces one edge rather than duplicates. Without the constraint the `OR IGNORE` would have nothing to ignore against and the canvas would render the same link several times.

**Worth knowing.** `parent_artifact_id` and `child_artifact_id` have no `REFERENCES artifacts(id)`. Only `project_id` has a foreign key. So deleting a project cascades its edges away, but deleting a single artifact leaves its edges behind pointing at nothing. In practice artifacts are not individually deleted, and the loose coupling is what allows `commit_bundle` to write an edge and an artifact in either order inside the same transaction. But an interviewer looking at this schema may well ask, and the honest answer is that it is a deliberate looseness with a known consequence.

```sql
CREATE TABLE IF NOT EXISTS flow_runs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'running',
    plan         TEXT NOT NULL DEFAULT '{}',
    node_states  TEXT NOT NULL DEFAULT '{}',
    result       TEXT NOT NULL DEFAULT '{}',
    ...
);
```

`database.py:79-89`. One row per execution of the canvas. `plan` is the compiled DAG — the steps and their dependencies, frozen at launch so that editing the canvas mid-run does not change what is running. `node_states` is a JSON map from node id to that node's status and produced artifact id. The flow engine reads `node_states`, mutates it and writes it back, and it does that inside `database.transaction()` (see `backend/services/flow/engine.py:118` and `:207`) precisely because it is a read-modify-write on a single JSON blob. Two parents of a fan-in node finishing simultaneously would otherwise each overwrite the other's completion.

```sql
CREATE TABLE IF NOT EXISTS chat_messages (...);
```

`database.py:91-99`. Chat history, optionally scoped to an artifact via the nullable `artifact_id`. Not part of the job lifecycle.

```sql
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project      ON jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type    ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_edges_parent      ON artifact_edges(parent_artifact_id);
CREATE INDEX IF NOT EXISTS idx_edges_child       ON artifact_edges(child_artifact_id);
CREATE INDEX IF NOT EXISTS idx_projects_user     ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_flow_runs_project ON flow_runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_project      ON chat_messages(project_id, created_at);
```

`database.py:101-109`. Each of these matches a query that actually exists.

`idx_jobs_status(status, created_at)` is the important one. It is a composite index in exactly the order `claim_job` needs on line 287: filter on `status='pending'`, order by `created_at ASC`, take one. With this index SQLite walks straight to the oldest pending row; without it, claiming a job scans the entire jobs table, and it does so while holding the write lock, which means every other writer waits behind it.

`idx_edges_parent` and `idx_edges_child` support the two traversal directions in `get_child_edges` and `get_parent_edges`. Both directions are needed because the flow engine walks down from a node to find what it unblocked, and the API walks up from an artifact to show its provenance.

---

## Two helpers: lines 113 to 118

```python
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

`database.py:113-114`. Every timestamp in the database goes through this function. Two things are guaranteed as a result: it is always UTC, and it is always the same ISO 8601 format.

That consistency is not cosmetic. `reap_stale_jobs` on line 402 compares timestamps with a plain SQL string comparison, `started_at < ?`. ISO 8601 strings are lexicographically ordered *only if* they share the same format and offset. Because everything here is `...+00:00`, string comparison is a correct time comparison. If one code path had written a naive local timestamp, the reaper would silently mis-order rows and either reap live jobs or ignore dead ones.

```python
def _new_id() -> str:
    return str(uuid.uuid4())
```

`database.py:117-118`. UUID4 as a string. Generated client-side, which is what lets a handler construct an artifact with an id before the row exists.

---

## The Database class: lines 121 to 139

```python
class Database:
    """
    The single persistence boundary for the whole backend.

    One connection per thread, since SQLite connections are not thread-safe.
    Writers are serialised behind a lock and take the write lock up front, which
    is what makes `claim_job` safe when several workers poll the same queue.
    """
```

`database.py:121-128`. The docstring states the two mechanisms up front. Both matter and they cover different cases, which is a distinction worth being able to draw:

- The Python lock serialises **threads inside one process**.
- `BEGIN IMMEDIATE` plus `busy_timeout` serialises **separate processes** on the same file — the API process and a Celery worker process.

```python
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or get_settings().database_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
```

`database.py:130-132`. The path comes from settings (`backend/core/config.py:155`, which resolves to `.storage/beeprepared.db` under the backend directory) but can be overridden, which is what the test fixtures do. `expanduser` handles a `~` in a configured path. `mkdir(parents=True, exist_ok=True)` creates the directory tree if it is not there, because SQLite will happily create a database file but will not create the directory it lives in — on a fresh clone the first startup would otherwise fail with "unable to open database file".

```python
        self._local = threading.local()
        self._write_lock = threading.RLock()
```

`database.py:133-134`. Two pieces of state, and both need explaining.

`threading.local()` is a container whose attributes are per-thread. Setting `self._local.connection` on one thread does not set it on another. This is how the connection pool works — there is no pool, there is one connection per thread created lazily. The reason is that a `sqlite3.Connection` is not safe to share between threads, and pysqlite enforces this by default: `check_same_thread` defaults to `True`, so using a connection from a thread other than the one that created it raises `ProgrammingError`. Thread-locals mean that never happens, and the default check stays on as a safety net rather than being disabled.

`threading.RLock` — a *re-entrant* lock, not a plain `Lock`. This is not a stylistic choice. The same thread acquires this lock more than once whenever a caller wraps several operations in `transaction()`: the outer `transaction()` takes it, and then an `insert` inside the block takes it again. A plain `Lock` would deadlock the thread against itself on the second acquire. An `RLock` counts acquisitions by the owning thread and only releases at zero. The flow engine at `engine.py:118` does exactly this — `with self._database.transaction():` around a block that calls `insert` and `update`.

```python
        with self._write_lock:
            self._connection.executescript(SCHEMA)

        logger.info("Database ready at %s", self.path)
```

`database.py:136-139`. The schema is applied once, on the constructing thread, under the write lock.

Note what is *not* used here: `_transaction`. This is deliberate. `PRAGMA journal_mode=WAL` cannot be executed inside an open transaction — SQLite refuses to change the journal mode of a database that is in one. `executescript` also issues an implicit COMMIT before it runs its script, so wrapping it in `BEGIN IMMEDIATE` would fight with it. The raw lock plus `executescript` is the right tool for schema application specifically.

Every statement uses `IF NOT EXISTS`, so this is safe to run on every startup. That is the migration story: there isn't one. New columns would require a hand-written `ALTER TABLE`. For a project of this size that is a reasonable trade, but be ready to say it plainly rather than pretend otherwise.

---

## The connection property: lines 141 to 151

```python
    @property
    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
```

`database.py:141-144`. `getattr` with a default rather than `self._local.connection`, because a thread that has never touched the database has no such attribute at all and a direct access would raise `AttributeError`. Lazy creation on first use per thread.

```python
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
```

`database.py:145`. Three arguments and two of them are decisions.

`timeout=30` is the busy timeout in seconds. When another connection holds the write lock, the default SQLite behaviour is to fail *immediately* with `SQLITE_BUSY` — "database is locked". Setting a timeout makes SQLite retry internally for up to thirty seconds before giving up. Since `commit_bundle` can be writing a large knowledge core, and a `BEGIN IMMEDIATE` from another process has to wait for it, without this every cross-process collision would surface as an error instead of a short wait.

`isolation_level=None` is the one to be able to explain. By default, pysqlite (the `sqlite3` module) manages transactions for you: it silently issues a `BEGIN` before the first DML statement and a `COMMIT` before certain other statements. That implicit `BEGIN` is a *deferred* begin, and deferred is exactly what `claim_job` must not have. Setting `isolation_level=None` puts the connection in autocommit mode, which turns pysqlite's transaction management off entirely and hands control to this file. From then on, a statement runs and commits on its own unless there is an explicit `BEGIN` open — and the only place that issues one is `_transaction` on line 176, which issues `BEGIN IMMEDIATE`.

So: `isolation_level=None` on line 145 is what makes `BEGIN IMMEDIATE` on line 176 possible, and `BEGIN IMMEDIATE` on line 176 is what makes invariant one hold. They are one decision in two places.

```python
            connection.row_factory = sqlite3.Row
```

`database.py:146`. By default a query returns plain tuples and you index by position. `sqlite3.Row` returns a mapping-like object supporting `row["status"]` and `row.keys()`. `_decode` on line 500 iterates `row.keys()` to build a dict, which is only possible with this set. Without it, every accessor in the file breaks.

```python
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
```

`database.py:147-149`. Three pragmas on every new connection, and they are not equally necessary.

`journal_mode=WAL` is persistent in the file, so this repeat is redundant. It is harmless and it documents the intent at the point where a connection is made.

`foreign_keys=ON` is **not** redundant. It is per-connection and defaults to off. Every connection this backend opens must set it or the `ON DELETE CASCADE` clauses in the schema are inert on that connection. Concretely: a worker thread that opened its connection without this pragma would delete a project and leave its jobs, artifacts, edges, flow runs and chat messages behind as orphans.

`busy_timeout=30000` is the same thirty seconds already set by `timeout=30` on line 145 — `timeout` is implemented as `busy_timeout` under the hood. Stating it explicitly in milliseconds makes the value visible next to the other pragmas rather than hidden in a keyword argument.

```python
            self._local.connection = connection
        return connection
```

`database.py:150-151`. Cached on the thread-local and returned. Note that connections are never closed. For a long-lived API process and a worker pool with a fixed thread count that is fine; the connections live as long as the threads do.

---

## The transaction helper: lines 153 to 205

This is the most important fifty lines in the file and the second most likely place for an interviewer to stop. Three pieces: `_transaction` itself (153-182), the `_abandon` helper it falls back on when something goes wrong (184-199), and the public `transaction` wrapper (201-205).

```python
    @contextmanager
    def _transaction(self):
        """
        Hold the write lock for one atomic unit of work.

        Nesting joins the transaction already open on this thread instead of
        issuing a second `BEGIN`, which SQLite rejects. That is what lets a
        caller wrap several writes that each transact on their own.

        Rollback is on `BaseException`, not `Exception`: a cancellation or an
        interrupt that escaped with the transaction still open would leave the
        connection unusable for every later write on this thread.

        The `COMMIT` is inside the `try` for the same reason. A commit can fail
        on its own - a full disk, an I/O error, a busy timeout expiring - and
        would otherwise leave the transaction open behind it.
        """
```

`database.py:153-169`. The docstring is three paragraphs and each one is a fix. The first is the nesting rule. The second and third are the same bug found twice, a year apart in reading order: an exception that escapes with `BEGIN IMMEDIATE` still open poisons the thread's connection for every later write. The second paragraph closes the case where the *body* raises something that is not an `Exception`; the third closes the case where the `COMMIT` itself raises. Both are covered below.

```python
        with self._write_lock:
            connection = self._connection
```

`database.py:170-171`. The Python lock is acquired first, before any SQL. Within this process, only one thread can be inside a write transaction at a time. Because it is an `RLock`, the same thread may already hold it from an enclosing `transaction()`.

```python
            if connection.in_transaction:
                yield connection
                return
```

`database.py:172-174`. The nesting case. `connection.in_transaction` is a pysqlite attribute that reports whether a transaction is open; in autocommit mode (which line 145 selected) it is `True` only after an explicit `BEGIN`. So this is precisely "am I already inside a `_transaction` on this thread".

If so, this call **joins** the existing transaction rather than opening a second one. SQLite rejects a nested `BEGIN` with "cannot start a transaction within a transaction". Without this branch, the flow engine's `with self._database.transaction():` block would throw on the first `insert` it made.

Two consequences to be able to state:

- There are **no savepoints**. A nested block that fails does not roll back only its own work — the exception propagates up to the outermost `_transaction`, which rolls back everything. That is the semantics you want here (the flow engine wants all-or-nothing on scheduling a wave), but it is worth naming rather than glossing.
- The nested branch has no `try`/`except`. It does not need one; the outer frame owns rollback.

```python
            connection.execute("BEGIN IMMEDIATE")
```

`database.py:176`. **This is invariant one.**

SQLite has three begin modes. `BEGIN` (also written `BEGIN DEFERRED`, and the default) acquires no lock at all. The transaction is "open" but nothing is reserved; a read acquires a read snapshot at the first `SELECT`, and the write lock is only acquired when the first write statement runs. `BEGIN IMMEDIATE` acquires the write lock at `BEGIN` time, before any statement runs. (`BEGIN EXCLUSIVE` additionally blocks readers, which WAL makes unnecessary here.)

Why that matters for `claim_job`. The claim is a read followed by a write: `SELECT id FROM jobs WHERE status='pending' ... LIMIT 1`, then `UPDATE jobs SET status='running' WHERE id=?`. Under a deferred begin, two workers can both execute the `SELECT` and both see the same row, because a read takes no write lock and nothing stops the second reader. Then both attempt the `UPDATE`. The first wins. The second is holding a snapshot that is now stale, and SQLite fails it with `SQLITE_BUSY_SNAPSHOT` — which, importantly, `busy_timeout` does **not** retry, because retrying cannot help a stale snapshot; the transaction has to be rolled back and started over. This code has no such retry loop, so the second worker's claim would raise out of `claim_job` into the worker loop. And in the versions of this race where the timing lands differently, you get the worse outcome: both workers proceed, both call the model, you pay twice, and then they race on the commit — where the terminal guard on line 311 catches the loser, but only after the money is spent.

`BEGIN IMMEDIATE` removes the whole class of problem. The write lock is taken before the `SELECT`, so the `SELECT` reads a state that no other writer can be modifying. The second worker blocks at `BEGIN IMMEDIATE` — for up to thirty seconds, thanks to `busy_timeout` — and when it gets in, its `SELECT` sees the row already marked `running` and skips to the next one, or returns `None`.

The comparison an interviewer may fish for: in PostgreSQL you would write `SELECT ... FOR UPDATE SKIP LOCKED`, which lets each worker lock and take a *different* row concurrently. SQLite has exactly one writer at a time, so there is nothing to skip — but the guarantee you actually need, "exactly one worker gets any given row", is delivered by `BEGIN IMMEDIATE` plus `busy_timeout`. The second worker waits instead of skipping. For a queue with a handful of workers and jobs that take tens of seconds each, waiting a few milliseconds at the claim is free.

There is a test for this at `backend/tests/test_pipeline.py:448`, `test_racing_workers_partition_the_queue`, which runs six real threads against twenty-four queued jobs and asserts that the union of what they claimed equals the queue and nothing was claimed twice. Be honest about what that test proves, though: within one process, the `RLock` on line 170 already guarantees it. The threaded test exercises the lock. `BEGIN IMMEDIATE` is what makes the same guarantee hold when the API process and a separate Celery worker process are both polling the same file, which is the deployment that actually runs.

```python
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                self._abandon(connection)
                raise
```

`database.py:177-182`. The body runs, then the commit, and if either of them raises the connection is put back into autocommit and the error is re-raised.

`except BaseException` rather than `except Exception` is a fix for a real bug, and it is a good story to be able to tell. Python's exception hierarchy has `BaseException` at the root, with `Exception` as a child. Three things inherit from `BaseException` but *not* from `Exception`: `KeyboardInterrupt`, `SystemExit`, and — the one that bit this code — `asyncio.CancelledError`.

Asyncio cancels tasks routinely. `WorkerPool.stop()` at `job_runner.py:279` calls `task.cancel()` on every worker. `JobExecutor.execute` wraps the handler in `asyncio.wait_for` with a timeout, and a timeout cancels the inner task. Every one of those raises `CancelledError`. With `except Exception`, `CancelledError` sailed straight past the handler: no `ROLLBACK` ran, the `with self._write_lock` block exited and released the Python lock, and the connection was left with `BEGIN IMMEDIATE` still open. The thread-local connection is reused, so from that moment on every write on that thread hit the `in_transaction` branch on line 172, joined a transaction that would never be committed, and appeared to succeed while writing nothing. The symptom was writes silently vanishing after a shutdown or a timeout, which is about as unpleasant a bug as this file could have. `BaseException` catches all of it.

### The `COMMIT` used to sit outside the `try`, and that was the same hole again

This is worth telling as a sequel, because it is the same lesson twice and it shows you went back and looked.

The version of this function that the `BaseException` change produced was:

```python
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
```

The `COMMIT` was the last statement of the function and it was **outside** the `try`. So the handler covered every way the *body* could fail and no way the *commit* could fail. A `COMMIT` can fail on its own: `SQLITE_FULL` when the disk fills, an I/O error on the WAL, a busy timeout that finally expires while the commit is waiting to take the lock. When that happened the `OperationalError` propagated to the caller with the transaction still open, the `with self._write_lock` block released the Python lock on the way out, and the thread-local connection was left in exactly the state the `BaseException` fix had been written to prevent. Every later write on that thread took the `in_transaction` branch on line 172, joined a transaction nobody would ever commit, and reported success while writing nothing.

Structurally identical to the earlier bug, reached by a different route, and the fix is one line of indentation: move the `COMMIT` inside the `try` so the same handler owns it.

The failure path is now `self._abandon(connection)` rather than a bare `ROLLBACK`, because after a failed `COMMIT` you cannot assume there is still a transaction to roll back. That is what the next function is for.

```python
    @staticmethod
    def _abandon(connection: sqlite3.Connection) -> None:
        """
        Return a failed transaction's connection to autocommit.

        Best effort by design: this runs while another error is on its way to
        the caller, and that error is the one worth seeing. SQLite closes the
        transaction itself for some failures, so there may be nothing to undo.
        """
        if not connection.in_transaction:
            return

        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            logger.exception("Rollback failed; this connection may be unusable")
```

`database.py:184-199`. Sixteen lines whose whole job is to leave the connection usable, and there are two decisions in it.

**The `in_transaction` guard on line 193.** SQLite ends the transaction itself for some errors — a failed `COMMIT` may have already rolled back internally, and `SQLITE_FULL` in particular can leave the connection in autocommit with nothing pending. Issuing `ROLLBACK` in that state raises "cannot rollback - no transaction is active", which would replace the real error with a meaningless one. Asking `in_transaction` first means the function does nothing when there is nothing to do. Note this is the same pysqlite attribute the nesting check on line 172 uses, so both places agree on what "in a transaction" means.

**The `except sqlite3.Error` on line 198.** If the `ROLLBACK` itself fails, that exception is swallowed and logged rather than raised. The reason is in the docstring: `_abandon` only ever runs while another exception is already travelling up to the caller. If `_abandon` raised, its exception would replace the original one, and the caller would be told "rollback failed" instead of "the disk is full" — the diagnosis would be about the cleanup rather than the fault. `logger.exception` records the full traceback so nothing is actually lost, and the warning in the message ("this connection may be unusable") is honest: if the rollback genuinely could not run, the connection is beyond saving and the next write on this thread will say so.

**What is guaranteed and what is not.** After `_abandon`, either the connection is in autocommit and usable, or the failure was logged and the connection is not. There is no state where the code silently believes it committed. That is the property `test_a_failed_commit_leaves_the_connection_usable` (`test_pipeline.py:604`) pins. The test wraps the real connection in `RefusesTheFirstCommit` (`test_pipeline.py:581`), a shim whose first `COMMIT` raises `sqlite3.OperationalError("disk I/O error")` the way a full disk does and which delegates everything else — including `in_transaction` — to the real connection, so the assertion is about what SQLite actually thinks rather than about the shim. It then asserts three things: the insert raises, `in_transaction` is `False` afterwards, and the *next* insert on the same connection really lands and is readable. That last assertion is the one that would have failed before the fix, and it is the one that describes the user-visible symptom.

```python
    @contextmanager
    def transaction(self):
        """Group several operations so they commit or roll back together."""
        with self._transaction():
            yield
```

`database.py:201-205`. The public wrapper. It yields nothing — callers get a scope, not a connection, so external code cannot execute arbitrary SQL on the connection. The only two callers are `flow/engine.py:118` and `flow/engine.py:207`. Both are read-modify-write cycles on the `node_states` JSON blob of a `flow_runs` row, and both need the read and the write inside the same lock or two concurrently finishing nodes each overwrite the other's completion.

---

## The generic table layer: lines 207 to 274

This is the Supabase-shaped API. When the store was Supabase, callers wrote `supabase.table("jobs").select("*").eq("status", "pending")`. Rather than rewrite every call site during the migration, these four methods accept the same PostgREST-style filter strings.

```python
    def select(
        self,
        table: str,
        filters: Filters = (),
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Read rows, translating PostgREST-style filters such as `("id", "eq.123")`."""
        where, params = self._where(filters)
        sql = f"SELECT * FROM {table}{where}"
```

`database.py:207-217`. Note that the SQL is always `SELECT *` regardless of what `columns` says. The `columns` argument is applied in Python at the end. That is a deliberate trade: interpolating a caller-supplied column list into SQL would be an injection surface, and projecting in Python cannot be. The cost is reading columns you throw away, which for a SQLite file on local disk is not a cost worth optimising.

```python
        if order:
            column, _, direction = order.partition(".")
            if column in self._columns(table):
                sql += f" ORDER BY {column} {'DESC' if direction == 'desc' else 'ASC'}"
```

`database.py:219-222`. `order` arrives as `"created_at.desc"`. `partition(".")` splits on the first dot into name, separator and direction.

The `if column in self._columns(table)` check is the guard. A column name cannot be a bound parameter in SQL — `ORDER BY ?` does not do what you want — so it has to be interpolated, and the only safe way to interpolate is to validate against the real column list first. `_columns` (line 457) reads `PRAGMA table_info`, so the allowed set comes from the database itself rather than a hand-maintained list that could drift.

The direction is a ternary that only recognises `desc`; anything else, including a garbage string, becomes `ASC`. There is nothing to inject.

**Worth knowing.** An unrecognised column is silently ignored — the `ORDER BY` is simply dropped and you get rows in whatever order SQLite returns them, with no error. A typo in a call site (`"updated.desc"` instead of `"updated_at.desc"`) would produce unordered results and no complaint.

```python
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
```

`database.py:223-224`. `int(limit)` is the guard here. A string that is not a number raises `ValueError` before it reaches SQL; a string that is a number becomes an integer. Nothing arbitrary can be interpolated.

```python
        rows = [self._decode(table, row) for row in self._connection.execute(sql, params)]
        if columns == "*":
            return rows

        wanted = [name.strip() for name in columns.split(",") if name.strip()]
        return [{name: row.get(name) for name in wanted} for row in rows]
```

`database.py:226-231`. Execute with the parameter list, decode each row's JSON columns, and project down to the requested columns in Python if a subset was asked for. `row.get(name)` rather than `row[name]` so an unknown column name yields `None` instead of raising.

Note that `select` uses `self._connection` directly and takes no lock. Reads do not need the write lock, and in WAL mode they do not block behind a writer either.

```python
    def insert(self, table: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Insert one row and return it as stored."""
        row = self._with_defaults(table, dict(data))
        encoded = self._encode(table, row)
        placeholders = ",".join("?" for _ in encoded)
```

`database.py:233-237`. `dict(data)` copies the caller's dictionary so `_with_defaults` mutating it does not surprise the caller. Then defaults are filled in, JSON columns encoded, and one `?` placeholder generated per column.

```python
        with self._transaction() as connection:
            connection.execute(
                f"INSERT INTO {table} ({','.join(encoded)}) VALUES ({placeholders})",
                list(encoded.values()),
            )
        return self.select(table, [("id", f"eq.{row['id']}")])
```

`database.py:239-244`. `','.join(encoded)` joins the dict's *keys* — iterating a dict yields keys. Column names are interpolated, values are bound. Dictionaries preserve insertion order in modern Python, which is why `encoded` (keys) and `encoded.values()` (values) line up.

The `select` on line 244 is outside the `with`, so in the non-nested case it reads after the commit. In the nested case nothing has been committed yet, but the read goes through the same thread-local connection and therefore sees the uncommitted row. Both paths return what was actually written, which is why the function can promise "as stored" rather than "as given".

Returning the stored row is what lets callers get the generated id: `api/routes/jobs.py:69` does `rows = database.insert("jobs", {...})` and then reads `rows[0]["id"]`.

```python
    def update(self, table: str, filters: Filters, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Patch matching rows and return them as stored."""
        filters = list(filters)
        payload = {key: value for key, value in data.items() if key in self._columns(table)}
```

`database.py:246-249`. `list(filters)` materialises the iterable because it is consumed twice — once by `_where` and once by the trailing `select`. A generator would be empty the second time.

The dict comprehension drops any key that is not a real column. That is both a safety measure (nothing arbitrary reaches the SQL) and a convenience (a caller can pass a whole model dump and have the extra fields ignored). It is also silent: a misspelled column is dropped without a word.

```python
        if table in {"projects", "flow_runs", "artifacts"}:
            payload["updated_at"] = _now()
        if not payload:
            return self.select(table, filters)
```

`database.py:250-253`. `updated_at` is maintained automatically for the three tables that have the column. `jobs` is absent from the set because the jobs table has no `updated_at` — its lifecycle is tracked by `started_at` and `completed_at`, which the queue methods set explicitly.

The empty-payload short-circuit avoids generating `UPDATE jobs SET  WHERE ...`, which is a syntax error. It returns the current rows unchanged, so the caller gets a sensible answer rather than an exception.

```python
        encoded = self._encode(table, payload)
        where, params = self._where(filters)
        assignments = ",".join(f"{key} = ?" for key in encoded)

        with self._transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments}{where}",
                list(encoded.values()) + params,
            )
        return self.select(table, filters)
```

`database.py:255-264`. Note the parameter ordering on line 262: the SET values come first, then the WHERE values, matching the order the `?` markers appear in the statement. Getting that backwards is a classic bug and it would fail loudly, but it is worth knowing why the concatenation is in that order.

```python
    def delete(self, table: str, filters: Filters) -> List[Dict[str, Any]]:
        """Delete matching rows and return what was removed."""
        filters = list(filters)
        removed = self.select(table, filters)
        where, params = self._where(filters)

        with self._transaction() as connection:
            connection.execute(f"DELETE FROM {table}{where}", params)
        return removed
```

`database.py:266-274`. The read on line 269 happens *before* the delete, for the obvious reason: afterwards there is nothing to read. That is why `delete` is the only one of the four that does its `select` first.

**Worth knowing.** The read on line 269 is outside the transaction, so strictly there is a window between reading and deleting. In practice deletes come from a single API request and the returned rows are only used to report what happened, so a stale read there is harmless — but it is a fair thing to be asked about.

---

## claim_job: lines 276 to 299

```python
    def claim_job(self, job_id: Optional[str] = None) -> Optional[JobModel]:
        """
        Move one pending job to `running` and return it.

        `BEGIN IMMEDIATE` takes the write lock before the read, so two workers
        racing on the same queue cannot both claim the same row.
        """
```

`database.py:276-282`. Step three of the job lifecycle. Optional `job_id` because there are two ways a job gets claimed: a worker draining the queue calls it with no argument (`job_runner.py:166`, `run_next`), and a worker handed a specific id by Redis calls it with that id (`job_runner.py:158`, `run_job`).

```python
        with self._transaction() as connection:
            query = (
                "SELECT id FROM jobs WHERE id = ? AND status = 'pending'"
                if job_id else
                "SELECT id FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
```

`database.py:283-288`. Both branches include `status = 'pending'` in the WHERE clause. That is not redundant even in the targeted case: it is what makes a duplicate dispatch harmless. Redis can deliver the same job id to two workers, or the drain task can re-dispatch a job that a worker has already picked up. The second caller's `SELECT` finds nothing, `claim_job` returns `None`, and `run_job` logs "was not claimable; another worker has it" and returns `False` without running anything.

The queue branch is FIFO — `ORDER BY created_at ASC LIMIT 1`. That is the ordering `idx_jobs_status(status, created_at)` was built for. There is no priority; oldest wins.

```python
            row = connection.execute(query, (str(job_id),) if job_id else ()).fetchone()
            if row is None:
                return None
```

`database.py:289-291`. `str(job_id)` because the caller may pass a `UUID` object and the column is TEXT — a `UUID` bound directly would not match the stored string. This coercion appears throughout the queue methods for the same reason.

Returning `None` from inside the `with` triggers the context manager's exit path, which reaches the `COMMIT` on line 179 and commits an empty transaction. Harmless.

```python
            connection.execute(
                "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
                (_now(), row["id"]),
            )
```

`database.py:293-296`. The claim itself, and three things happen in it.

`status='running'` is what makes the row invisible to every subsequent `claim_job`, since both queries filter on `status = 'pending'`.

`started_at=?` is **invariant four**. This is the timestamp the reaper keys off. If a worker is killed — SIGKILL, container eviction, laptop lid closed — the row stays `running` forever. `claim_job` will never return it again, because it is not `pending`. Nothing will ever fail it, because failure is recorded by the process that just died. From the user's point of view the flow node spins with no error and no result, permanently. `started_at` is the only evidence that a job has been in flight too long, and `reap_stale_jobs` on line 389 is what acts on it.

`attempts=attempts+1` increments **in SQL, not in Python**. That is worth pausing on. Reading the value, adding one in Python and writing it back would be a read-modify-write and would need the same protection as everything else here. Doing it as a single SQL expression makes the increment atomic within the statement. It happens to be inside `BEGIN IMMEDIATE` anyway, so it is already safe, but the expression form is the right habit and it is one fewer round trip.

Note again that attempts counts *claims*, not failures. A job claimed three times has `attempts = 3`. With `job_max_attempts` defaulting to 3 (`config.py:138`), a job gets three shots at the model in total.

```python
            claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()

        return self._to_job(self._decode("jobs", claimed))
```

`database.py:297-299`. Re-read the full row *inside* the transaction, so what comes back reflects the update. Then decode and convert outside — line 299 runs after the `with` has committed and released the lock, because JSON parsing and Pydantic validation are pure CPU work with no reason to hold the write lock.

---

## commit_bundle: lines 301 to 339

```python
    def commit_bundle(self, bundle: JobBundle) -> None:
        """Write a job's artifacts, edges and terminal status in one transaction."""
        timestamp = _now()
```

`database.py:301-303`. Step five of the lifecycle, and **invariant two**.

One timestamp is computed once and used for every row written below. That is not just tidiness: every artifact and edge produced by one job then carries the same `created_at`, so they sort together and you can tell at a glance which rows came from which commit.

The signature takes a `JobBundle` and returns nothing. This is the shape that makes step four of the lifecycle possible: `handler.run(job)` performs no database writes at all, it just builds this object (`models/graph.py:42`, with a docstring saying exactly that). A handler that fails halfway through leaves nothing behind because it never wrote anything. All the writing is here, in one place, in one transaction.

```python
        with self._transaction() as connection:
            job = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (str(bundle.job_id),)
            ).fetchone()
            if job is None:
                raise ValueError(f"Job not found: {bundle.job_id}")
            if job["status"] in TERMINAL_STATUSES:
                raise ValueError(f"Job {bundle.job_id} is already {job['status']}")
```

`database.py:305-312`. The terminal guard, **invariant three**, checked *inside* the transaction so the check and the writes that follow cannot be interleaved with another commit.

The scenario this defends against is concrete. Suppose the reaper decides a job has been running too long and puts it back to `pending`. Another worker claims it and runs it. Meanwhile the original worker was not dead, only slow, and it finishes and calls `commit_bundle`. Now two bundles want to commit against one job row. The first to reach line 311 finds a non-terminal status and proceeds. The second finds `completed` and raises.

Follow what happens to that `ValueError`. `JobExecutor.execute` (`job_runner.py:117`) catches it, calls `_record_failure`, which calls `fail_job`, which hits its own terminal guard on line 358 and returns the string `"completed"`. Back in `_record_failure` (`job_runner.py:194`), the outcome is not in `{"failed", "missing"}`, so the runner logs "already finished as completed; leaving that outcome alone" and — critically — does **not** publish `JOB_FAILED` and does **not** notify the flow engine of an error. The user sees one artifact and no failure. The two guards work as a pair; neither alone would be enough.

There is a test at `test_pipeline.py:430`, `test_a_committed_job_cannot_commit_twice`, asserting the `ValueError` with a message matching "already completed".

```python
            for artifact in bundle.artifacts:
                connection.execute(
                    "INSERT OR REPLACE INTO artifacts "
                    "(id, project_id, type, content, created_by_job_id, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (str(artifact.id), str(artifact.project_id), artifact.type,
                     json.dumps(artifact.content), str(bundle.job_id), timestamp),
                )
```

`database.py:314-321`. `INSERT OR REPLACE` rather than plain `INSERT`. The reason is the refine path: refining an artifact rebuilds it under the same id, so the row already exists and a plain insert would fail on the primary key. `OR REPLACE` deletes the conflicting row and inserts the new one.

Note that `json.dumps` is called directly here rather than going through `_encode`. That is because this method writes raw SQL rather than going through `insert`, which is itself deliberate — `commit_bundle` needs all of these statements on the same connection inside one `BEGIN IMMEDIATE`, and it needs `OR REPLACE` and `OR IGNORE` semantics that the generic layer does not expose.

`created_by_job_id` is set from the bundle's job id, which is how provenance gets recorded even for artifacts that have no parent edges.

**Worth knowing, two things.** First, `OR REPLACE` genuinely deletes and re-inserts, so a refined artifact's `created_at` becomes the time of the refine, not the original creation, and `updated_at` — which is not in the column list — is reset to NULL. Second, in general `OR REPLACE` fires `ON DELETE CASCADE` on anything referencing the replaced row. Here that is safe only because `artifact_edges` has no foreign key to `artifacts` (see line 72-73), so a replace does not silently sweep away the edges that put the artifact on the canvas. That is the one place where the loose schema earns its keep, and it is worth being able to say so rather than being caught out by it.

```python
            for edge in bundle.edges:
                connection.execute(
                    "INSERT OR IGNORE INTO artifact_edges "
                    "(id, project_id, parent_artifact_id, child_artifact_id, relationship_type, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (_new_id(), str(edge.project_id), str(edge.parent_artifact_id),
                     str(edge.child_artifact_id), edge.relationship_type, timestamp),
                )
```

`database.py:323-330`. `INSERT OR IGNORE` paired with the `UNIQUE (parent_artifact_id, child_artifact_id, relationship_type)` constraint from line 76. Together they make edge writing idempotent: if that derivation is already recorded, the insert is silently dropped rather than raising or duplicating.

A fresh `_new_id()` is generated for the edge's primary key, because the uniqueness that matters is the triple, not the id. The id is just a handle.

```python
            connection.execute(
                "UPDATE jobs SET status='completed', result=?, completed_at=?, error_message=NULL WHERE id=?",
                (json.dumps(bundle.result), timestamp, str(bundle.job_id)),
            )
```

`database.py:332-335`. The status flip, in the same transaction as the artifacts and edges above it.

`error_message=NULL` clears any message left by a previous failed attempt. Without it, a job that failed once with a rate-limit error, was requeued, and then succeeded would sit in the database as `completed` with a stale error message attached, and any UI showing the message would report a failure that did not happen.

This is the line to point at for invariant two. Consider what a partial write would look like to the user if these statements were four separate transactions instead of one:

- Artifacts committed, status not: the quiz row exists but the job still says `running`. The frontend polls and never sees completion. The flow engine is never notified, so the nodes downstream of this one never start. The reaper eventually requeues the job, a worker regenerates the same quiz, and you pay again — for work already sitting in the database.
- Status committed, artifacts not: the job says `completed` with a `result` containing an `artifact_id`, and the flow engine dutifully schedules the children. Each child handler tries to load its source artifact, does not find it, and fails. The canvas shows a completed node whose entire subtree failed with "source artifacts not found".
- Artifacts committed, edges not: the artifact exists and the job is complete, but the canvas has no link from the core to the quiz. The quiz floats unconnected and the provenance view is wrong.

One transaction means none of those states is reachable. Either every row is there or none of them is.

```python
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?",
                (timestamp, str(bundle.project_id)),
            )
```

`database.py:336-339`. Touch the project so it sorts to the top of the project list, which `api/routes/projects.py:35` orders by `updated_at.desc`. Also inside the transaction, so the list ordering can never reflect a commit that did not happen.

---

## fail_job: lines 341 to 372

```python
    def fail_job(self, job_id: Any, error: str, *, retryable: bool = False) -> str:
        """
        Record a failure, requeuing the job while it still has attempts left.

        Returns the outcome: `pending` when requeued, `failed` when recorded,
        `missing` when the row is gone, otherwise the terminal status the job
        already holds. A job reclaimed by the reaper can be running twice, and
        the loser's failure must not overwrite the winner's committed result.
        """
        max_attempts = get_settings().job_max_attempts
```

`database.py:341-350`. `retryable` is keyword-only (the `*` in the signature) because `fail_job(job_id, error, True)` at a call site would be unreadable — you would have to look up the signature to know what `True` meant.

The return type is a string with four possible meanings rather than a bool, and that richness is used. `job_runner.py:189-203` branches on it three ways: `"pending"` means log and stop; `"failed"` or `"missing"` means publish `JOB_FAILED` and tell the flow engine the node failed; anything else is a terminal status the job already held, which gets a warning and no further action.

`job_max_attempts` is read from settings on every call rather than cached, so a test can change the environment variable and clear the settings cache mid-run. `test_pipeline.py:393` does exactly that.

```python
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, attempts FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                return "missing"
            if row["status"] in TERMINAL_STATUSES:
                return row["status"]
```

`database.py:352-359`. **The terminal guard.** This is the second half of invariant three and it is the fix for a specific bug.

Before this guard existed, `fail_job` unconditionally set `status='failed'`. The failure mode: the reaper requeues a job whose worker looked dead, a second worker claims it and completes it, and then the first worker — which was alive all along, merely slow — finally gives up and calls `fail_job`. The row flips from `completed` to `failed`. The artifact is still sitting in the database, perfectly good. But `job_runner._record_failure` then notified the flow engine of an error, and `FlowEngine._skip_downstream` marked every node below that one as skipped. So a subtree of the flow that had actually succeeded was reported as failed and its children never ran, on the basis of a stale failure from a worker whose work had been superseded.

The guard returns the existing terminal status instead of writing, and the runner treats that as "leave it alone". Two tests cover it: `test_pipeline.py:471`, `test_a_late_failure_cannot_undo_a_committed_result`, asserts `fail_job` returns `"completed"` and the row stays `completed`; and `test_pipeline.py:481` does the same for a cancellation.

Also note that returning `"missing"` for a vanished row is not the same as failing. A row can disappear because its project was deleted mid-run and the `ON DELETE CASCADE` took the job with it. There is nothing to record.

```python
            if retryable and (row["attempts"] or 0) < max_attempts:
                connection.execute(
                    "UPDATE jobs SET status='pending', started_at=NULL, error_message=? WHERE id=?",
                    (error[:2000], str(job_id)),
                )
                return "pending"
```

`database.py:361-366`. The retry path, taken only when the caller judged the error transient *and* there are attempts left.

The transient judgement is made by `is_transient` in `job_runner.py:57` — network errors, timeouts, and messages containing "rate limit", "overloaded" and similar, plus labelled HTTP status codes. A malformed payload will fail identically on every retry while spending tokens, so it goes straight to `failed`.

`(row["attempts"] or 0)` handles a NULL, which the schema's `NOT NULL DEFAULT 0` should make impossible but the defensive read costs nothing.

`started_at=NULL` is **invariant four again**, in the other direction. Clearing it as the row goes back to `pending` means the reaper's query on line 402 — which requires `status='running' AND started_at IS NOT NULL` — cannot match it, and when a worker next claims it, `claim_job` writes a fresh `started_at` and the staleness clock restarts from that claim rather than from the first one. If `started_at` were left in place, a job that had been retried a few times would look stale the moment it was claimed and the reaper would rip it away mid-run, forever.

`error[:2000]` truncates. This exists because model provider errors and Python tracebacks can be enormous, and storing an unbounded string on every failure in an embedded database is how you end up with a hundred-megabyte file whose bulk is stack traces. Two thousand characters is enough to diagnose and bounded enough not to matter.

Note the error message is recorded even on the requeue. The row says `pending` but carries the reason for the last failure, which is useful when you are staring at a job that has been retried twice.

```python
            connection.execute(
                "UPDATE jobs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                (error[:2000], _now(), str(job_id)),
            )
            return "failed"
```

`database.py:368-372`. Terminal failure. `completed_at` is set even though the job did not complete successfully — the column means "reached a terminal state", not "succeeded". Same truncation.

---

## cancel_job: lines 374 to 387

```python
    def cancel_job(self, job_id: Any) -> bool:
        """Cancel a job that has not finished. Returns whether anything changed."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None or row["status"] in TERMINAL_STATUSES:
                return False
```

`database.py:374-381`. The same terminal guard again, this time collapsing "no such job" and "already finished" into one `False`, because from the API's point of view they are the same answer: nothing to cancel.

`api/routes/jobs.py:135-136` turns that `False` into a `409 Conflict` with the message "Job is already {status}", having already looked the job up separately and returned `404` if it did not exist. So the two cases are still distinguished for the user; they are just not distinguished here.

```python
            connection.execute(
                "UPDATE jobs SET status='cancelled', completed_at=?, error_message=? WHERE id=?",
                (_now(), "Cancelled by user", str(job_id)),
            )
            return True
```

`database.py:383-387`. `cancelled` is a member of `TERMINAL_STATUSES`, so once written, `claim_job` will not pick the row up and `fail_job` and `commit_bundle` will both refuse to touch it.

This is worth spelling out because it is what makes cancellation actually work with no ability to kill a running handler. Cancelling a `pending` job takes it off the queue outright — the row is no longer `pending`, so `claim_job` skips it. Cancelling a `running` job does not stop the worker; the handler keeps going, finishes, and calls `commit_bundle`, which finds the status terminal and raises. So the artifact is never written and the flow is never advanced. The work is wasted but the outcome is correct. `test_pipeline.py:439` covers the pending case, and `test_pipeline.py:481` covers a failure arriving after a cancellation.

---

## reap_stale_jobs: lines 389 to 421

```python
    def reap_stale_jobs(self, older_than_seconds: int) -> List[str]:
        """
        Requeue jobs left `running` by a worker that died.

        Without this the row is never claimable again and the node spins forever.
        """
```

`database.py:389-394`. **Invariant four.**

There are two callers. `backend/tasks.py:65` is a Celery beat task that runs on a schedule when Redis is present. `job_runner.py:304`, `WorkerPool._reaper`, is an asyncio task started alongside the in-process workers for the no-Redis deployment. Both pass `get_settings().stale_job_seconds`, which defaults to 1800.

That number is worth checking against `job_timeout_seconds`, which is 900 (`config.py:137`). The handler is wrapped in `asyncio.wait_for` with that 900-second timeout, so a live-but-slow job will time out and fail itself long before the reaper's 1800-second window opens. The reaper only ever sees rows whose worker is genuinely gone. The factor of two is the margin.

```python
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        max_attempts = get_settings().job_max_attempts
        reaped: List[str] = []
```

`database.py:395-397`. The cutoff is computed in Python as an ISO string in the same format `_now()` produces, so the SQL string comparison on line 402 is a real time comparison. This is the payoff for `_now()` always being UTC.

```python
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id, attempts FROM jobs "
                "WHERE status='running' AND started_at IS NOT NULL AND started_at < ?",
                (cutoff,),
            ).fetchall()
```

`database.py:399-404`. Three conditions. `status='running'` is the only state a stranded job can be in. `started_at IS NOT NULL` is a guard against a row that is somehow `running` without a claim timestamp — it would compare as NULL and never match `< cutoff` anyway, but stating it makes the intent explicit and lets the query planner use the index. `started_at < cutoff` is the staleness test.

`.fetchall()` rather than iterating the cursor, because the loop below writes to the same table the cursor is reading from. Modifying a table while a cursor is open on it is asking for trouble; materialising the result list first removes the question.

The whole read-and-requeue runs inside one `BEGIN IMMEDIATE`, so a worker cannot claim a row in between the reaper reading it and the reaper requeuing it.

```python
            for row in rows:
                if (row["attempts"] or 0) < max_attempts:
                    connection.execute(
                        "UPDATE jobs SET status='pending', started_at=NULL, "
                        "error_message='Requeued after worker timeout' WHERE id=?",
                        (row["id"],),
                    )
```

`database.py:406-412`. Same attempts check and the same `started_at=NULL` as the retry path in `fail_job`, for the same reason — the clock has to restart at the next claim or the job will be reaped again immediately.

The error message is a fixed string, which is honest: nobody recorded a reason, because the process that would have recorded one is gone. "Requeued after worker timeout" is all that can truthfully be said.

```python
                else:
                    connection.execute(
                        "UPDATE jobs SET status='failed', completed_at=?, "
                        "error_message='Timed out with no attempts left' WHERE id=?",
                        (_now(), row["id"]),
                    )
                reaped.append(row["id"])
```

`database.py:413-419`. The bound. A job whose worker keeps dying — because it triggers an out-of-memory kill on a huge PDF, say — would otherwise cycle forever between `running` and `pending`, each cycle costing another partial model call. After `job_max_attempts` claims it is failed for good, which at least produces an error the user can see.

`reaped.append` happens on both branches, so the returned list is "rows I touched", not "rows I requeued".

```python
        return reaped
```

`database.py:421`. The return value is used. `tasks.py:68` iterates it and calls `run_job.delay(job_id)` for each, so the requeued jobs are dispatched immediately rather than waiting for the next drain. `job_runner.py:310` only logs the count, because the in-process pool's workers are already polling and will pick them up on their own.

`test_pipeline.py:419`, `test_stale_running_jobs_return_to_the_queue`, calls this with `older_than_seconds=-1` — a negative window makes the cutoff a second in the *future*, so everything currently running is stale. Neat trick for testing a time-based mechanism without sleeping.

---

## Read helpers: lines 423 to 455

```python
    def pending_job_ids(self) -> List[str]:
        """Ids of every job still waiting to be claimed, oldest first."""
        rows = self._connection.execute(
            "SELECT id FROM jobs WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
        return [row["id"] for row in rows]
```

`database.py:423-428`. Used by the drain task at `tasks.py:55`, which re-dispatches everything pending. This is the recovery mechanism for step two of the lifecycle: a job row is committed before dispatch, so if the dispatch call failed — broker down, network blip — the row is still there and the next drain will dispatch it. Nothing is lost, only delayed.

No lock and no transaction, because it is a read.

```python
    def get_job(self, job_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("jobs", job_id)

    def get_project(self, project_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("projects", project_id)

    def get_artifact(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("artifacts", artifact_id)
```

`database.py:430-437`. Three one-line conveniences over `_first`. Named lookups read better at the call site than `select("jobs", [("id", "eq." + job_id)])[0]` and mean the "or None if missing" logic exists once.

```python
    def get_artifacts(self, artifact_ids: List[Any]) -> List[Dict[str, Any]]:
        """Fetch many artifacts in one query."""
        if not artifact_ids:
            return []
        joined = ",".join(str(value) for value in artifact_ids)
        return self.select("artifacts", [("id", f"in.({joined})")])
```

`database.py:439-444`. The batch fetch, used by the generate handler when a job has several source artifacts. One query instead of N, which for a mock exam built from four sources is the difference between one round trip and four.

The empty-list guard returns early. Without it the `in.()` string would be empty and `_where` would produce `1 = 0` (line 530), which is also correct — but returning early avoids the query entirely.

**Worth knowing.** The ids are joined into a comma-separated string here and split back apart by `_where` on line 528. That round trip through a string is fragile in principle: an id containing a comma would be split into two. In practice every id is a UUID, which never contains a comma, so it holds. It is a fair thing to be probed on and the honest answer is that the format was inherited from the PostgREST filter syntax the migration preserved.

```python
    def get_parent_edges(self, child_artifact_id: Any) -> List[Dict[str, Any]]:
        """Every edge pointing at this artifact. An artifact may have many parents."""
        return self.select("artifact_edges", [("child_artifact_id", f"eq.{child_artifact_id}")])

    def get_child_edges(self, parent_artifact_id: Any) -> List[Dict[str, Any]]:
        return self.select("artifact_edges", [("parent_artifact_id", f"eq.{parent_artifact_id}")])
```

`database.py:446-451`. Graph traversal in both directions. The docstring's point matters: this is a DAG, not a tree. A study guide can be derived from a knowledge core *and* a set of notes, so an artifact has a list of parents rather than one. `idx_edges_child` and `idx_edges_parent` (lines 105-106) make both directions indexed lookups.

```python
    def _first(self, table: str, row_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select(table, [("id", f"eq.{row_id}")])
        return rows[0] if rows else None
```

`database.py:453-455`. Look up by primary key, return the row or `None`.

---

## Encoding and decoding: lines 457 to 553

```python
    def _columns(self, table: str) -> set:
        return {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")}
```

`database.py:457-458`. Asks SQLite for the table's real column names. Used by `select` to validate an `ORDER BY` column and by `update` to filter the payload. Because the answer comes from the database rather than a constant, it cannot drift out of sync with the schema.

**Worth knowing.** This runs a `PRAGMA` on every `update` call. It is a metadata read against an already-open connection so the cost is negligible, but it is an uncached lookup on a hot path and an interviewer might ask why it is not memoised. The answer is that it never showed up as a problem, not that it could not be cached.

```python
    @staticmethod
    def _with_defaults(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = _now()
        row.setdefault("id", _new_id())
        row.setdefault("created_at", timestamp)
```

`database.py:460-464`. `setdefault` throughout, so an explicitly supplied value always wins. Every table gets an id and a `created_at`.

Generating the id in Python rather than letting SQLite assign one is what allows a caller to know the id before the write, and what allows a handler to build a graph of artifacts with ids already wired into edges before any of it is committed.

```python
        if table == "projects":
            row.setdefault("updated_at", timestamp)
            row.setdefault("canvas_state", {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []})
```

`database.py:466-468`. A new project gets an empty but *valid* canvas — a viewport at origin with zoom 1, no nodes, no edges. Not `{}`. That matters because the frontend reads `canvas_state.nodes` and `canvas_state.viewport.zoom` directly, and an empty object would produce undefined property access on the very first render of a new project.

```python
        elif table == "jobs":
            row.setdefault("status", "pending")
            row.setdefault("payload", {})
            row.setdefault("result", {})
        elif table == "flow_runs":
            row.setdefault("updated_at", timestamp)

        return row
```

`database.py:469-476`. `status` defaults to `pending`, which is step one of the lifecycle: a job row exists in the queue the moment it is written, before anything is dispatched.

These defaults duplicate the `DEFAULT` clauses in the schema, which is not pointless — the schema default only applies if the column is omitted from the INSERT, and `insert` builds its column list from whatever keys are present. Filling the values here means the returned row from `insert` has them, rather than the caller having to re-read to find out what the defaults were.

Note the function mutates and returns the same dict. `insert` passed it a copy on line 235, so the caller's dictionary is untouched.

```python
    @staticmethod
    def _encode(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        json_columns = JSON_COLUMNS.get(table, set())
        encoded: Dict[str, Any] = {}

        for key, value in row.items():
            if key in json_columns:
                encoded[key] = json.dumps(value if value is not None else {})
```

`database.py:478-485`. Python values to SQLite values.

A declared JSON column is always serialised, and a `None` becomes the string `"{}"` rather than SQL NULL. That is what upholds the `NOT NULL DEFAULT '{}'` on those columns and means `_decode` can always `json.loads` without a null check.

**Worth knowing.** If a caller passes a value that is *already* a JSON string for one of these columns, it gets encoded again and you end up with a quoted string inside the column. `_decode` would then return a string rather than a dict. Every current call site passes real Python objects, so it does not bite, but it is an asymmetry in the round trip.

```python
            elif isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value)
            elif isinstance(value, (uuid.UUID, datetime)):
                encoded[key] = str(value)
            else:
                encoded[key] = value

        return encoded
```

`database.py:486-493`. Three fallbacks. A dict or list on a non-JSON column is still serialised, because SQLite cannot bind those types at all and would raise `InterfaceError`. A `UUID` or `datetime` is stringified, because those cannot be bound either and because every id and timestamp column is TEXT — this is the coercion that lets callers pass a Pydantic model's `UUID` field straight through. Everything else passes untouched: strings, integers, floats, `None` and `bytes` are all types SQLite binds natively.

```python
    @staticmethod
    def _decode(table: str, row: sqlite3.Row) -> Dict[str, Any]:
        json_columns = JSON_COLUMNS.get(table, set())
        decoded: Dict[str, Any] = {}

        for key in row.keys():
            value = row[key]
            if key in json_columns and isinstance(value, str):
                try:
                    decoded[key] = json.loads(value)
                except json.JSONDecodeError:
                    decoded[key] = {}
            else:
                decoded[key] = value

        return decoded
```

`database.py:495-510`. The inverse. `row.keys()` is why `row_factory = sqlite3.Row` had to be set on line 146.

The `isinstance(value, str)` check skips a NULL, which would otherwise crash `json.loads`.

The `except json.JSONDecodeError` returning `{}` is a judgement call worth being able to defend. The argument for it: a single corrupt blob — truncated by a disk-full, or written by an older version with a different format — should not make an entire project unloadable. Returning an empty dict means the row still loads and the rest of the project still works. The argument against it: it hides corruption silently, with no log line, so a systematically broken write path would look like "the content is empty" rather than "the content failed to parse". Both readings are fair; the code chose availability over loudness.

```python
    @staticmethod
    def _where(filters: Filters) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        for column, expression in filters:
            if not isinstance(expression, str):
                clauses.append(f"{column} = ?")
                params.append(expression)
```

`database.py:512-520`. The filter translator, and the reason the migration off Supabase did not touch every call site.

The first branch handles a non-string value — a raw integer or `None` — as plain equality. It means `[("attempts", 3)]` works without having to write `"eq.3"`.

```python
            elif expression.startswith("eq."):
                clauses.append(f"{column} = ?")
                params.append(expression[3:])
            elif expression.startswith("neq."):
                clauses.append(f"{column} != ?")
                params.append(expression[4:])
```

`database.py:521-526`. The two comparison operators the codebase actually uses. `expression[3:]` and `expression[4:]` strip the prefix — three characters for `eq.`, four for `neq.`.

In every branch the column name is interpolated into the SQL and the value is bound as a parameter. Column names come from code, values come from users. That is the boundary that keeps this injection-safe, and it is worth being able to state in exactly those words.

```python
            elif expression.startswith("in.(") and expression.endswith(")"):
                values = [item.strip() for item in expression[4:-1].split(",") if item.strip()]
                if not values:
                    clauses.append("1 = 0")
                    continue
                clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
                params.extend(values)
```

`database.py:527-533`. The set membership operator. `expression[4:-1]` strips `in.(` from the front and `)` from the back, then splits on commas and drops empties.

The `1 = 0` on line 530 is the interesting line. SQLite rejects `IN ()` as a syntax error, so an empty set has to be handled. There were two wrong things to do here: raise, which would make an empty list a caller error rather than a legitimate query; or omit the clause entirely, which would turn "match none of these" into "no filter at all" and return the whole table. `1 = 0` is an always-false predicate that returns zero rows, which is the correct answer to "give me the rows whose id is in this empty set".

This matters at real call sites. `api/routes/jobs.py:99` lists a user's projects and then queries jobs with `("project_id", f"in.({ids})")`. If the user has no projects, an omitted clause would return *every job in the database*, belonging to everyone. That route happens to guard with an explicit `if not projects: return []` on line 100, but `1 = 0` is the reason it would still be correct without it.

`in.` also has a job-queue use worth mentioning, because it connects to a bug in the history. Duplicate job suppression lives in `api/routes/jobs.py:160`, `_find_in_flight_duplicate`, and its filter is:

```python
[("project_id", f"eq.{project_id}"), ("type", "eq.generate"),
 ("status", f"in.({','.join(IN_FLIGHT)})")]
```

with `IN_FLIGHT = ("pending", "running")` at `jobs.py:34`. That is the fix for the "regenerate does nothing" bug. The earlier version matched *any* prior job with the same target type and sources, including completed ones, so pressing Regenerate found the completed job from ten minutes ago, returned its id, and handed the user back the artifact they already had. The button looked broken. Restricting the lookup to `pending` and `running` means only genuinely in-flight work is deduplicated — a real double-click is collapsed, a deliberate regenerate is not. The function also returns `None` immediately if the request carries `instructions`, on the reasoning that a steered request is different work by definition.

To be precise: that logic is **not in this file**. `database.py` only provides the `in.` filter that makes the status set expressible. If asked where deduplication happens, point at `backend/api/routes/jobs.py:160`.

```python
            else:
                clauses.append(f"{column} = ?")
                params.append(expression)

        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params
```

`database.py:534-538`. The catch-all treats any unrecognised string as an equality value. The trailing return joins the clauses with `AND` and produces an empty string if there were no filters, so `f"SELECT * FROM {table}{where}"` on line 217 degrades to a full table read.

**Worth knowing.** The catch-all is silent. Writing `("attempts", "gt.2")` — a PostgREST operator this translator does not implement — does not raise; it compares the column to the literal string `"gt.2"` and matches nothing. Only `eq.`, `neq.` and `in.` are supported, and there is no way to find that out except by reading this function.

```python
    @staticmethod
    def _to_job(row: Dict[str, Any]) -> JobModel:
        return JobModel(
            id=row["id"],
            project_id=row["project_id"],
            type=row["type"],
            status=row["status"],
            payload=row.get("payload") or {},
            result=row.get("result") or {},
            error_message=row.get("error_message"),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
        )
```

`database.py:540-553`. The one place a raw row becomes a typed object. Only `claim_job` uses it, which is the boundary worth noticing: the API returns plain dicts, and the *worker* — the code that will act on this data — gets a validated `JobModel`.

Pydantic does real work in this constructor. `id` and `project_id` are strings in the row and are declared `UUID` on the model, so they are parsed and a malformed id raises here rather than three functions later. `type` is a `JobType` enum and `status` a `JobStatus` enum, so an unrecognised value raises immediately. The three timestamps are declared `datetime` and are parsed from their ISO strings, which is why `JobModel.started_at` is a real datetime for anything downstream that wants to do arithmetic on it.

`row["..."]` for required fields and `row.get(...)` for optional ones is a deliberate distinction: a missing required column should raise a `KeyError` loudly rather than being quietly passed as `None` and turning into a Pydantic error further along.

`or {}` on `payload` and `result` converts a NULL to an empty dict. `_decode` returns `None` for a NULL JSON column, and the model declares those fields as `Dict[str, Any]` with a default factory rather than `Optional`.

The model also carries two convenience properties defined in `models/jobs.py` — `flow_run_id` and `flow_node_id`, both reading out of `payload`. That is how `job_runner._notify_flow` knows whether a completed job belongs to a canvas run, which is step six of the lifecycle.

---

## The module singleton: lines 556 to 574

```python
_database: Optional[Database] = None
_lock = threading.Lock()
```

`database.py:556-557`. Module-level state. One `Database` instance per process, guarded by a plain `Lock` — plain, not re-entrant, because unlike `_write_lock` this is never acquired recursively.

```python
def get_database() -> Database:
    """The shared database handle, opened on first use."""
    global _database
    if _database is None:
        with _lock:
            if _database is None:
                _database = Database()
    return _database
```

`database.py:560-567`. Double-checked locking, and the double check is the point.

The outer check on line 563 is unsynchronised, so the common case — the instance already exists — never touches the lock at all. `get_database()` is called on essentially every request (`api/deps.py:33`), so making the hot path lock-free matters. The inner check on line 565 is inside the lock and handles the race where two threads both passed the outer check while the instance was still `None`: the first constructs it, the second re-checks, sees it is now set, and does not construct a second one.

Constructing a second one would not be catastrophic — SQLite would cope — but it would mean two thread-local pools and, more importantly, two `_write_lock` objects. Two write locks means two threads could be inside `BEGIN IMMEDIATE` in the same process at once, and the guarantee that invariant one rests on within a process would be gone. The second one would block on SQLite's own lock rather than deadlocking, so it would still be correct, but it would be correct by accident rather than by design.

Double-checked locking is famously broken in some languages because of instruction reordering. In CPython it is safe: name binding is a single bytecode operation and the GIL means another thread cannot observe a half-constructed object bound to `_database`.

Note `Database()` is called with no arguments, so it reads its path from settings. Configuration flows through settings, not through this function.

```python
def reset_database() -> None:
    """Discard the cached handle so the next call reopens it."""
    global _database
    with _lock:
        _database = None
```

`database.py:570-574`. The escape hatch, and its only caller is `tests/conftest.py:73`. Each test gets a fresh `tmp_path`, sets `BEE_DATA_DIR` to point at it, and calls this so the next `get_database()` opens a new file rather than reusing a handle to the previous test's database. Without it, the very first test's path would be cached for the whole session and every later test would share one database — the classic cached-singleton test-pollution problem, which the fixture's docstring names explicitly.

**Worth knowing.** This drops the reference without closing anything. The old `Database` object's thread-local connections stay open until Python garbage-collects them, which for a `threading.local` holding a reference on a still-live thread may be a while. In tests against temporary files that is harmless. In production this function is never called.

---

## The five things to be able to say without looking

If you only remember five sentences from this file:

1. `isolation_level=None` on `database.py:145` turns off pysqlite's automatic transaction handling, which is what lets `database.py:176` issue `BEGIN IMMEDIATE` instead of a deferred `BEGIN`, which is what makes `claim_job` atomic — the write lock is taken before the read, so two workers cannot both see the same pending row.
2. `_transaction` catches `BaseException` and not `Exception` because `asyncio.CancelledError` is not an `Exception`; when it was only `Exception`, a cancelled task left `BEGIN IMMEDIATE` open on a thread-local connection and every subsequent write on that thread silently joined a transaction that never committed. The `COMMIT` on `database.py:179` is inside that same `try` for the same reason — it used to sit outside it, so a commit that failed on a full disk or an I/O error stranded the connection in exactly the way the `BaseException` change had been written to prevent. `_abandon` (`database.py:184-199`) is the failure path: it returns the connection to autocommit, no-ops when SQLite already closed the transaction itself, and logs rather than raises a failing `ROLLBACK` so the cleanup cannot replace the error the caller needs to see.
3. `commit_bundle` writes artifacts, edges and the job's terminal status in one transaction, which is why a handler can return a `JobBundle` and do no database writes of its own, and why there is no observable state where the artifact exists but the job is still running.
4. `commit_bundle`, `fail_job` and `cancel_job` all check `TERMINAL_STATUSES` inside the transaction, so a slow duplicate worker cannot flip an already-completed job to failed — which used to happen after the reaper requeued a job whose worker was merely slow, and which caused the flow engine to skip a subtree that had actually succeeded.
5. `claim_job` stamps `started_at` and the requeue paths clear it, because that column is the only evidence that a job is in flight; a worker killed mid-job leaves its row `running` forever, `claim_job` skips it because it is not `pending`, and the node spins with no error until `reap_stale_jobs` finds it by that timestamp.

## Two things that are not in this file

Be ready to redirect, because both come up naturally when looking at this code and neither is here:

- **Ownership** is stored here (`user_id` on `database.py:39`, indexed on `:107`) but enforced at `backend/api/deps.py:48`, as a plain `!=` so that a NULL owner matches nobody and the read check agrees with what `list_projects` shows.
- **Duplicate job suppression** uses the `in.` filter this file provides, but the logic — restricted to `pending` and `running` so a completed job is never handed back as a "duplicate" — is at `backend/api/routes/jobs.py:160`.
