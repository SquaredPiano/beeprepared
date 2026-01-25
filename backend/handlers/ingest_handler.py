"""
IngestHandler: Bridge between DB Jobs and the Ingestion → Core pipeline.

INVARIANTS:
- Produces exactly 2 artifacts: Source + Knowledge Core
- Produces exactly 1 edge: Source → Core
- Knowledge Core is the ONLY artifact that summarizes raw sources
- All downstream generation derives from Knowledge Core
"""

import uuid
import logging
from typing import Dict, Any

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle, ArtifactPayload, EdgePayload
from backend.handlers.base import JobHandler

from backend.core.ingest import IngestionService
from backend.core.extraction import ExtractionService
from backend.core.text_cleaning import TextCleaningService as TextCleaner
from backend.core.knowledge_core import KnowledgeCoreService

logger = logging.getLogger(__name__)


# ============================================================================
# FROZEN CONTRACTS
# ============================================================================

# Allowed generation map (what can generate what)
ALLOWED_GENERATIONS: Dict[str, set] = {
    "knowledge_core": {"quiz", "exam", "notes", "slides", "flashcards"},
    "quiz": {"flashcards"},
    "exam": set(),
    "slides": set(),
    "notes": set(),
    "flashcards": set(),
}

# Source types that IngestHandler can process
VALID_SOURCE_TYPES = {"youtube", "audio", "video", "pdf", "pptx", "md"}


class IngestHandler(JobHandler):
    """
    Handles 'ingest' job type.
    
    Input Payload (frozen):
    {
        "source_type": "youtube | audio | video | pdf | pptx | md",
        "source_ref": "url or file path",
        "original_name": "Lecture 1"
    }
    
    Output:
    - Artifact 1 (Source): kind=source, type=<source_type>
    - Artifact 2 (Core): kind=core, type=knowledge_core
    - Edge: Source → Core
    """

    def __init__(self):
        self.ingestor = IngestionService()
        self.extractor = ExtractionService()
        self.cleaner = TextCleaner()
        self.core_service = KnowledgeCoreService()

    async def run(self, job: JobModel) -> JobBundle:
        logger.info(f"[IngestHandler] Processing job {job.id}")
        
        payload = job.payload
        
        # --- Validate Payload ---
        source_type = payload.get("source_type")
        source_ref = payload.get("source_ref")
        original_name = payload.get("original_name", "Untitled")
        
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {source_type}. Must be one of {VALID_SOURCE_TYPES}")
        
        if not source_ref:
            raise ValueError("source_ref is required")
        
        # --- Step 1: Ingest (Upload to R2) ---
        logger.info(f"[IngestHandler] Step 1: Ingesting {source_type}...")
        
        # Dispatch to correct ingestor method
        if source_type == "youtube":
            ingest_result = self.ingestor.process_youtube(source_ref, str(job.project_id))
        elif source_type == "audio":
            ingest_result = self.ingestor.process_audio_upload(source_ref, str(job.project_id), original_name)
        elif source_type == "video":
            ingest_result = self.ingestor.process_video_upload(source_ref, str(job.project_id), original_name)
        elif source_type in {"pdf", "pptx", "md"}:
            ingest_result = self.ingestor.process_document(source_ref, str(job.project_id), original_name, source_type.upper())
        else:
            raise ValueError(f"Unhandled source_type: {source_type}")
        
        if ingest_result.get("status") == "FAILED":
            raise RuntimeError(f"Ingestion failed: {ingest_result}")
        
        r2_key = ingest_result.get("fileURL")
        logger.info(f"[IngestHandler] Ingested to R2: {r2_key}")
        
        # --- Step 2: Extract Text ---
        logger.info(f"[IngestHandler] Step 2: Extracting text...")
        text, extract_meta = self.extractor.extract_from_r2(r2_key)
        
        if len(text) < 50:
            raise RuntimeError(f"Extraction failed or text too short ({len(text)} chars)")
        
        logger.info(f"[IngestHandler] Extracted {len(text)} chars")
        
        # --- Step 3: Clean Text ---
        logger.info(f"[IngestHandler] Step 3: Cleaning text...")
        cleaned_text = self.cleaner.clean_with_gemini(text)
        logger.info(f"[IngestHandler] Cleaned text: {len(cleaned_text)} chars")
        
        # --- Step 4: Generate Knowledge Core ---
        logger.info(f"[IngestHandler] Step 4: Generating Knowledge Core...")
        knowledge_core = self.core_service.generate_knowledge_core(cleaned_text)
        
        if not knowledge_core:
            raise RuntimeError("Knowledge Core generation failed")
        
        # --- KC-5 Enforcement: Validate no empty required fields ---
        REQUIRED_FIELDS = [
            ("title", knowledge_core.title),
            ("summary", knowledge_core.summary),
            ("concepts", knowledge_core.concepts),
            ("section_hierarchy", knowledge_core.section_hierarchy),
            ("notes", knowledge_core.notes),
            ("definitions", knowledge_core.definitions),
            ("examples", knowledge_core.examples),
            ("key_facts", knowledge_core.key_facts),
        ]
        
        for name, field in REQUIRED_FIELDS:
            if not field:
                raise ValueError(f"KC-5 Violation: Empty or missing '{name}' in KnowledgeCore")
        
        # --- KC-4 Enforcement: Validate plain text only (field-by-field) ---
        FORBIDDEN_LATEX = ['$', '\\(', '\\)', '\\[', '\\]']
        FORBIDDEN_MD = ['#', '**', '*', '`']  # Spec requires single * too
        FORBIDDEN = FORBIDDEN_LATEX + FORBIDDEN_MD
        
        def _assert_plain_text(value: str, field_path: str):
            """Raise if value contains forbidden LaTeX or Markdown tokens."""
            # Type guard: fail loudly on non-strings (KC-5 philosophy)
            if not isinstance(value, str):
                raise ValueError(
                    f"KC-4 Violation: Non-string value in KnowledgeCore.{field_path}"
                )
            for token in FORBIDDEN:
                if token in value:
                    raise ValueError(
                        f"KC-4 Violation: Forbidden token '{token}' in KnowledgeCore.{field_path}"
                    )

        
        # Validate top-level fields
        _assert_plain_text(knowledge_core.title, "title")
        _assert_plain_text(knowledge_core.summary, "summary")
        
        # Validate nested fields
        for i, c in enumerate(knowledge_core.concepts):
            _assert_plain_text(c.name, f"concepts[{i}].name")
            _assert_plain_text(c.description, f"concepts[{i}].description")
        
        for i, s in enumerate(knowledge_core.section_hierarchy):
            _assert_plain_text(s.title, f"section_hierarchy[{i}].title")
            _assert_plain_text(s.summary, f"section_hierarchy[{i}].summary")
            for j, sub in enumerate(s.subsections):
                _assert_plain_text(sub.title, f"section_hierarchy[{i}].subsections[{j}].title")
                _assert_plain_text(sub.summary, f"section_hierarchy[{i}].subsections[{j}].summary")
        
        for i, n in enumerate(knowledge_core.notes):
            _assert_plain_text(n.heading, f"notes[{i}].heading")
            for j, bullet in enumerate(n.bullets):
                _assert_plain_text(bullet, f"notes[{i}].bullets[{j}]")
        
        for i, d in enumerate(knowledge_core.definitions):
            _assert_plain_text(d.term, f"definitions[{i}].term")
            _assert_plain_text(d.definition, f"definitions[{i}].definition")
            _assert_plain_text(d.context, f"definitions[{i}].context")
        
        for i, e in enumerate(knowledge_core.examples):
            _assert_plain_text(e.description, f"examples[{i}].description")
            _assert_plain_text(e.relevance, f"examples[{i}].relevance")
        
        for i, kf in enumerate(knowledge_core.key_facts):
            _assert_plain_text(kf.fact, f"key_facts[{i}].fact")
            _assert_plain_text(kf.category, f"key_facts[{i}].category")
        
        logger.info(f"[IngestHandler] Knowledge Core generated and validated: {knowledge_core.title}")


        
        # --- Step 5: Build JobBundle ---
        source_artifact_id = uuid.uuid4()
        core_artifact_id = uuid.uuid4()
        
        # Artifact 1: Source
        source_artifact = ArtifactPayload(
            id=source_artifact_id,
            project_id=job.project_id,
            type=source_type,  # "youtube", "audio", "video", "pdf", etc.
            content={
                "kind": "source",
                "r2_key": r2_key,
                "original_name": original_name,
                "ingest_meta": ingest_result,
            }
        )
        
        # Artifact 2: Knowledge Core
        core_artifact = ArtifactPayload(
            id=core_artifact_id,
            project_id=job.project_id,
            type="knowledge_core",
            content={
                "kind": "core",
                "core": knowledge_core.model_dump(),
            }
        )
        
        # NOTE: No edge from Source → Core
        # DB invariant: knowledge_core must have indegree=0 (it's the epistemic root)
        # Provenance is tracked via created_by_job_id, not edges
        # Edges are for downstream generation: Core → Quiz, Core → Notes, etc.
        
        bundle = JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[source_artifact, core_artifact],
            edges=[],  # No edges for ingest - Core is root
            renderings=[],
            result={
                "status": "success",
                "source_artifact_id": str(source_artifact_id),
                "core_artifact_id": str(core_artifact_id),
            }
        )
        
        logger.info(f"[IngestHandler] Job {job.id} completed. Created 2 artifacts, 0 edges.")
        return bundle
