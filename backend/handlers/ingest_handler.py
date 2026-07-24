"""Turns an uploaded source into the knowledge core a project is built on."""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.handlers.base import JobHandler
from backend.models.artifacts import SOURCE_TYPES
from backend.models.graph import ArtifactPayload, JobBundle
from backend.models.jobs import IngestPayload, JobModel
from backend.pipeline.cleaning import TextCleaner
from backend.pipeline.extraction import ExtractionService
from backend.pipeline.ingestion import IngestionService, StoredSource
from backend.pipeline.knowledge import KnowledgeCore, KnowledgeExtractor

logger = logging.getLogger(__name__)

MIN_EXTRACTED_CHARS = 50
FORBIDDEN_MARKUP = ("$", "\\(", "\\)", "\\[", "\\]")


class CoreValidationError(ValueError):
    """A knowledge core violated the contract every artifact depends on."""


class KnowledgeCoreValidator:
    """
    Checks a core before it becomes the root of a project's graph.

    Only the fields every generator reads are required. A short recording may
    genuinely contain no worked examples, and rejecting the whole core over an
    empty optional list would discard an otherwise usable extraction.

    Markup is rejected everywhere: the core is plain text by contract, and stray
    LaTeX here corrupts every artifact derived from it.
    """

    REQUIRED_FIELDS = ("title", "summary", "concepts", "key_facts")

    def validate(self, core: KnowledgeCore) -> None:
        """Raise if the core is unusable or contains markup."""
        self._require_content(core)
        self._require_plain_text(core)

    def _require_content(self, core: KnowledgeCore) -> None:
        missing = [name for name in self.REQUIRED_FIELDS if not getattr(core, name)]
        if missing:
            raise CoreValidationError(
                f"Knowledge core has no {', '.join(missing)}. "
                "The source may be too short or contain no teachable content."
            )

    def _require_plain_text(self, core: KnowledgeCore) -> None:
        for path, value in self._text_fields(core):
            if not isinstance(value, str):
                raise CoreValidationError(f"Knowledge core field {path} is not text")
            for token in FORBIDDEN_MARKUP:
                if token in value:
                    raise CoreValidationError(
                        f"Knowledge core field {path} contains markup '{token}'. "
                        "The core must be plain text."
                    )

    @staticmethod
    def _text_fields(core: KnowledgeCore) -> List[Tuple[str, Any]]:
        fields: List[Tuple[str, Any]] = [("title", core.title), ("summary", core.summary)]

        for index, concept in enumerate(core.concepts):
            fields += [(f"concepts[{index}].name", concept.name),
                       (f"concepts[{index}].description", concept.description)]

        for index, section in enumerate(core.section_hierarchy):
            fields += [(f"section_hierarchy[{index}].title", section.title),
                       (f"section_hierarchy[{index}].summary", section.summary)]
            for position, subsection in enumerate(section.subsections):
                prefix = f"section_hierarchy[{index}].subsections[{position}]"
                fields += [(f"{prefix}.title", subsection.title),
                           (f"{prefix}.summary", subsection.summary)]

        for index, note in enumerate(core.notes):
            fields.append((f"notes[{index}].heading", note.heading))
            fields += [(f"notes[{index}].bullets[{position}]", bullet)
                       for position, bullet in enumerate(note.bullets)]

        for index, definition in enumerate(core.definitions):
            fields += [(f"definitions[{index}].term", definition.term),
                       (f"definitions[{index}].definition", definition.definition),
                       (f"definitions[{index}].context", definition.context)]

        for index, example in enumerate(core.examples):
            fields += [(f"examples[{index}].description", example.description),
                       (f"examples[{index}].relevance", example.relevance)]

        for index, fact in enumerate(core.key_facts):
            fields += [(f"key_facts[{index}].fact", fact.fact),
                       (f"key_facts[{index}].category", fact.category)]

        return fields


class IngestHandler(JobHandler):
    """
    Stores a source, extracts its text, cleans it, and distils a knowledge core.

    Ingest produces exactly two artifacts and no edges. The core is the root of
    the project's graph, and provenance back to the source file is carried by
    `created_by_job_id` rather than by an edge, because the core was not derived
    from anything already in the graph.

    Ingest is also the end of the buffered upload's life. The upload endpoint
    stages a copy on disk so a large recording never has to be held in memory,
    and this is the last reader of it; leaving it behind would duplicate every
    ingested file for as long as the machine stays up.
    """

    def __init__(
        self,
        ingestion: Optional[IngestionService] = None,
        extraction: Optional[ExtractionService] = None,
        cleaner: Optional[TextCleaner] = None,
        knowledge: Optional[KnowledgeExtractor] = None,
        validator: Optional[KnowledgeCoreValidator] = None,
    ) -> None:
        self._ingestion = ingestion or IngestionService()
        self._extraction = extraction or ExtractionService()
        self._cleaner = cleaner or TextCleaner()
        self._knowledge = knowledge or KnowledgeExtractor()
        self._validator = validator or KnowledgeCoreValidator()

    async def run(self, job: JobModel) -> JobBundle:
        payload = IngestPayload(**job.payload)

        if payload.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"Unknown source type '{payload.source_type}'. "
                f"Expected one of: {', '.join(sorted(SOURCE_TYPES))}"
            )

        logger.info("Ingesting %s (%s)", payload.original_name, payload.source_type)

        self.report("storing source", 10)
        source = self._store(payload, str(job.project_id))

        try:
            self.report("reading source", 30)
            extracted = await self._read(source, payload.source_ref)
            if len(extracted.text) < MIN_EXTRACTED_CHARS:
                raise RuntimeError(
                    f"Only {len(extracted.text)} characters came out of {payload.original_name}. "
                    "The file may be empty, image-only, or an unsupported format."
                )

            self.report("cleaning text", 50)
            cleaned = await self._cleaner.clean(extracted.text)

            self.report("building knowledge core", 70)
            core = await self._knowledge.extract(cleaned)

            self.report("validating knowledge core", 90)
            self._validator.validate(core)
            logger.info("Knowledge core ready: %s", core.title)
        finally:
            self._discard_staged_upload(payload.source_ref)

        return self._bundle(job, payload, source, extracted.metadata, core)

    def _store(self, payload: IngestPayload, project_id: str) -> StoredSource:
        """
        Put a durable copy of the source in the file store.

        Deliberately outside the cleanup block: until this returns, the staged
        upload is the only copy there is.
        """
        if payload.source_type == "youtube":
            return self._ingestion.store_youtube(payload.source_ref, project_id)

        if not Path(payload.source_ref).is_file():
            raise RuntimeError(
                f"No readable file at {payload.source_ref}. A buffered upload is deleted "
                "once its ingest finishes, so a finished job cannot be re-run; upload again."
            )

        return self._ingestion.store_upload(
            payload.source_ref, project_id, payload.original_name, payload.source_type
        )

    async def _read(self, source: StoredSource, original_path: str):
        if original_path and Path(original_path).exists():
            return await self._extraction.extract(original_path)
        return await self._extraction.extract_stored(source.key)

    @staticmethod
    def _discard_staged_upload(source_ref: str) -> None:
        """
        Delete the upload the API buffered for this job, if that is what this is.

        The upload endpoint stages through `tempfile.NamedTemporaryFile`, so a
        staged upload is a regular file sitting directly in the system temp
        directory under the temp-file prefix. A YouTube URL is not a path, and a
        caller naming source material of their own is naming something outside
        that shape; deleting the wrong file here is far worse than leaking one.
        """
        path = Path(source_ref)
        if not path.name.startswith(tempfile.gettempprefix()):
            return
        if path.parent != Path(tempfile.gettempdir()):
            return
        if not path.is_file():
            return

        path.unlink(missing_ok=True)
        logger.info("Discarded the staged upload %s", path.name)

    @staticmethod
    def _bundle(
        job: JobModel,
        payload: IngestPayload,
        source: StoredSource,
        metadata: dict,
        core: KnowledgeCore,
    ) -> JobBundle:
        source_id, core_id = uuid.uuid4(), uuid.uuid4()

        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[
                ArtifactPayload(
                    id=source_id,
                    project_id=job.project_id,
                    type=payload.source_type,
                    content={
                        "kind": "source",
                        "storage_key": source.key,
                        "original_name": source.original_name,
                        "size_bytes": source.size_bytes,
                        "extraction": metadata,
                    },
                ),
                ArtifactPayload(
                    id=core_id,
                    project_id=job.project_id,
                    type="knowledge_core",
                    content={"kind": "core", "title": core.title, "core": core.model_dump()},
                ),
            ],
            edges=[],
            result={
                "status": "success",
                "source_artifact_id": str(source_id),
                "core_artifact_id": str(core_id),
                "title": core.title,
            },
        )
