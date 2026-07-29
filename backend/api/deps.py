"""Request dependencies: identity, database access, and ownership checks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

from backend.services.database import Database, get_database

LOCAL_USER_ID = "local-user"


def resolve_user(authorization: Optional[str]) -> str:
    """
    Identify the caller.

    Today this hands back the same id for everybody. It takes an `Authorization`
    argument and never reads it, so nothing here authenticates anyone, and every
    request is treated as the owner of the one local workspace. There's no
    identity provider behind it to ask.

    Ownership is still written onto each project and checked on every read, which
    keeps the queries correct and leaves exactly one function to replace when
    accounts arrive. The unused argument stays in the signature for that reason.
    `get_current_user` and the WebSocket route both pass a header value in, so
    the day a real token gets verified, the change is inside this body and
    nowhere else.

    The flip side is worth saying plainly. While every caller resolves to the
    same user, an ownership check can't keep two people apart, because there's
    only ever one person.
    """
    return LOCAL_USER_ID


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """
    The caller's id, in the form a route can depend on.

    FastAPI pulls the `Authorization` header and passes it to `resolve_user`,
    which ignores it. No credential is verified anywhere along that path.
    """
    return resolve_user(authorization)


def get_db() -> Database:
    """The shared database handle."""
    return get_database()


def require_project(
    project_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    Load a project, and turn the caller away if it isn't theirs.

    The check is a plain `!=` against the stored `user_id`, so a project with no
    owner recorded matches nobody. It used to read `if owner and owner !=
    user_id`, and that handed any project with a NULL `user_id` to whoever asked
    for it. Meanwhile `list_projects` filtered those same rows out, so read said
    yes while list said no. Two endpoints disagreeing about one row is how a bug
    like that lives through a review.
    """
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
    """
    Fetch an artifact, once we know the caller owns the project holding it.

    An artifact carries no `user_id` of its own. Ownership lives on the project
    row, so the only way to answer "is this yours" is to look up the parent
    project and ask `require_project` about that.
    """
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
    Get an artifact the caller owns, and check it sits in the project they named.

    `require_artifact` has already settled ownership, so the extra question here
    is which project the artifact belongs to. An id from another of your own
    projects would clear the ownership check and still be wrong, because a
    provenance edge is filed under one project. Let a parent from elsewhere
    through and the canvas ends up drawing an edge to a node it can't find.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    if str(artifact["project_id"]) != str(project_id):
        raise HTTPException(status_code=400, detail="Artifact belongs to a different project")

    return artifact
