"""
Embedded SQLite store: the zero-infrastructure implementation of the data layer.

Why this exists
---------------
The original backend could only talk to Supabase. That is a hard dependency on
a hosted service for what is, at its core, five tables and two transactions -
so a lapsed API key or an offline laptop took the whole product down, and the
stop-gap in-memory store lost every project on restart.

This module implements the same contract against a local SQLite file. It is
durable, transactional, needs no daemon, and gives us the two things the job
system actually requires from a database:

1. ``claim_job``     - atomically move exactly one pending job to running,
                       even with several workers racing (BEGIN IMMEDIATE).
2. ``commit_bundle`` - write artifacts, edges, renderings and the job's
                       terminal state in a single transaction, or none of it.

Supabase remains supported; ``DBInterface`` picks whichever is configured.
"""

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

from backend.core.config import BACKEND_DIR, get_settings
from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle

logger = logging.getLogger(__name__)

# Columns that hold JSON documents. Serialised on write, parsed on read, so
# callers always deal in plain Python dicts regardless of the backend.
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
    flow_run_id    TEXT,
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

CREATE TABLE IF NOT EXISTS renderings (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL,
    format      TEXT NOT NULL,
    r2_path     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (artifact_id, format)
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
CREATE INDEX IF NOT EXISTS idx_jobs_flow         ON jobs(flow_run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type    ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_edges_parent      ON artifact_edges(parent_artifact_id);
CREATE INDEX IF NOT EXISTS idx_edges_child       ON artifact_edges(child_artifact_id);
CREATE INDEX IF NOT EXISTS idx_projects_user     ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_project      ON chat_messages(project_id, created_at);
"""

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class LocalDatabase:
    """SQLite-backed implementation of the BeePrepared data layer."""

    def __init__(self, path: Optional[Path] = None):
        settings = get_settings()
        self.path = Path(path or settings.storage_dir / "beeprepared.db").expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread: SQLite connections are not thread-safe, but
        # the file is, and WAL lets readers run while a writer holds the lock.
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._bootstrap()
        logger.info("Local database ready at %s", self.path)

    # -- connection handling -------------------------------------------------

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        with self._write_lock:
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Additive migrations for databases created by an earlier version."""
        for table, column, ddl in (
            ("jobs", "attempts", "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"),
            ("jobs", "flow_run_id", "ALTER TABLE jobs ADD COLUMN flow_run_id TEXT"),
            ("artifacts", "updated_at", "ALTER TABLE artifacts ADD COLUMN updated_at TEXT"),
        ):
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._conn.execute(ddl)

    @contextmanager
    def _transaction(self):
        """Serialise writers and give them an immediate write lock."""
        with self._write_lock:
            conn = self._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    # -- row (de)serialisation ----------------------------------------------

    @staticmethod
    def _encode(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        json_cols = JSON_COLUMNS.get(table, set())
        encoded: Dict[str, Any] = {}
        for key, value in data.items():
            if key in json_cols:
                encoded[key] = json.dumps(value if value is not None else {})
            elif isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value)
            elif isinstance(value, uuid.UUID):
                encoded[key] = str(value)
            elif isinstance(value, datetime):
                encoded[key] = value.isoformat()
            else:
                encoded[key] = value
        return encoded

    @staticmethod
    def _decode(table: str, row: sqlite3.Row) -> Dict[str, Any]:
        json_cols = JSON_COLUMNS.get(table, set())
        out: Dict[str, Any] = {}
        for key in row.keys():
            value = row[key]
            if key in json_cols and isinstance(value, str):
                try:
                    out[key] = json.loads(value)
                except json.JSONDecodeError:
                    out[key] = {}
            else:
                out[key] = value
        return out

    def _columns(self, table: str) -> set:
        return {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}

    # -- PostgREST-style filter translation ---------------------------------

    @staticmethod
    def _build_where(filters: Iterable[Tuple[str, str]]) -> Tuple[str, List[Any]]:
        """Translate the ``(column, "eq.value")`` filter form into SQL."""
        clauses: List[str] = []
        params: List[Any] = []
        for column, expression in filters:
            if not isinstance(expression, str):
                clauses.append(f"{column} = ?")
                params.append(expression)
                continue
            if expression.startswith("eq."):
                clauses.append(f"{column} = ?")
                params.append(expression[3:])
            elif expression.startswith("neq."):
                clauses.append(f"{column} != ?")
                params.append(expression[4:])
            elif expression.startswith("in.(") and expression.endswith(")"):
                values = [v.strip() for v in expression[4:-1].split(",") if v.strip()]
                if not values:
                    clauses.append("1 = 0")
                    continue
                placeholders = ",".join("?" for _ in values)
                clauses.append(f"{column} IN ({placeholders})")
                params.extend(values)
            elif expression.startswith("is."):
                target = expression[3:]
                clauses.append(f"{column} IS {'NULL' if target == 'null' else 'NOT NULL'}")
            else:
                clauses.append(f"{column} = ?")
                params.append(expression)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    # -- generic table operations -------------------------------------------

    def select(
        self,
        table_name: str,
        filters: Iterable[Tuple[str, str]] = (),
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        where, params = self._build_where(filters)
        sql = f"SELECT * FROM {table_name}{where}"

        if order:
            column, _, direction = order.partition(".")
            if column in self._columns(table_name):
                sql += f" ORDER BY {column} {'DESC' if direction == 'desc' else 'ASC'}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        rows = [self._decode(table_name, row) for row in self._conn.execute(sql, params)]
        if columns and columns != "*":
            requested = [c.strip() for c in columns.split(",") if c.strip()]
            rows = [{c: row.get(c) for c in requested} for row in rows]
        return rows

    def insert(self, table_name: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        row = dict(data)
        row.setdefault("id", _new_id())
        timestamp = _now()
        row.setdefault("created_at", timestamp)

        if table_name == "projects":
            row.setdefault("updated_at", timestamp)
            row.setdefault("canvas_state", {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []})
        elif table_name == "jobs":
            row.setdefault("status", "pending")
            row.setdefault("payload", {})
            row.setdefault("result", {})
        elif table_name == "flow_runs":
            row.setdefault("updated_at", timestamp)

        allowed = self._columns(table_name)
        row = {k: v for k, v in row.items() if k in allowed}
        encoded = self._encode(table_name, row)

        placeholders = ",".join("?" for _ in encoded)
        sql = (
            f"INSERT INTO {table_name} ({','.join(encoded)}) VALUES ({placeholders})"
        )
        with self._transaction() as conn:
            conn.execute(sql, list(encoded.values()))
        return self.select(table_name, [("id", f"eq.{row['id']}")])

    def update(
        self,
        table_name: str,
        filters: Iterable[Tuple[str, str]],
        data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        filters = list(filters)
        payload = dict(data)
        if table_name in {"projects", "flow_runs"}:
            payload["updated_at"] = _now()
        elif table_name == "artifacts":
            payload["updated_at"] = _now()

        allowed = self._columns(table_name)
        payload = {k: v for k, v in payload.items() if k in allowed}
        if not payload:
            return self.select(table_name, filters)

        encoded = self._encode(table_name, payload)
        where, params = self._build_where(filters)
        assignments = ",".join(f"{k} = ?" for k in encoded)
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE {table_name} SET {assignments}{where}",
                list(encoded.values()) + params,
            )
        return self.select(table_name, filters)

    def delete(self, table_name: str, filters: Iterable[Tuple[str, str]]) -> List[Dict[str, Any]]:
        filters = list(filters)
        doomed = self.select(table_name, filters)
        where, params = self._build_where(filters)
        with self._transaction() as conn:
            conn.execute(f"DELETE FROM {table_name}{where}", params)
        return doomed

    # -- job queue ----------------------------------------------------------

    def claim_job(self, job_id: Optional[str] = None) -> Optional[JobModel]:
        """
        Atomically move one pending job to ``running``.

        ``BEGIN IMMEDIATE`` takes the write lock before the SELECT, so two
        workers racing on the same queue cannot both observe the same pending
        row. This is the SQLite equivalent of ``FOR UPDATE SKIP LOCKED``.
        """
        with self._transaction() as conn:
            if job_id:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE id = ? AND status = 'pending'", (str(job_id),)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
                ).fetchone()

            if row is None:
                return None

            conn.execute(
                "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
                (_now(), row["id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()

        return self._to_job_model(self._decode("jobs", claimed))

    def commit_bundle(self, bundle: JobBundle) -> None:
        """Write every artifact, edge and rendering and finish the job atomically."""
        timestamp = _now()
        with self._transaction() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id = ?", (str(bundle.job_id),)).fetchone()
            if job is None:
                raise ValueError(f"Job not found: {bundle.job_id}")
            if job["status"] in TERMINAL_STATUSES:
                raise ValueError(f"Job {bundle.job_id} is already {job['status']}; refusing to rewrite history")

            for artifact in bundle.artifacts:
                conn.execute(
                    "INSERT OR REPLACE INTO artifacts "
                    "(id, project_id, type, content, created_by_job_id, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        str(artifact.id),
                        str(artifact.project_id),
                        artifact.type,
                        json.dumps(artifact.content),
                        str(bundle.job_id),
                        timestamp,
                    ),
                )

            for edge in bundle.edges:
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_edges "
                    "(id, project_id, parent_artifact_id, child_artifact_id, relationship_type, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        _new_id(),
                        str(edge.project_id),
                        str(edge.parent_artifact_id),
                        str(edge.child_artifact_id),
                        edge.relationship_type,
                        timestamp,
                    ),
                )

            for rendering in bundle.renderings:
                conn.execute(
                    "INSERT OR REPLACE INTO renderings "
                    "(id, project_id, artifact_id, format, r2_path, created_at) VALUES (?,?,?,?,?,?)",
                    (
                        str(rendering.id or uuid.uuid4()),
                        str(rendering.project_id),
                        str(rendering.artifact_id),
                        rendering.format,
                        rendering.r2_path,
                        timestamp,
                    ),
                )

            conn.execute(
                "UPDATE jobs SET status='completed', result=?, completed_at=?, error_message=NULL WHERE id=?",
                (json.dumps(bundle.result), timestamp, str(bundle.job_id)),
            )
            conn.execute(
                "UPDATE projects SET updated_at=? WHERE id=?",
                (timestamp, str(bundle.project_id)),
            )

    def fail_job(self, job_id: Any, error_message: str, *, retryable: bool = False) -> str:
        """
        Mark a job failed, or return it to the queue when it still has attempts
        left. Returns the status the job ended up in.
        """
        settings = get_settings()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
            if row is None:
                return "missing"

            attempts = row["attempts"] or 0
            if retryable and attempts < settings.job_max_attempts:
                conn.execute(
                    "UPDATE jobs SET status='pending', started_at=NULL, error_message=? WHERE id=?",
                    (error_message[:2000], str(job_id)),
                )
                return "pending"

            conn.execute(
                "UPDATE jobs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                (error_message[:2000], _now(), str(job_id)),
            )
            return "failed"

    def cancel_job(self, job_id: Any) -> bool:
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
            if row is None or row["status"] in TERMINAL_STATUSES:
                return False
            conn.execute(
                "UPDATE jobs SET status='cancelled', completed_at=?, error_message=? WHERE id=?",
                (_now(), "Cancelled by user", str(job_id)),
            )
            return True

    def reap_stale_jobs(self, older_than_seconds: int) -> List[str]:
        """
        Return jobs that have been ``running`` past the timeout to the queue.

        Without this a worker crash strands the job forever: the row stays
        ``running`` so ``claim_job`` skips it and the user's node spins for good.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        settings = get_settings()
        requeued: List[str] = []
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT id, attempts FROM jobs WHERE status='running' AND started_at IS NOT NULL AND started_at < ?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                if (row["attempts"] or 0) < settings.job_max_attempts:
                    conn.execute(
                        "UPDATE jobs SET status='pending', started_at=NULL, "
                        "error_message='Requeued after worker timeout' WHERE id=?",
                        (row["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status='failed', completed_at=?, "
                        "error_message='Timed out; no attempts left' WHERE id=?",
                        (_now(), row["id"]),
                    )
                requeued.append(row["id"])
        return requeued

    def pending_job_ids(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT id FROM jobs WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
        return [row["id"] for row in rows]

    @staticmethod
    def _to_job_model(row: Dict[str, Any]) -> JobModel:
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

    def get_job(self, job_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select("jobs", [("id", f"eq.{job_id}")])
        return rows[0] if rows else None

    # -- graph lookups ------------------------------------------------------

    def get_artifact(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select("artifacts", [("id", f"eq.{artifact_id}")])
        return rows[0] if rows else None

    def get_artifacts(self, artifact_ids: List[Any]) -> List[Dict[str, Any]]:
        if not artifact_ids:
            return []
        joined = ",".join(str(a) for a in artifact_ids)
        return self.select("artifacts", [("id", f"in.({joined})")])

    def get_parent_edge(self, child_artifact_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.get_all_parent_edges(child_artifact_id)
        return rows[0] if rows else None

    def get_all_parent_edges(self, child_artifact_id: Any) -> List[Dict[str, Any]]:
        return self.select("artifact_edges", [("child_artifact_id", f"eq.{child_artifact_id}")])

    def project_of_job(self, job_id: Any) -> Optional[str]:
        row = self._conn.execute("SELECT project_id FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
        return row["project_id"] if row else None


_DB: Optional[LocalDatabase] = None
_DB_LOCK = threading.Lock()


def get_local_db() -> LocalDatabase:
    """Process-wide SQLite database singleton."""
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = LocalDatabase()
    return _DB


def reset_local_db() -> None:
    """Drop the cached handle. Used by tests."""
    global _DB
    with _DB_LOCK:
        _DB = None
