"""The unit of work a handler returns and the runner commits."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def as_uuid(value: Any) -> UUID:
    """Parse an artifact identifier, rejecting anything malformed."""
    if isinstance(value, UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"Not a valid artifact id: {value!r}") from error


class ArtifactPayload(BaseModel):
    """A node in the knowledge graph, before it is written."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: UUID
    project_id: UUID
    type: str
    content: Dict[str, Any]


class EdgePayload(BaseModel):
    """A provenance link: `child` was derived from `parent`."""

    parent_artifact_id: UUID
    child_artifact_id: UUID
    project_id: UUID
    relationship_type: str = "derived_from"


class JobBundle(BaseModel):
    """
    Everything one job produced.

    Handlers build this and never touch the database; the runner commits it in a
    single transaction, so a handler that fails midway leaves no partial graph.
    """

    job_id: UUID
    project_id: UUID
    artifacts: List[ArtifactPayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
