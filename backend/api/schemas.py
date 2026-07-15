"""Request and response bodies for the HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.artifacts import GENERATED_TYPES, SOURCE_TYPES

JOB_TYPES = frozenset({"ingest", "generate", "refine"})


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
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


class IngestRequest(BaseModel):
    source_type: str
    source_ref: str
    original_name: str = "Untitled"

    @field_validator("source_type")
    @classmethod
    def known_source(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
        return value


class GenerateRequest(BaseModel):
    target_type: str
    source_artifact_ids: List[str] = Field(default_factory=list)
    source_artifact_id: Optional[str] = None
    instructions: Optional[str] = Field(None, max_length=4000)

    @field_validator("target_type")
    @classmethod
    def known_target(cls, value: str) -> str:
        if value not in GENERATED_TYPES:
            raise ValueError(f"target_type must be one of: {', '.join(sorted(GENERATED_TYPES))}")
        return value

    def sources(self) -> List[str]:
        """Every source id, accepting the single-source shorthand."""
        return self.source_artifact_ids or ([self.source_artifact_id] if self.source_artifact_id else [])


class RefineRequest(BaseModel):
    source_artifact_id: str
    instructions: str = Field(min_length=1, max_length=4000)
    target_type: Optional[str] = None


class JobRequest(BaseModel):
    project_id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def known_type(cls, value: str) -> str:
        if value not in JOB_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(JOB_TYPES))}")
        return value


class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"
    dispatch: str = "local"
    reused: bool = False


class JobStatus(BaseModel):
    id: str
    project_id: str
    type: str
    status: str
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    attempts: Optional[int] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ArtifactUpdate(BaseModel):
    content: Optional[Dict[str, Any]] = None


class DownloadLink(BaseModel):
    download_url: str
    format: str
    mime_type: str
    filename: str


class FlowRequest(BaseModel):
    """
    The graph to compile.

    Nodes and edges are optional; when omitted the project's saved canvas is
    used instead.
    """

    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None


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


class ChatRequest(BaseModel):
    project_id: str
    message: str = Field(min_length=1, max_length=4000)
    artifact_id: Optional[str] = Field(None, description="The artifact in view, if any")


class ChatResponse(BaseModel):
    reply: str
    action: str = "answer"
    job_id: Optional[str] = None
    target_type: Optional[str] = None
