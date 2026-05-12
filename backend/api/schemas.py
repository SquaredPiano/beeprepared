"""Request and response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.artifacts import GENERATED_ARTIFACT_TYPES

VALID_SOURCE_TYPES = {"youtube", "audio", "video", "pdf", "pptx", "md"}


# --- Projects --------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    canvas_state: Optional[Dict[str, Any]] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    user_id: Optional[str] = None
    canvas_state: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# --- Jobs ------------------------------------------------------------------

class IngestPayload(BaseModel):
    source_type: str
    source_ref: str
    original_name: str = "Untitled"

    @field_validator("source_type")
    @classmethod
    def known_source(cls, value: str) -> str:
        if value not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}")
        return value


class GeneratePayload(BaseModel):
    target_type: str
    source_artifact_id: Optional[str] = None
    source_artifact_ids: Optional[List[str]] = None
    instructions: Optional[str] = Field(None, max_length=4000)

    @field_validator("target_type")
    @classmethod
    def known_target(cls, value: str) -> str:
        if value not in GENERATED_ARTIFACT_TYPES:
            raise ValueError(
                f"target_type must be one of: {', '.join(sorted(GENERATED_ARTIFACT_TYPES))}"
            )
        return value

    def resolved_sources(self) -> List[str]:
        return self.source_artifact_ids or ([self.source_artifact_id] if self.source_artifact_id else [])


class RefinePayload(BaseModel):
    source_artifact_id: str
    instructions: str = Field(..., min_length=1, max_length=4000)
    target_type: Optional[str] = None


class JobRequest(BaseModel):
    project_id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def known_type(cls, value: str) -> str:
        allowed = {"ingest", "generate", "refine"}
        if value not in allowed:
            raise ValueError(f"type must be one of: {', '.join(sorted(allowed))}")
        return value


class JobResponse(BaseModel):
    job_id: str
    status: str = "pending"
    dispatch: str = "local"
    reused: bool = False


class JobStatusResponse(BaseModel):
    id: str
    project_id: str
    type: str
    status: str
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: Optional[int] = None


# --- Artifacts -------------------------------------------------------------

class ArtifactUpdate(BaseModel):
    content: Optional[Dict[str, Any]] = None


class DownloadResponse(BaseModel):
    download_url: str
    format: str
    mime_type: str
    filename: str
    backend: str


# --- Flows -----------------------------------------------------------------

class FlowRunRequest(BaseModel):
    """
    Run the project's canvas as a pipeline.

    Nodes and edges may be supplied directly (running unsaved canvas state) or
    omitted, in which case the project's persisted ``canvas_state`` is used.
    """

    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None


class FlowValidateRequest(FlowRunRequest):
    pass


class FlowStepView(BaseModel):
    node_id: str
    target_type: str
    parents: List[str]
    depth: int


class FlowPlanResponse(BaseModel):
    valid: bool
    steps: List[FlowStepView] = Field(default_factory=list)
    waves: int = 0
    error: Optional[str] = None


class FlowRunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    node_states: Dict[str, Any]
    plan: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


# --- Assistant -------------------------------------------------------------

class ChatRequest(BaseModel):
    """A message to the in-app assistant."""

    project_id: str
    message: str = Field(..., min_length=1, max_length=4000)
    artifact_id: Optional[str] = Field(
        None, description="The artifact in view. Refinement targets this."
    )


class ChatResponse(BaseModel):
    reply: str
    action: str = "answer"           # answer | refine | generate
    job_id: Optional[str] = None
    target_type: Optional[str] = None
