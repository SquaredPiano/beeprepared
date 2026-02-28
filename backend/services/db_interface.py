"""
Data access layer.

``DBInterface`` is the single seam between the pipeline and whatever is storing
its data. Two backends implement it:

- ``local``    - embedded SQLite (default; see ``services/local_db.py``)
- ``supabase`` - PostgREST + the ``claim_next_job`` / ``commit_job_bundle`` RPCs

Handlers, the job runner and the flow engine only ever see this class, so the
storage decision is made once, at construction, instead of being re-litigated
at every call site.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import httpx

from backend.core.config import get_settings
from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle
from backend.services.local_db import get_local_db

logger = logging.getLogger(__name__)

_BACKEND_LOCK = threading.Lock()
_BACKEND: Optional[str] = None
_BACKEND_REASON: str = ""


def _probe_supabase() -> Tuple[bool, str]:
    """Is Supabase configured and answering? Decided once per process."""
    settings = get_settings()
    if not settings.has_supabase:
        return False, "SUPABASE_URL/SUPABASE_KEY not configured"
    try:
        response = httpx.get(
            f"{settings.supabase_url}/rest/v1/",
            headers={"apikey": settings.supabase_key},
            timeout=5.0,
        )
        if response.status_code >= 500:
            return False, f"Supabase returned {response.status_code}"
        return True, "supabase reachable"
    except Exception as exc:
        return False, f"Supabase unreachable: {exc}"


def active_backend() -> str:
    """``"supabase"`` or ``"local"``. Cached after the first call."""
    global _BACKEND, _BACKEND_REASON
    if _BACKEND is None:
        with _BACKEND_LOCK:
            if _BACKEND is None:
                forced = get_settings().database_backend
                if forced == "supabase":
                    _BACKEND, _BACKEND_REASON = "supabase", "forced by DATABASE_BACKEND"
                elif forced == "local":
                    _BACKEND, _BACKEND_REASON = "local", "forced by DATABASE_BACKEND"
                else:
                    ok, reason = _probe_supabase()
                    _BACKEND = "supabase" if ok else "local"
                    _BACKEND_REASON = reason
                logger.info("Database backend: %s (%s)", _BACKEND, _BACKEND_REASON)
    return _BACKEND


def backend_reason() -> str:
    active_backend()
    return _BACKEND_REASON


def reset_backend() -> None:
    """Forget the cached backend decision. Used by tests."""
    global _BACKEND, _BACKEND_REASON
    with _BACKEND_LOCK:
        _BACKEND, _BACKEND_REASON = None, ""


class DBInterface:
    """Storage-agnostic access to projects, jobs, artifacts and the graph."""

    def __init__(self) -> None:
        self.backend = active_backend()
        self.local = self.backend == "local"
        self.store = get_local_db() if self.local else None

        if not self.local:
            settings = get_settings()
            self.url = settings.supabase_url
            self.key = settings.supabase_key
            self.rest_url = f"{self.url}/rest/v1"
            self.headers = {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            self._client = httpx.Client(timeout=30.0)

    # -- Supabase plumbing --------------------------------------------------

    def _rpc(self, function_name: str, params: Dict[str, Any]) -> Any:
        response = self._client.post(
            f"{self.rest_url}/rpc/{function_name}", headers=self.headers, json=params
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _rest(
        self,
        method: str,
        table: str,
        *,
        params: Optional[List[Tuple[str, str]]] = None,
        json_body: Any = None,
    ) -> Any:
        response = self._client.request(
            method,
            f"{self.rest_url}/{table}",
            headers=self.headers,
            params=params or [],
            json=json_body,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {table} failed: {response.text}")
        if response.status_code == 204 or not response.content:
            return []
        return response.json()

    @staticmethod
    def _params(filters: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
        return list(filters)

    # -- generic table access ----------------------------------------------

    def select(
        self,
        table: str,
        filters: Iterable[Tuple[str, str]] = (),
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if self.local:
            return self.store.select(table, filters, columns=columns, order=order, limit=limit)

        params = self._params(filters)
        params.append(("select", columns))
        if order:
            params.append(("order", order))
        if limit is not None:
            params.append(("limit", str(limit)))
        return self._rest("GET", table, params=params) or []

    def insert(self, table: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.local:
            return self.store.insert(table, data)
        return self._rest("POST", table, json_body=data) or []

    def update(
        self, table: str, filters: Iterable[Tuple[str, str]], data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if self.local:
            return self.store.update(table, filters, data)
        return self._rest("PATCH", table, params=self._params(filters), json_body=data) or []

    def delete(self, table: str, filters: Iterable[Tuple[str, str]]) -> List[Dict[str, Any]]:
        if self.local:
            return self.store.delete(table, filters)
        return self._rest("DELETE", table, params=self._params(filters)) or []

    # -- job queue ----------------------------------------------------------

    def claim_job(self, job_id: Optional[str] = None) -> Optional[JobModel]:
        """Atomically take the next pending job (or a specific one) off the queue."""
        if self.local:
            return self.store.claim_job(job_id)

        try:
            data = self._rpc("claim_next_job", {})
            if not data:
                return None
            row = data[0]
            return JobModel(
                id=row["j_id"],
                project_id=row["j_project_id"],
                type=row["j_type"],
                status=row["j_status"],
                payload=row["j_payload"] or {},
                result=row["j_result"] or {},
                created_at=row["j_created_at"],
                started_at=row["j_started_at"],
                completed_at=row["j_completed_at"],
                error_message=row["j_error_message"],
            )
        except Exception as exc:
            logger.error("Failed to claim job: %s", exc)
            return None

    def commit_bundle(self, bundle: JobBundle) -> None:
        """Persist a job's entire output in one transaction."""
        if self.local:
            self.store.commit_bundle(bundle)
            return

        def clean(models):
            return [
                {k: (str(v) if isinstance(v, UUID) else v) for k, v in m.model_dump().items()}
                for m in models
            ]

        self._rpc(
            "commit_job_bundle",
            {
                "_job_id": str(bundle.job_id),
                "_project_id": str(bundle.project_id),
                "_artifacts": clean(bundle.artifacts),
                "_edges": clean(bundle.edges),
                "_renderings": clean(bundle.renderings),
                "_result": bundle.result,
            },
        )

    def fail_job(self, job_id: Any, error_message: str, *, retryable: bool = False) -> str:
        if self.local:
            return self.store.fail_job(job_id, error_message, retryable=retryable)

        self._rest(
            "PATCH",
            "jobs",
            params=[("id", f"eq.{job_id}")],
            json_body={"status": "failed", "error_message": error_message[:2000]},
        )
        return "failed"

    def cancel_job(self, job_id: Any) -> bool:
        if self.local:
            return self.store.cancel_job(job_id)
        rows = self.select("jobs", [("id", f"eq.{job_id}")], columns="id,status")
        if not rows or rows[0]["status"] in {"completed", "failed", "cancelled"}:
            return False
        self.update("jobs", [("id", f"eq.{job_id}")], {"status": "failed", "error_message": "Cancelled by user"})
        return True

    def reap_stale_jobs(self, older_than_seconds: int) -> List[str]:
        if self.local:
            return self.store.reap_stale_jobs(older_than_seconds)
        # Supabase deployments run the reaper as a scheduled SQL function.
        return []

    def pending_job_ids(self) -> List[str]:
        if self.local:
            return self.store.pending_job_ids()
        rows = self.select("jobs", [("status", "eq.pending")], columns="id", order="created_at.asc")
        return [row["id"] for row in rows]

    def get_job(self, job_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select("jobs", [("id", f"eq.{job_id}")])
        return rows[0] if rows else None

    # -- graph lookups ------------------------------------------------------

    def get_artifact(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select("artifacts", [("id", f"eq.{artifact_id}")])
        return rows[0] if rows else None

    def get_artifacts(self, artifact_ids: List[Any]) -> List[Dict[str, Any]]:
        """Batch fetch. Replaces the per-id loop that made source resolution N+1."""
        if not artifact_ids:
            return []
        joined = ",".join(str(a) for a in artifact_ids)
        return self.select("artifacts", [("id", f"in.({joined})")])

    def get_parent_edge(self, child_artifact_id: Any) -> Optional[Dict[str, Any]]:
        edges = self.get_all_parent_edges(child_artifact_id)
        return edges[0] if edges else None

    def get_all_parent_edges(self, child_artifact_id: Any) -> List[Dict[str, Any]]:
        return self.select("artifact_edges", [("child_artifact_id", f"eq.{child_artifact_id}")])

    def get_project(self, project_id: Any) -> Optional[Dict[str, Any]]:
        rows = self.select("projects", [("id", f"eq.{project_id}")])
        return rows[0] if rows else None

    def project_owner(self, project_id: Any) -> Optional[str]:
        rows = self.select("projects", [("id", f"eq.{project_id}")], columns="id,user_id")
        return rows[0].get("user_id") if rows else None

    def close(self) -> None:
        if not self.local and getattr(self, "_client", None):
            self._client.close()
