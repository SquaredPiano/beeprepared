from typing import List, Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

# Matches SQL type 'artifact_type' via string serialization
class ArtifactPayload(BaseModel):
    id: UUID
    project_id: UUID
    type: str # 'video', 'text', 'knowledge_core', etc.
    content: Dict[str, Any] # JSONB
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# Matches SQL type 'edge_type' via string serialization 
class EdgePayload(BaseModel):
    parent_artifact_id: UUID
    child_artifact_id: UUID
    relationship_type: str = "derived_from" # 'derived_from', 'contains', 'references'
    project_id: UUID

# Matches SQL type 'render_format' via string serialization
class RenderingPayload(BaseModel):
    id: Optional[UUID] = None # Optional usually, but we might want schema strictness
    project_id: UUID
    artifact_id: UUID
    format: str # 'pdf', 'mp3', etc.
    r2_path: str

class JobBundle(BaseModel):
    job_id: UUID
    project_id: UUID
    artifacts: List[ArtifactPayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)
    renderings: List[RenderingPayload] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
