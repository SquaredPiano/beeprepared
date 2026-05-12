"""Job routes: create, inspect, list and cancel work."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import (
    GeneratePayload,
    IngestPayload,
    JobRequest,
    JobResponse,
    JobStatusResponse,
    RefinePayload,
)
from backend.services.db_interface import DBInterface
from backend.services.dispatcher import enqueue
from backend.services.events import EVENT_JOB_CANCELLED, EVENT_JOB_CREATED, publish

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

PAYLOAD_MODELS = {
    "ingest": IngestPayload,
    "generate": GeneratePayload,
    "refine": RefinePayload,
}

ACTIVE_STATUSES = ("pending", "running")


def _find_reusable_job(
    db: DBInterface, project_id: str, payload: GeneratePayload
) -> Optional[Dict[str, Any]]:
    """
    Find an existing job that already does exactly this work.

    Only in-flight jobs are reused. The original implementation also returned
    *completed* jobs, which meant clicking "regenerate" silently handed back the
    old artifact and looked like the button was broken. Deduplicating concurrent
    duplicates is worth doing; refusing to ever regenerate is not.

    A steered generation is never deduplicated - different instructions are
    different work by definition.
    """
    if payload.instructions:
        return None

    wanted = sorted(payload.resolved_sources())
    if not wanted:
        return None

    candidates = db.select(
        "jobs",
        [("project_id", f"eq.{project_id}"), ("type", "eq.generate"),
         ("status", f"in.({','.join(ACTIVE_STATUSES)})")],
        order="created_at.desc",
        limit=50,
    )

    for job in candidates:
        job_payload = job.get("payload") or {}
        if job_payload.get("target_type") != payload.target_type:
            continue
        if job_payload.get("instructions"):
            continue
        sources = job_payload.get("source_artifact_ids") or (
            [job_payload["source_artifact_id"]] if job_payload.get("source_artifact_id") else []
        )
        if sorted(str(s) for s in sources) == wanted:
            return job
    return None


@router.post("", response_model=JobResponse, status_code=202)
def create_job(
    request: JobRequest,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> JobResponse:
    """
    Queue a job.

    The row is written first and dispatched second, so a broker hiccup delays
    the work instead of losing it - the periodic drain task picks up anything
    that was never enqueued.
    """
    require_project(request.project_id, user_id, db)

    model = PAYLOAD_MODELS[request.type]
    try:
        payload = model(**request.payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {request.type} payload: {exc}") from exc

    if request.type == "generate":
        existing = _find_reusable_job(db, request.project_id, payload)
        if existing:
            logger.info("Reusing in-flight job %s for an identical request", existing["id"])
            return JobResponse(
                job_id=existing["id"], status=existing["status"], dispatch="reused", reused=True
            )

    rows = db.insert("jobs", {
        "project_id": request.project_id,
        "type": request.type,
        "status": "pending",
        "payload": payload.model_dump(exclude_none=True),
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create the job")

    job_id = rows[0]["id"]
    logger.info("Created %s job %s for project %s", request.type, job_id, request.project_id)

    publish(request.project_id, EVENT_JOB_CREATED, {"job_id": job_id, "type": request.type})
    dispatch = enqueue(job_id)

    return JobResponse(job_id=job_id, status="pending", dispatch=dispatch)


@router.get("")
def list_jobs(
    project_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Recent jobs for one project, or across every project the caller owns."""
    if project_id:
        require_project(project_id, user_id, db)
        return db.select(
            "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=limit
        )

    projects = db.select("projects", [("user_id", f"eq.{user_id}")], columns="id")
    project_ids = [p["id"] for p in projects]
    if not project_ids:
        return []

    return db.select(
        "jobs",
        [("project_id", f"in.({','.join(project_ids)})")],
        order="created_at.desc",
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> JobStatusResponse:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    require_project(job["project_id"], user_id, db)

    return JobStatusResponse(**{
        field: job.get(field) for field in JobStatusResponse.model_fields
    })


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    """
    Cancel a queued or running job.

    A running job is marked cancelled immediately; the worker notices when it
    next commits and discards the result rather than writing an artifact the
    user has already abandoned.
    """
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    require_project(job["project_id"], user_id, db)

    cancelled = db.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"Job is already {job['status']} and cannot be cancelled",
        )

    publish(job["project_id"], EVENT_JOB_CANCELLED, {"job_id": job_id})
    return {"status": "cancelled", "id": job_id}
