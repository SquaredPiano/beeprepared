"""SQLite persistence: projects, the job queue, and the artifact graph."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.core.config import get_settings
from backend.models.graph import JobBundle
from backend.models.jobs import TERMINAL_STATUSES, JobModel

logger = logging.getLogger(__name__)

Filters = Iterable[Tuple[str, Any]]

JSON_COLUMNS = {
    "projects": {"canvas_state"},
    "jobs": {"payload", "result"},
    "artifacts": {"content"},
    "flow_runs": {"plan", "node_states", "result"},
    "chat_messages": {"metadata"},
}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    user_id       TEXT,
    canvas_state  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS artifacts (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type              TEXT NOT NULL,
    content           TEXT NOT NULL DEFAULT '{}',
    created_by_job_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS artifact_edges (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_artifact_id TEXT NOT NULL,
    child_artifact_id  TEXT NOT NULL,
    relationship_type  TEXT NOT NULL DEFAULT 'derived_from',
    created_at         TEXT NOT NULL,
    UNIQUE (parent_artifact_id, child_artifact_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS flow_runs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'running',
    plan         TEXT NOT NULL DEFAULT '{}',
    node_states  TEXT NOT NULL DEFAULT '{}',
    result       TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project      ON jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type    ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_edges_parent      ON artifact_edges(parent_artifact_id);
CREATE INDEX IF NOT EXISTS idx_edges_child       ON artifact_edges(child_artifact_id);
CREATE INDEX IF NOT EXISTS idx_projects_user     ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_flow_runs_project ON flow_runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_project      ON chat_messages(project_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class Database:
    """
    Everything in the backend that touches storage comes through here.

    Each thread gets its own connection, because a SQLite connection isn't safe
    to share across threads. Writers queue up behind a single lock, and they ask
    SQLite for the write lock before they read anything. That second part is what
    makes `claim_job` safe when several workers are polling the same queue.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or get_settings().database_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()

        with self._write_lock:
            self._connection.executescript(SCHEMA)

        logger.info("Database ready at %s", self.path)

    @property
    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            self._local.connection = connection
        return connection

    @contextmanager
    def _transaction(self):
        """
        Run a group of writes as a single transaction.

        If this thread already has one open we join it rather than starting
        another, because SQLite refuses a nested `BEGIN`. That's what lets a
        caller wrap up several smaller writes that each open a transaction of
        their own.

        We roll back on `BaseException`, not `Exception`. The reason is
        `asyncio.CancelledError`, which is a `BaseException` and so slips
        straight through an `except Exception`. One of those escaping with a
        transaction still open used to leave the connection stuck mid-write, and
        then every later write on that thread failed too.

        The `COMMIT` sits inside the `try` for much the same reason. Committing
        can fail on its own account, on a full disk or an I/O error or a busy
        timeout running out. Outside the `try` we'd walk away from that with the
        transaction still open.
        """
        with self._write_lock:
            connection = self._connection
            if connection.in_transaction:
                yield connection
                return

            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                self._abandon(connection)
                raise

    @staticmethod
    def _abandon(connection: sqlite3.Connection) -> None:
        """
        Put a connection back into autocommit after a transaction has gone wrong.

        This is best effort on purpose. It runs while some other error is already
        on its way up to the caller, and that error is the one worth seeing, so a
        `ROLLBACK` that fails gets logged and nothing more. Sometimes there's
        nothing to undo at all, because SQLite closes the transaction itself on
        certain failures.
        """
        if not connection.in_transaction:
            return

        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            logger.exception("Rollback failed; this connection may be unusable")

    @contextmanager
    def transaction(self):
        """Let a caller group several writes so they all land or none of them do."""
        with self._transaction():
            yield

    def select(
        self,
        table: str,
        filters: Filters = (),
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Read rows. Filters come in PostgREST style, like `("id", "eq.123")`."""
        where, params = self._where(filters)
        sql = f"SELECT * FROM {table}{where}"

        if order:
            column, _, direction = order.partition(".")
            if column in self._columns(table):
                sql += f" ORDER BY {column} {'DESC' if direction == 'desc' else 'ASC'}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        rows = [self._decode(table, row) for row in self._connection.execute(sql, params)]
        if columns == "*":
            return rows

        wanted = [name.strip() for name in columns.split(",") if name.strip()]
        return [{name: row.get(name) for name in wanted} for row in rows]

    def insert(self, table: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Insert one row, then read it back and return it as it was stored."""
        row = self._with_defaults(table, dict(data))
        encoded = self._encode(table, row)
        placeholders = ",".join("?" for _ in encoded)

        with self._transaction() as connection:
            connection.execute(
                f"INSERT INTO {table} ({','.join(encoded)}) VALUES ({placeholders})",
                list(encoded.values()),
            )
        return self.select(table, [("id", f"eq.{row['id']}")])

    def update(self, table: str, filters: Filters, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Patch every matching row, then hand them back as they now stand."""
        filters = list(filters)
        payload = {key: value for key, value in data.items() if key in self._columns(table)}
        if table in {"projects", "flow_runs", "artifacts"}:
            payload["updated_at"] = _now()
        if not payload:
            return self.select(table, filters)

        encoded = self._encode(table, payload)
        where, params = self._where(filters)
        assignments = ",".join(f"{key} = ?" for key in encoded)

        with self._transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments}{where}",
                list(encoded.values()) + params,
            )
        return self.select(table, filters)

    def delete(self, table: str, filters: Filters) -> List[Dict[str, Any]]:
        """Delete matching rows. Returns what was there, read just before the delete."""
        filters = list(filters)
        removed = self.select(table, filters)
        where, params = self._where(filters)

        with self._transaction() as connection:
            connection.execute(f"DELETE FROM {table}{where}", params)
        return removed

    def claim_job(self, job_id: Optional[str] = None) -> Optional[JobModel]:
        """
        Take the next pending job off the queue and mark it running.

        Pass a `job_id` to claim that one row, or nothing to take the oldest job
        waiting.

        We ask SQLite for the write lock up front with `BEGIN IMMEDIATE`. Without
        it, two workers can both read the same pending row and both decide it's
        theirs, and then we pay for the same model call twice.
        """
        with self._transaction() as connection:
            query = (
                "SELECT id FROM jobs WHERE id = ? AND status = 'pending'"
                if job_id else
                "SELECT id FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
            row = connection.execute(query, (str(job_id),) if job_id else ()).fetchone()
            if row is None:
                return None

            connection.execute(
                "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
                (_now(), row["id"]),
            )
            claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()

        return self._to_job(self._decode("jobs", claimed))

    def commit_bundle(self, bundle: JobBundle) -> None:
        """
        Write a job's artifacts, its edges and its finished status all at once.

        It's one transaction, so either the whole bundle lands or none of it does
        and nothing partial is left behind. If the row has already reached a
        terminal status we raise instead of writing anything, because that means
        another worker finished this job first and its result is the one that
        counts.
        """
        timestamp = _now()

        with self._transaction() as connection:
            job = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (str(bundle.job_id),)
            ).fetchone()
            if job is None:
                raise ValueError(f"Job not found: {bundle.job_id}")
            if job["status"] in TERMINAL_STATUSES:
                raise ValueError(f"Job {bundle.job_id} is already {job['status']}")

            for artifact in bundle.artifacts:
                connection.execute(
                    "INSERT OR REPLACE INTO artifacts "
                    "(id, project_id, type, content, created_by_job_id, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (str(artifact.id), str(artifact.project_id), artifact.type,
                     json.dumps(artifact.content), str(bundle.job_id), timestamp),
                )

            for edge in bundle.edges:
                connection.execute(
                    "INSERT OR IGNORE INTO artifact_edges "
                    "(id, project_id, parent_artifact_id, child_artifact_id, relationship_type, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (_new_id(), str(edge.project_id), str(edge.parent_artifact_id),
                     str(edge.child_artifact_id), edge.relationship_type, timestamp),
                )

            connection.execute(
                "UPDATE jobs SET status='completed', result=?, completed_at=?, error_message=NULL WHERE id=?",
                (json.dumps(bundle.result), timestamp, str(bundle.job_id)),
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE id=?",
                (timestamp, str(bundle.project_id)),
            )

    def fail_job(self, job_id: Any, error: str, *, retryable: bool = False) -> str:
        """
        Record that a job failed, and requeue it if it still has attempts left.

        The return value says what we did: `pending` if we put it back on the
        queue, `failed` if we wrote the failure down for good, `missing` if the
        row has gone, and otherwise the terminal status the job was already
        sitting in.

        That last case is the one to know about. The reaper can hand a job back to
        the queue while the original worker is still grinding away on it, so two
        workers really can be running the same job. If the slow one then fails, we
        won't let it stamp `failed` over the result the other one has already
        committed.
        """
        max_attempts = get_settings().job_max_attempts

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, attempts FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                return "missing"
            if row["status"] in TERMINAL_STATUSES:
                return row["status"]

            if retryable and (row["attempts"] or 0) < max_attempts:
                connection.execute(
                    "UPDATE jobs SET status='pending', started_at=NULL, error_message=? WHERE id=?",
                    (error[:2000], str(job_id)),
                )
                return "pending"

            connection.execute(
                "UPDATE jobs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                (error[:2000], _now(), str(job_id)),
            )
            return "failed"

    def cancel_job(self, job_id: Any) -> bool:
        """Cancel a job that hasn't finished yet. Tells you if it changed anything."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None or row["status"] in TERMINAL_STATUSES:
                return False

            connection.execute(
                "UPDATE jobs SET status='cancelled', completed_at=?, error_message=? WHERE id=?",
                (_now(), "Cancelled by user", str(job_id)),
            )
            return True

    def reap_stale_jobs(self, older_than_seconds: int) -> List[str]:
        """
        Pick up jobs that a dead worker left sitting in `running`.

        Nothing else will ever touch those rows, since `claim_job` only looks at
        pending ones. So without the reaper the job is simply stuck, and the node
        on the canvas spins forever with no error to show the user. Jobs that have
        run out of attempts get marked failed here instead of requeued.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        max_attempts = get_settings().job_max_attempts
        reaped: List[str] = []

        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id, attempts FROM jobs "
                "WHERE status='running' AND started_at IS NOT NULL AND started_at < ?",
                (cutoff,),
            ).fetchall()

            for row in rows:
                if (row["attempts"] or 0) < max_attempts:
                    connection.execute(
                        "UPDATE jobs SET status='pending', started_at=NULL, "
                        "error_message='Requeued after worker timeout' WHERE id=?",
                        (row["id"],),
                    )
                else:
                    connection.execute(
                        "UPDATE jobs SET status='failed', completed_at=?, "
                        "error_message='Timed out with no attempts left' WHERE id=?",
                        (_now(), row["id"]),
                    )
                reaped.append(row["id"])

        return reaped

    def pending_job_ids(self) -> List[str]:
        """Ids of every job still waiting to be claimed, oldest first."""
        rows = self._connection.execute(
            "SELECT id FROM jobs WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
        return [row["id"] for row in rows]

    def get_job(self, job_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("jobs", job_id)

    def get_project(self, project_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("projects", project_id)

    def get_artifact(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        return self._first("artifacts", artifact_id)

    def get_artifacts(self, artifact_ids: List[Any]) -> List[Dict[str, Any]]:
        """Fetch a whole batch of artifacts in a single query."""
        if not artifact_ids:
            return []
        joined = ",".join(str(value) for value in artifact_ids)
        return self.select("artifacts", [("id", f"in.({joined})")])

    def get_parent_edges(self, child_artifact_id: Any) -> List[Dict[str, Any]]:
        """Every edge pointing at this artifact. One artifact can have several parents."""
        return self.select("artifact_edges", [("child_artifact_id", f"eq.{child_artifact_id}")])

    def get_child_edges(self, parent_artifact_id: Any) -> List[Dict[str, Any]]:
        return self.select("artifact_edges", [("parent_artifact_id", f"eq.{parent_artifact_id}")])

    def _first(self, table: str, row_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select(table, [("id", f"eq.{row_id}")])
        return rows[0] if rows else None

    def _columns(self, table: str) -> set:
        return {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _with_defaults(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = _now()
        row.setdefault("id", _new_id())
        row.setdefault("created_at", timestamp)

        if table == "projects":
            row.setdefault("updated_at", timestamp)
            row.setdefault("canvas_state", {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []})
        elif table == "jobs":
            row.setdefault("status", "pending")
            row.setdefault("payload", {})
            row.setdefault("result", {})
        elif table == "flow_runs":
            row.setdefault("updated_at", timestamp)

        return row

    @staticmethod
    def _encode(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        json_columns = JSON_COLUMNS.get(table, set())
        encoded: Dict[str, Any] = {}

        for key, value in row.items():
            if key in json_columns:
                encoded[key] = json.dumps(value if value is not None else {})
            elif isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value)
            elif isinstance(value, (uuid.UUID, datetime)):
                encoded[key] = str(value)
            else:
                encoded[key] = value

        return encoded

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

    @staticmethod
    def _where(filters: Filters) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        for column, expression in filters:
            if not isinstance(expression, str):
                clauses.append(f"{column} = ?")
                params.append(expression)
            elif expression.startswith("eq."):
                clauses.append(f"{column} = ?")
                params.append(expression[3:])
            elif expression.startswith("neq."):
                clauses.append(f"{column} != ?")
                params.append(expression[4:])
            elif expression.startswith("in.(") and expression.endswith(")"):
                values = [item.strip() for item in expression[4:-1].split(",") if item.strip()]
                if not values:
                    clauses.append("1 = 0")
                    continue
                clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
                params.extend(values)
            else:
                clauses.append(f"{column} = ?")
                params.append(expression)

        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params

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


_database: Optional[Database] = None
_lock = threading.Lock()


def get_database() -> Database:
    """The shared database handle, opened on first use."""
    global _database
    if _database is None:
        with _lock:
            if _database is None:
                _database = Database()
    return _database


def reset_database() -> None:
    """Discard the cached handle so the next call reopens it."""
    global _database
    with _lock:
        _database = None
