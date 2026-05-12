"""Artifact routes: read, edit, download, and the cross-project vault view."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import get_current_user, get_db, require_artifact
from backend.api.schemas import ArtifactUpdate, DownloadResponse
from backend.services.db_interface import DBInterface
from backend.services.storage import StorageError, get_object_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["artifacts"])


@router.get("/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    return require_artifact(artifact_id, user_id, db)


@router.get("/artifacts/{artifact_id}/lineage")
def get_lineage(
    artifact_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    """
    Where this artifact came from and what was built on top of it.

    With multi-input generation an artifact can have several parents, so this
    returns lists on both sides - it is the provenance view of the DAG the user
    drew on the canvas.
    """
    artifact = require_artifact(artifact_id, user_id, db)

    parent_edges = db.get_all_parent_edges(artifact_id)
    child_edges = db.select("artifact_edges", [("parent_artifact_id", f"eq.{artifact_id}")])

    parents = db.get_artifacts([edge["parent_artifact_id"] for edge in parent_edges])
    children = db.get_artifacts([edge["child_artifact_id"] for edge in child_edges])

    return {
        "artifact": artifact,
        "parents": parents,
        "children": children,
    }


@router.patch("/artifacts/{artifact_id}")
def update_artifact(
    artifact_id: str,
    updates: ArtifactUpdate,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    """
    Save user edits to an artifact.

    Content is shallow-merged rather than replaced, so a client that PATCHes
    only ``data`` does not wipe the attached binary metadata alongside it.
    """
    artifact = require_artifact(artifact_id, user_id, db)

    if updates.content is None:
        raise HTTPException(status_code=400, detail="No content supplied")

    merged = dict(artifact.get("content") or {})
    merged.update(updates.content)
    merged["edited_by_user"] = True

    rows = db.update("artifacts", [("id", f"eq.{artifact_id}")], {"content": merged})
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")

    logger.info("Artifact %s edited by %s", artifact_id, user_id)
    return rows[0]


@router.get("/artifacts/{artifact_id}/download", response_model=DownloadResponse)
def download_artifact(
    artifact_id: str,
    inline: bool = Query(False, description="Preview in the browser instead of downloading"),
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> DownloadResponse:
    """
    A time-limited URL for the artifact's rendered file.

    The URL comes from the active object store, so this is a Cloudflare
    presigned URL or a signed local ``/api/files`` path depending on
    configuration. The caller does not need to know which.
    """
    artifact = require_artifact(artifact_id, user_id, db)

    binary = (artifact.get("content") or {}).get("binary")
    if not binary:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact {artifact_id} has no downloadable file attached",
        )

    storage_path = binary.get("storage_path")
    if not storage_path:
        raise HTTPException(status_code=500, detail="Binary metadata is missing its storage path")

    fmt = binary.get("format", "bin")
    mime_type = binary.get("mime_type", "application/octet-stream")
    filename = f"{artifact.get('type', 'artifact')}_{str(artifact_id)[:8]}.{fmt}"

    store = get_object_store()
    try:
        url = store.signed_url(storage_path, filename=filename, inline=inline)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Could not sign a URL for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Could not produce a download link") from exc

    return DownloadResponse(
        download_url=url,
        format=fmt,
        mime_type=mime_type,
        filename=filename,
        backend=store.backend_name,
    )


@router.get("/vault")
def list_vault(
    limit: int = Query(200, ge=1, le=1000),
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """Every artifact the caller owns, newest first, across all their projects."""
    projects = db.select("projects", [("user_id", f"eq.{user_id}")], columns="id,name")
    if not projects:
        return {"files": []}

    names = {p["id"]: p.get("name") for p in projects}
    artifacts = db.select(
        "artifacts",
        [("project_id", f"in.({','.join(names)})")],
        order="created_at.desc",
        limit=limit,
    )
    for artifact in artifacts:
        artifact["project_name"] = names.get(artifact["project_id"])

    return {"files": artifacts}
