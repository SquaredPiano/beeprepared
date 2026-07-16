"""Artifacts: read, edit, trace provenance, and download exports."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import get_current_user, get_db, require_artifact
from backend.api.schemas import ArtifactUpdate, DownloadLink
from backend.services.database import Database
from backend.services.files import FileStore, StorageError, get_file_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])

VAULT_LIMIT = 200


@router.get("/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """One artifact and its content."""
    return require_artifact(artifact_id, user_id, database)


@router.get("/artifacts/{artifact_id}/lineage")
def get_lineage(
    artifact_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """
    What this artifact came from and what was built on it.

    Both sides are lists: with multi-input generation an artifact genuinely has
    several parents.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    parent_edges = database.get_parent_edges(artifact_id)
    child_edges = database.get_child_edges(artifact_id)

    return {
        "artifact": artifact,
        "parents": database.get_artifacts([edge["parent_artifact_id"] for edge in parent_edges]),
        "children": database.get_artifacts([edge["child_artifact_id"] for edge in child_edges]),
    }


@router.patch("/artifacts/{artifact_id}")
def update_artifact(
    artifact_id: str,
    updates: ArtifactUpdate,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """
    Save user edits.

    Content is merged rather than replaced, so a client sending only `data` does
    not discard the attached export metadata.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    if updates.content is None:
        raise HTTPException(status_code=400, detail="No content supplied")

    merged = {**(artifact.get("content") or {}), **updates.content, "edited_by_user": True}
    rows = database.update("artifacts", [("id", f"eq.{artifact_id}")], {"content": merged})
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")

    logger.info("Artifact %s edited", artifact_id)
    return rows[0]


@router.get("/artifacts/{artifact_id}/download", response_model=DownloadLink)
def download_artifact(
    artifact_id: str,
    inline: bool = Query(False, description="Preview in the browser instead of downloading"),
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
    store: FileStore = Depends(get_file_store),
) -> DownloadLink:
    """A time-limited link to the artifact's exported file."""
    artifact = require_artifact(artifact_id, user_id, database)

    export = (artifact.get("content") or {}).get("binary")
    if not export:
        raise HTTPException(status_code=404, detail="This artifact has no exported file")

    key = export.get("storage_path")
    if not key:
        raise HTTPException(status_code=500, detail="Export metadata is missing its storage key")

    file_format = export.get("format", "bin")
    filename = f"{artifact.get('type', 'artifact')}_{str(artifact_id)[:8]}.{file_format}"

    try:
        url = store.signed_url(key, filename=filename, inline=inline)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return DownloadLink(
        download_url=url,
        format=file_format,
        mime_type=export.get("mime_type", "application/octet-stream"),
        filename=filename,
    )


@router.get("/vault")
def list_vault(
    limit: int = Query(VAULT_LIMIT, ge=1, le=1000),
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """Every artifact the caller owns, newest first, across all their projects."""
    projects = database.select("projects", [("user_id", f"eq.{user_id}")], columns="id,name")
    if not projects:
        return {"files": []}

    names = {project["id"]: project.get("name") for project in projects}
    artifacts = database.select(
        "artifacts",
        [("project_id", f"in.({','.join(names)})")],
        order="created_at.desc",
        limit=limit,
    )

    for artifact in artifacts:
        artifact["project_name"] = names.get(artifact["project_id"])

    return {"files": artifacts}
