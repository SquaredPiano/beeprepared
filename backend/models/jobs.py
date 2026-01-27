from enum import Enum
from typing import Optional, Dict, Any, List, Union
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

# Enums matching SQL Schema
class JobType(str, Enum):
    INGEST = "ingest"
    EXTRACT = "extract"
    CLEAN = "clean"
    GENERATE = "generate"
    RENDER = "render"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

# --- Payloads for specific Job Types ---

class IngestPayload(BaseModel):
    source_type: str = Field(..., description="youtube, local_file, etc.")
    source_url: Optional[str] = None
    file_path: Optional[str] = None # For local files before upload
    title: Optional[str] = None

class ExtractPayload(BaseModel):
    artifact_id: UUID

class CleanPayload(BaseModel):
    artifact_id: UUID # Points to RAW_TEXT artifact
    
class GeneratePayload(BaseModel):
    source_artifact_id: UUID # Points to KNOWLEDGE_CORE or similar
    target_type: str # quiz, flashcards, etc.
    parameters: Dict[str, Any] = {} # Difficulty, count, etc.

class RenderPayload(BaseModel):
    artifact_id: UUID
    format: str # pdf, pptx

# --- Main Job Model ---

class JobModel(BaseModel):
    id: UUID
    project_id: UUID
    type: JobType
    status: JobStatus
    payload: Dict[str, Any] # Flexible to accept any of the above dumps
    result: Dict[str, Any] = {}
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat()
        }
