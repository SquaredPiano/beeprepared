"""
GenerateHandler: Bridge between DB Jobs and ArtifactGenerator.

INVARIANTS:
- ONLY accepts artifacts whose type is in ALLOWED_GENERATIONS
- Fail fast if source type is invalid
- Produces exactly 1 artifact + 1 edge
"""

import uuid
import logging
from typing import Dict, Any, Optional

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle, ArtifactPayload, EdgePayload
from backend.handlers.base import JobHandler
from backend.services.db_interface import DBInterface
from backend.services.generators import ArtifactGenerator
from backend.core.knowledge_core import KnowledgeCore

logger = logging.getLogger(__name__)


# ============================================================================
# FROZEN CONTRACTS
# ============================================================================

ALLOWED_GENERATIONS: Dict[str, set] = {
    "knowledge_core": {"quiz", "exam", "notes", "slides", "flashcards"},
    "quiz": {"flashcards"},
    "exam": set(),
    "slides": set(),
    "notes": set(),
    "flashcards": set(),
}


class GenerateHandler(JobHandler):
    """
    Handles 'generate' job type.
    
    Input Payload (frozen):
    {
        "source_artifact_id": "uuid",
        "target_type": "quiz | exam | notes | slides | flashcards"
    }
    
    Output:
    - Artifact: kind=generated, type=<target_type>
    - Edge: source_artifact_id → new_artifact_id
    """

    def __init__(self):
        self.db = DBInterface()
        self.generator = ArtifactGenerator()

    async def run(self, job: JobModel) -> JobBundle:
        logger.info(f"[GenerateHandler] Processing job {job.id}")
        
        payload = job.payload
        
        # --- Validate Payload ---
        source_artifact_id = payload.get("source_artifact_id")
        target_type = payload.get("target_type")
        
        if not source_artifact_id:
            raise ValueError("source_artifact_id is required")
        
        if not target_type:
            raise ValueError("target_type is required")
        
        # --- Fetch Source Artifact ---
        logger.info(f"[GenerateHandler] Fetching source artifact: {source_artifact_id}")
        source_artifact = self.db.get_artifact(uuid.UUID(source_artifact_id))
        
        if not source_artifact:
            raise ValueError(f"Source artifact not found: {source_artifact_id}")
        
        source_type = source_artifact.get("type")
        
        # --- CRITICAL ASSERTION: Check ALLOWED_GENERATIONS ---
        allowed_targets = ALLOWED_GENERATIONS.get(source_type, set())
        
        if target_type not in allowed_targets:
            raise ValueError(
                f"Cannot generate '{target_type}' from '{source_type}'. "
                f"Allowed: {allowed_targets or 'none'}"
            )
        
        logger.info(f"[GenerateHandler] Generating {target_type} from {source_type}")
        
        # --- Get Knowledge Core ---
        # If source is knowledge_core, use it directly
        # If source is quiz (for flashcards), we need to fetch the parent core
        content = source_artifact.get("content", {})
        
        if source_type == "knowledge_core":
            core_data = content.get("core")
            if not core_data:
                raise ValueError("knowledge_core artifact missing 'core' in content")
            knowledge_core = KnowledgeCore(**core_data)
        elif source_type == "quiz":
            # For quiz → flashcards, we can generate flashcards from quiz content
            # But we need the quiz model, not knowledge core
            # For now, we require knowledge_core as source for all generation
            raise ValueError(
                f"Recursive generation from '{source_type}' not yet implemented. "
                f"Please use knowledge_core as source."
            )
        else:
            raise ValueError(f"Cannot extract knowledge from source type: {source_type}")
        
        # --- Generate Target Artifact ---
        generated_model = None
        
        if target_type == "quiz":
            generated_model = self.generator.generate_quiz(knowledge_core)
        elif target_type == "exam":
            generated_model = self.generator.generate_exam(knowledge_core)
        elif target_type == "notes":
            generated_model = self.generator.generate_notes(knowledge_core)
        elif target_type == "slides":
            generated_model = self.generator.generate_slides(knowledge_core)
        elif target_type == "flashcards":
            generated_model = self.generator.generate_flashcards(knowledge_core)
        else:
            raise ValueError(f"Unknown target_type: {target_type}")
        
        if not generated_model:
            raise RuntimeError(f"Generation failed for {target_type}")
        
        logger.info(f"[GenerateHandler] Generated {target_type} successfully")
        
        # --- Build JobBundle ---
        new_artifact_id = uuid.uuid4()
        
        artifact = ArtifactPayload(
            id=new_artifact_id,
            project_id=job.project_id,
            type=target_type,
            content={
                "kind": "generated",
                "data": generated_model.model_dump(),
            }
        )
        
        edge = EdgePayload(
            parent_artifact_id=uuid.UUID(source_artifact_id),
            child_artifact_id=new_artifact_id,
            relationship_type="derived_from",
            project_id=job.project_id,
        )
        
        bundle = JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[artifact],
            edges=[edge],
            renderings=[],
            result={
                "status": "success",
                "artifact_id": str(new_artifact_id),
                "artifact_type": target_type,
            }
        )
        
        logger.info(f"[GenerateHandler] Job {job.id} completed. Created 1 artifact, 1 edge.")
        return bundle
