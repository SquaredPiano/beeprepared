from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobType(str, Enum):
    """Kinds of work the queue can execute."""

    INGEST = "ingest"      # raw source -> knowledge core
    GENERATE = "generate"  # knowledge core (or artifacts) -> new artifact
    REFINE = "refine"      # existing artifact + instructions -> revised artifact
    EXTRACT = "extract"    # reserved: standalone text extraction
    CLEAN = "clean"        # reserved: standalone text cleaning
    RENDER = "render"      # reserved: standalone binary rendering


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


# --- Typed payloads -------------------------------------------------------
# The job row stores an untyped dict; these document and validate what each
# job type expects to find in it.

class IngestPayload(BaseModel):
    source_type: str = Field(..., description="youtube | audio | video | pdf | pptx | md")
    source_ref: str = Field(..., description="URL, or a path to the uploaded file")
    original_name: str = "Untitled"


class GeneratePayload(BaseModel):
    target_type: str = Field(..., description="quiz | exam | notes | slides | flashcards | ...")
    source_artifact_ids: Optional[list[str]] = Field(
        None, description="All inputs wired into the generator node"
    )
    source_artifact_id: Optional[str] = Field(
        None, description="Single-source form, kept for backwards compatibility"
    )
    instructions: Optional[str] = Field(None, description="Free-text steering for the model")
    flow_run_id: Optional[str] = Field(None, description="Set when the job is part of a flow run")


class RefinePayload(BaseModel):
    source_artifact_id: str = Field(..., description="The artifact being revised")
    instructions: str = Field(..., description="What the user wants changed")
    target_type: Optional[str] = Field(None, description="Defaults to the source artifact's type")


class RenderPayload(BaseModel):
    artifact_id: UUID
    format: str


# --- Job ------------------------------------------------------------------

class JobModel(BaseModel):
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
        """The flow run this job belongs to, if it was dispatched by one."""
        return self.payload.get("flow_run_id")

    model_config = ConfigDict(use_enum_values=False)
