"""
GenerateHandler: Bridge between DB Jobs and ArtifactGenerator.

INVARIANTS:
- ONLY accepts artifacts whose type is in ALLOWED_GENERATIONS
- Fail fast if source type is invalid
- Produces exactly 1 artifact + 1 edge
- Binary outputs (PDF, PPTX) are generated and uploaded to R2
"""

import uuid
import logging
from typing import Dict, Any, Optional

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle, ArtifactPayload, EdgePayload
from backend.handlers.base import JobHandler
from backend.services.db_interface import DBInterface
from backend.services.generators import ArtifactGenerator
from backend.services.binary_renderer import BinaryRenderer
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
    - Binary: PDF/PPTX uploaded to R2 (for exam/slides)
    """

    def __init__(self):
        self.db = DBInterface()
        self.generator = ArtifactGenerator()
        self.binary_renderer = BinaryRenderer()

    def _validate_artifact_semantics(self, target_type: str, model) -> None:
        """
        Enforce minimum content requirements for each artifact type.
        Raises RuntimeError if validation fails.
        """
        # INVARIANT: Completed jobs must produce usable artifacts
        data = model.model_dump() if hasattr(model, 'model_dump') else model
        
        # Notes are now pure markdown - validate body length, not sections
        if target_type == "notes":
            body = data.get("body", "")
            if len(body) < 200:
                raise RuntimeError(
                    f"Semantic validation failed for notes: "
                    f"expected at least 200 characters, got {len(body)}"
                )
            return
        
        MIN_REQUIREMENTS = {
            "quiz": ("questions", 5, "questions"),
            "flashcards": ("cards", 5, "cards"),
            "slides": ("slides", 3, "slides"),
            "exam": ("questions", 10, "questions"),
        }
        
        if target_type not in MIN_REQUIREMENTS:
            return  # Unknown type, skip validation
        
        field, min_count, label = MIN_REQUIREMENTS[target_type]
        
        items = data.get(field, [])
        count = len(items) if items else 0
        
        if count < min_count:
            raise RuntimeError(
                f"Semantic validation failed for {target_type}: "
                f"expected at least {min_count} {label}, got {count}"
            )

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
        
        # --- Semantic Validation: Ensure artifact has minimum content ---
        self._validate_artifact_semantics(target_type, generated_model)
        
        logger.info(f"[GenerateHandler] Generated {target_type} successfully")
        
        # --- Build JobBundle ---
        new_artifact_id = uuid.uuid4()
        
        # --- Binary Rendering (PDF/PPTX) ---
        # INVARIANT: For exam and slides, binary MUST exist or job FAILS.
        # A COMPLETED artifact means "fully usable and downloadable".
        binary_metadata = None
        
        if target_type == "exam":
            logger.info(f"[GenerateHandler] Starting PDF render for exam artifact {new_artifact_id}")
            binary_metadata = self.binary_renderer.render_exam_pdf(
                generated_model, 
                job.project_id, 
                new_artifact_id
            )
            if binary_metadata and binary_metadata.get("storage_path"):
                logger.info(f"[GenerateHandler] Exam PDF uploaded to R2: {binary_metadata['storage_path']}")
                logger.info(f"[GenerateHandler] Artifact {new_artifact_id} has binary - ready for COMPLETED status")
            else:
                # HARD FAIL: Exam without PDF is not usable
                raise RuntimeError(
                    f"Exam binary rendering failed. "
                    f"R2 available: {self.binary_renderer.r2_available}. "
                    f"Artifact {new_artifact_id} cannot be marked COMPLETED without binary."
                )
        
        elif target_type == "slides":
            logger.info(f"[GenerateHandler] Starting PPTX render for slides artifact {new_artifact_id}")
            binary_metadata = self.binary_renderer.render_slides_pptx(
                generated_model, 
                job.project_id, 
                new_artifact_id
            )
            if binary_metadata and binary_metadata.get("storage_path"):
                logger.info(f"[GenerateHandler] Slides PPTX uploaded to R2: {binary_metadata['storage_path']}")
                logger.info(f"[GenerateHandler] Artifact {new_artifact_id} has binary - ready for COMPLETED status")
            else:
                # HARD FAIL: Slides without PPTX is not usable
                raise RuntimeError(
                    f"Slides binary rendering failed. "
                    f"R2 available: {self.binary_renderer.r2_available}. "
                    f"Artifact {new_artifact_id} cannot be marked COMPLETED without binary."
                )
        
        # --- Build artifact content ---
        artifact_content = {
            "kind": "generated",
            "data": generated_model.model_dump(),
        }
        
        # Add binary metadata if available
        if binary_metadata:
            artifact_content["binary"] = binary_metadata
        
        artifact = ArtifactPayload(
            id=new_artifact_id,
            project_id=job.project_id,
            type=target_type,
            content=artifact_content
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
