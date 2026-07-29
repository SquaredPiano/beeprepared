"""The unit of work a handler returns and the runner commits."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def as_uuid(value: Any) -> UUID:
    """
    Parse an artifact id, and refuse anything that isn't one.

    Ids reach us as strings out of JSON. An earlier version parsed them loosely
    enough that a malformed id didn't raise here. It quietly became a lookup for
    an artifact that never existed.
    """
    if isinstance(value, UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"Not a valid artifact id: {value!r}") from error


class ArtifactPayload(BaseModel):
    """A node in the knowledge graph, before it's been written."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: UUID
    project_id: UUID
    type: str
    content: Dict[str, Any]


class EdgePayload(BaseModel):
    """
    A provenance link, saying `child` was derived from `parent`.

    A child can have more than one. An artifact built from three lectures has
    three of these, so what the edges describe is a DAG and not a tree. A
    knowledge core has none at all, because it wasn't derived from anything that
    was already in the graph.
    """

    parent_artifact_id: UUID
    child_artifact_id: UUID
    project_id: UUID
    relationship_type: str = "derived_from"


class JobBundle(BaseModel):
    """
    Everything one job produced.

    A handler builds one of these and never touches the database itself. The
    runner commits the whole bundle in a single transaction, so a handler that
    dies midway through leaves no half-built graph behind.
    """

    job_id: UUID
    project_id: UUID
    artifacts: List[ArtifactPayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
