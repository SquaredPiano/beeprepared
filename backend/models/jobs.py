"""Job queue vocabulary: what work exists and what state it can be in."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobType(str, Enum):
    """The kinds of work the queue knows how to run."""

    INGEST = "ingest"
    GENERATE = "generate"
    REFINE = "refine"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
})


class IngestPayload(BaseModel):
    """
    Turn a raw source file into a knowledge core.

    A source arrives one of two ways, and the field it's under tells you which.
    `source_ref` is a URL for us to fetch. `staged_key` names an upload that's
    already sitting in the file store. We name that upload by storage key and not
    by path, because that's what lets the container that accepted the upload and
    the container that ingests it be two different containers. All they have to
    share is the volume the store lives on.
    """

    source_type: str
    source_ref: Optional[str] = None
    staged_key: Optional[str] = None
    original_name: str = "Untitled"


class GeneratePayload(BaseModel):
    """Turn one artifact, or several, into a new one."""

    target_type: str
    source_artifact_ids: List[str] = Field(default_factory=list)
    instructions: Optional[str] = None
    flow_run_id: Optional[str] = None
    flow_node_id: Optional[str] = None


class RefinePayload(BaseModel):
    """Rebuild an existing artifact against a plain-English request."""

    source_artifact_id: str
    instructions: str
    target_type: Optional[str] = None


class JobModel(BaseModel):
    """One row out of the job queue."""

    model_config = ConfigDict(use_enum_values=False)

    id: UUID
    project_id: UUID
    type: JobType
    status: JobStatus
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def flow_run_id(self) -> Optional[str]:
        return self.payload.get("flow_run_id")

    @property
    def flow_node_id(self) -> Optional[str]:
        return self.payload.get("flow_node_id")
