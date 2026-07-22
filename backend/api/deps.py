"""Request dependencies: identity, database access, and ownership checks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

from backend.services.database import Database, get_database

LOCAL_USER_ID = "local-user"


def resolve_user(authorization: Optional[str]) -> str:
    """
    Identify the caller.

    This deployment serves a single local workspace, so there is no identity
    provider and every caller is that workspace's owner. Ownership is still
    recorded on each project and checked on every read, which is what keeps the
    queries correct and leaves one seam to replace if accounts are ever added.
    """
    return LOCAL_USER_ID


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """The authenticated caller's id."""
    return resolve_user(authorization)


def get_db() -> Database:
    """The shared database handle."""
    return get_database()


def require_project(
    project_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """Load a project and assert the caller owns it."""
    database = database or get_database()
    project = database.get_project(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return project


def require_artifact(
    artifact_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """Load an artifact and assert the caller owns the project it belongs to."""
    database = database or get_database()
    artifact = database.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    require_project(artifact["project_id"], user_id, database)
    return artifact


def require_project_artifact(
    artifact_id: str,
    project_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    Load an artifact the caller owns and assert it sits in the named project.

    Provenance edges are filed under a single project, so an edge to a parent
    living elsewhere would render as a dangling link on the canvas.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    if str(artifact["project_id"]) != str(project_id):
        raise HTTPException(status_code=400, detail="Artifact belongs to a different project")

    return artifact
