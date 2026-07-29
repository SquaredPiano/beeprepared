"""Request and response bodies for the HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
    """
    Where an ingest job is to get its source.

    There are two ways to name a source and a job uses one of them, never both.
    `source_ref` is a URL for the pipeline to fetch. `staged_key` names an upload
    that's already waiting in the file store, which is where the upload endpoint
    leaves one.
    """

    source_type: str
    source_ref: Optional[str] = None
    staged_key: Optional[str] = None
    original_name: str = "Untitled"

    @field_validator("source_type")
    @classmethod
    def known_source(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
        return value

    @model_validator(mode="after")
    def exactly_one_reference(self) -> "IngestRequest":
        """
        Insist on exactly one of the two source references.

        A job that names both tells us nothing about which one it meant. One that
        names neither has nothing to read at all, and if we accept it here it
        just fails inside a worker some minutes later, where nobody is watching
        the response.
        """
        if bool(self.source_ref) == bool(self.staged_key):
            raise ValueError(
                "an ingest job names exactly one of source_ref, a URL to fetch, and "
                "staged_key, an upload waiting in the file store"
            )
        return self

    @model_validator(mode="after")
    def only_youtube_is_named_by_a_url(self) -> "IngestRequest":
        """
        Keep the downloader on the network and everything else in the store.

        Give yt-dlp a bare path and it will happily read a local file for you, so
        a YouTube ingest becomes a way to read files off the server. Demanding
        `http://` or `https://` is a cheap early no, and it isn't the real guard.
        It says nothing about where the URL points, and an http(s) URL aimed at an
        internal address is an SSRF. The host is authorised by `YouTubeUrlGuard`
        in `backend/pipeline/ingestion.py`, right before the call that fetches it.

        Every other source type is refused a `source_ref` outright. For those it
        used to be a filesystem path, which turned any ingest job into a read of
        any file the server could open, with no downloader involved at all. Those
        sources are named by the key their upload was staged under, and that key
        gets checked against the project the job belongs to.
        """
        if self.source_type == "youtube":
            if not (self.source_ref or "").startswith(("http://", "https://")):
                raise ValueError("source_ref must be an http(s) URL for a youtube source")
        elif self.source_ref:
            raise ValueError(
                f"a {self.source_type} source is named by the staged_key of an upload, "
                "not by a source_ref"
            )
        return self


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

    @model_validator(mode="after")
    def at_least_one_source(self) -> "GenerateRequest":
        if not self.sources():
            raise ValueError("source_artifact_ids must name at least one artifact")
        return self

    def sources(self) -> List[str]:
        """Every source id, whether the caller sent the list or the single-id shorthand."""
        return self.source_artifact_ids or ([self.source_artifact_id] if self.source_artifact_id else [])


class RefineRequest(BaseModel):
    source_artifact_id: str
    instructions: str = Field(min_length=1, max_length=4000)
    target_type: Optional[str] = None

    @field_validator("target_type")
    @classmethod
    def known_target(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in GENERATED_TYPES:
            raise ValueError(f"target_type must be one of: {', '.join(sorted(GENERATED_TYPES))}")
        return value


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

    Nodes and edges are both optional. Leave them out and we compile whichever
    canvas the project has saved.
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
