"""
IngestHandler: raw source in, Knowledge Core out.

Pipeline: store the source, extract its text, clean the text, then distil it
into a ``KnowledgeCore`` - the single structured representation that every
downstream artifact is generated from.

Two invariants worth stating, because the database enforces them:

- Ingest produces exactly two artifacts: the **source** and the **core**.
- It produces **zero edges**. The Knowledge Core is the epistemic root of a
  project's graph (indegree 0); provenance back to the source file is tracked by
  ``created_by_job_id``, not by an edge. Edges mean "was generated from", and
  the core was not generated from anything inside the graph.

The core is also validated before it is allowed to become the root: an empty
field or stray LaTeX here would silently corrupt every artifact derived from it,
so it fails loudly at ingest instead.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from backend.core.extraction import ExtractionService
from backend.core.ingest import IngestionService
from backend.core.knowledge_core import KnowledgeCore, KnowledgeCoreService
from backend.core.text_cleaning import TextCleaningService
from backend.handlers.base import JobHandler
from backend.models.jobs import JobModel
from backend.models.protocol import ArtifactPayload, JobBundle

logger = logging.getLogger(__name__)

VALID_SOURCE_TYPES = {"youtube", "audio", "video", "pdf", "pptx", "md"}

# Below this, extraction produced nothing usable - a scanned PDF with no text
# layer, a silent recording, an empty file.
MIN_EXTRACTED_CHARS = 50

# The Knowledge Core is plain text by contract. Markup here leaks into every
# generated artifact and breaks the LaTeX rendering downstream.
FORBIDDEN_TOKENS = ("$", "\\(", "\\)", "\\[", "\\]")


class CoreValidationError(ValueError):
    """Raised when a generated Knowledge Core violates its contract."""


class IngestHandler(JobHandler):
    """
    Handles ``ingest`` jobs.

    Payload::

        {
            "source_type": "youtube | audio | video | pdf | pptx | md",
            "source_ref":  "<url or local file path>",
            "original_name": "Lecture 1"
        }
    """

    def __init__(
        self,
        ingestor: Optional[IngestionService] = None,
        extractor: Optional[ExtractionService] = None,
        cleaner: Optional[TextCleaningService] = None,
        core_service: Optional[KnowledgeCoreService] = None,
    ):
        self.ingestor = ingestor or IngestionService()
        self.extractor = extractor or ExtractionService()
        self.cleaner = cleaner or TextCleaningService()
        self.core_service = core_service or KnowledgeCoreService()

    # -- steps --------------------------------------------------------------

    def _store_source(self, source_type: str, source_ref: str, name: str, project_id) -> Dict[str, Any]:
        """Normalise and store the source; returns ingest metadata."""
        if source_type == "youtube":
            return self.ingestor.process_youtube(source_ref, str(project_id))
        if source_type == "audio":
            return self.ingestor.process_audio_upload(source_ref, str(project_id), name)
        if source_type == "video":
            return self.ingestor.process_video_upload(source_ref, str(project_id), name)
        if source_type in {"pdf", "pptx", "md"}:
            return self.ingestor.process_document(source_ref, str(project_id), name, source_type.upper())
        raise ValueError(f"Unhandled source_type: {source_type}")

    def _extract(self, storage_key: str, source_ref: str) -> Tuple[str, dict]:
        """
        Read text out of the stored object.

        Local uploads are read straight off disk when they are still there - the
        round trip through storage is pure overhead in that case.
        """
        if source_ref and os.path.exists(source_ref):
            return self.extractor.extract(source_ref)
        return self.extractor.extract_from_storage(storage_key)

    # -- validation ---------------------------------------------------------

    @staticmethod
    def validate_core(core: KnowledgeCore) -> None:
        """
        Refuse a core that would poison everything derived from it.

        Two rules: no required collection may be empty, and no text field may
        contain LaTeX. Both are cheap to check here and expensive to discover
        three artifacts later.
        """
        required = [
            ("title", core.title), ("summary", core.summary),
            ("concepts", core.concepts), ("section_hierarchy", core.section_hierarchy),
            ("notes", core.notes), ("definitions", core.definitions),
            ("examples", core.examples), ("key_facts", core.key_facts),
        ]
        empty = [name for name, value in required if not value]
        if empty:
            raise CoreValidationError(
                f"Knowledge Core is missing required content: {', '.join(empty)}"
            )

        for path, value in IngestHandler._text_fields(core):
            if not isinstance(value, str):
                raise CoreValidationError(f"Knowledge Core field {path} is not a string")
            for token in FORBIDDEN_TOKENS:
                if token in value:
                    raise CoreValidationError(
                        f"Knowledge Core field {path} contains forbidden markup '{token}'. "
                        "The core must be plain text."
                    )

    @staticmethod
    def _text_fields(core: KnowledgeCore) -> List[Tuple[str, Any]]:
        """Every string in the core, paired with a path for the error message."""
        fields: List[Tuple[str, Any]] = [("title", core.title), ("summary", core.summary)]

        for i, concept in enumerate(core.concepts):
            fields += [(f"concepts[{i}].name", concept.name),
                       (f"concepts[{i}].description", concept.description)]

        for i, section in enumerate(core.section_hierarchy):
            fields += [(f"section_hierarchy[{i}].title", section.title),
                       (f"section_hierarchy[{i}].summary", section.summary)]
            for j, sub in enumerate(section.subsections):
                fields += [(f"section_hierarchy[{i}].subsections[{j}].title", sub.title),
                           (f"section_hierarchy[{i}].subsections[{j}].summary", sub.summary)]

        for i, note in enumerate(core.notes):
            fields.append((f"notes[{i}].heading", note.heading))
            fields += [(f"notes[{i}].bullets[{j}]", bullet) for j, bullet in enumerate(note.bullets)]

        for i, definition in enumerate(core.definitions):
            fields += [(f"definitions[{i}].term", definition.term),
                       (f"definitions[{i}].definition", definition.definition),
                       (f"definitions[{i}].context", definition.context)]

        for i, example in enumerate(core.examples):
            fields += [(f"examples[{i}].description", example.description),
                       (f"examples[{i}].relevance", example.relevance)]

        for i, fact in enumerate(core.key_facts):
            fields += [(f"key_facts[{i}].fact", fact.fact),
                       (f"key_facts[{i}].category", fact.category)]

        return fields

    # -- run ----------------------------------------------------------------

    async def run(self, job: JobModel) -> JobBundle:
        payload = job.payload
        source_type = payload.get("source_type")
        source_ref = payload.get("source_ref")
        original_name = payload.get("original_name", "Untitled")

        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type}'. Expected one of: "
                f"{', '.join(sorted(VALID_SOURCE_TYPES))}"
            )
        if not source_ref:
            raise ValueError("source_ref is required")

        logger.info("[IngestHandler] job=%s type=%s name=%s", job.id, source_type, original_name)

        # 1. Store
        self.report("storing source", 10)
        ingest_result = self._store_source(source_type, source_ref, original_name, job.project_id)
        if ingest_result.get("status") == "FAILED":
            raise RuntimeError(f"Ingestion failed for {original_name}: {ingest_result}")
        storage_key = ingest_result.get("fileURL")

        # 2. Extract
        self.report("extracting text", 30)
        text, extract_meta = self._extract(storage_key, source_ref)
        if len(text or "") < MIN_EXTRACTED_CHARS:
            raise RuntimeError(
                f"Extracted only {len(text or '')} characters from {original_name}. "
                "The file may be empty, image-only, or an unsupported format."
            )
        logger.info("[IngestHandler] extracted %d chars", len(text))

        # 3. Clean
        self.report("cleaning transcript", 50)
        cleaned = await self.cleaner.clean_text(text)

        # 4. Distil
        self.report("building knowledge core", 70)
        core = await self.core_service.generate_knowledge_core(cleaned)
        if not core:
            raise RuntimeError("Knowledge Core generation returned nothing")

        self.report("validating knowledge core", 90)
        self.validate_core(core)
        logger.info("[IngestHandler] core ready: %s", core.title)

        # 5. Bundle
        source_artifact_id = uuid.uuid4()
        core_artifact_id = uuid.uuid4()

        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[
                ArtifactPayload(
                    id=source_artifact_id,
                    project_id=job.project_id,
                    type=source_type,
                    content={
                        "kind": "source",
                        "storage_key": storage_key,
                        # Kept for artifacts written before storage was pluggable.
                        "r2_key": storage_key,
                        "original_name": original_name,
                        "ingest_meta": ingest_result,
                        "extract_meta": extract_meta,
                        "extracted_chars": len(text),
                    },
                ),
                ArtifactPayload(
                    id=core_artifact_id,
                    project_id=job.project_id,
                    type="knowledge_core",
                    content={
                        "kind": "core",
                        "title": core.title,
                        "core": core.model_dump(),
                    },
                ),
            ],
            # No edges: the core is the graph's root. See the module docstring.
            edges=[],
            renderings=[],
            result={
                "status": "success",
                "source_artifact_id": str(source_artifact_id),
                "core_artifact_id": str(core_artifact_id),
                "title": core.title,
            },
        )
