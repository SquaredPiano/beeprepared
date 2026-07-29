"""Turns an uploaded source into the knowledge core a project is built on."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.handlers.base import JobHandler
from backend.models.artifacts import SOURCE_TYPES
from backend.models.graph import ArtifactPayload, JobBundle
from backend.models.jobs import IngestPayload, JobModel
from backend.pipeline.cleaning import TRANSCRIBED_SOURCE_TYPES, TextCleaner
from backend.pipeline.extraction import ExtractionService
from backend.pipeline.ingestion import IngestionService, StoredSource
from backend.pipeline.knowledge import KnowledgeCore, KnowledgeExtractor
from backend.services.uploads import UploadStaging

logger = logging.getLogger(__name__)

MIN_EXTRACTED_CHARS = 50
FORBIDDEN_MARKUP = ("$", "\\(", "\\)", "\\[", "\\]")


class CoreValidationError(ValueError):
    """A knowledge core broke the contract every artifact below it depends on."""


class KnowledgeCoreValidator:
    """
    Checks a core before it becomes the root of a project's graph.

    We only insist on the fields every generator reads. A ten-minute recording
    might genuinely have no worked examples in it, and throwing out a usable
    extraction over one empty optional list costs the user their upload for
    nothing.

    Markup gets rejected wherever it shows up. The core is plain text by
    contract, so one stray piece of LaTeX in here leaks into every artifact
    built on top of it.
    """

    REQUIRED_FIELDS = ("title", "summary", "concepts", "key_facts")

    def validate(self, core: KnowledgeCore) -> None:
        """Raise if the core is unusable, or if there's markup anywhere in it."""
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
    Stores a source, pulls its text out, cleans it, and distils a knowledge core.

    Ingest makes exactly two artifacts and no edges. The core is the root of the
    project's graph. Provenance back to the source file rides on
    `created_by_job_id` and not on an edge, because the core wasn't derived from
    anything that was already in the graph.

    This is also where a staged upload's life ends. The upload endpoint puts a
    copy in the file store, which keeps a big recording out of memory and lets
    any process on the data volume run the job. Ingest is the last thing to read
    that copy, so ingest is what releases it. Leave it there and every file the
    user ingests is stored twice for as long as the machine is up.
    """

    def __init__(
        self,
        ingestion: Optional[IngestionService] = None,
        extraction: Optional[ExtractionService] = None,
        cleaner: Optional[TextCleaner] = None,
        knowledge: Optional[KnowledgeExtractor] = None,
        validator: Optional[KnowledgeCoreValidator] = None,
        staging: Optional[UploadStaging] = None,
    ) -> None:
        self._ingestion = ingestion or IngestionService()
        self._extraction = extraction or ExtractionService()
        self._cleaner = cleaner or TextCleaner()
        self._knowledge = knowledge or KnowledgeExtractor()
        self._validator = validator or KnowledgeCoreValidator()
        self._staging = staging or UploadStaging()

    async def run(self, job: JobModel) -> JobBundle:
        payload = IngestPayload(**job.payload)

        if payload.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"Unknown source type '{payload.source_type}'. "
                f"Expected one of: {', '.join(sorted(SOURCE_TYPES))}"
            )

        logger.info("Ingesting %s (%s)", payload.original_name, payload.source_type)
        project_id = str(job.project_id)

        self.report("storing source", 10)
        staged = self._staged_upload_path(payload, project_id)
        source = self._store(payload, project_id, staged)

        self.report("reading source", 30)
        extracted = await self._read(source, staged)
        if len(extracted.text) < MIN_EXTRACTED_CHARS:
            raise RuntimeError(
                f"Only {len(extracted.text)} characters came out of {payload.original_name}. "
                "The file may be empty, image-only, or an unsupported format."
            )

        self.report("cleaning text", 50)
        cleaned = await self._clean(extracted.text, payload.source_type)

        self.report("building knowledge core", 70)
        core = await self._knowledge.extract(cleaned)

        self.report("validating knowledge core", 90)
        self._validator.validate(core)
        logger.info("Knowledge core ready: %s", core.title)

        self._release_staged_upload(payload, project_id)
        return self._bundle(job, payload, source, extracted.metadata, core)

    def _staged_upload_path(self, payload: IngestPayload, project_id: str) -> Optional[Path]:
        """
        Find this job's staged upload, or return nothing if it has none to read.

        The payload names the upload by storage key. A key resolves to the same
        bytes in every process that can reach the data volume, and we check it
        against the project the job belongs to. A filesystem path does neither.
        It means nothing in another container, and a caller who gets to supply
        one can point it at any file the server can open.
        """
        if payload.source_type == "youtube":
            return None

        if not payload.staged_key:
            raise ValueError(
                f"A {payload.source_type} source is ingested from an upload, so its payload "
                "must carry the staged_key that the project's upload endpoint returned."
            )

        return self._staging.path_for(payload.staged_key, project_id)

    def _store(
        self,
        payload: IngestPayload,
        project_id: str,
        staged: Optional[Path],
    ) -> StoredSource:
        """
        Put a durable copy of the source into the file store.

        This runs first for a reason. Until it comes back, the staged upload is
        the only copy of the file that exists.
        """
        if staged is not None:
            return self._ingestion.store_upload(
                str(staged), project_id, payload.original_name, payload.source_type
            )

        if not payload.source_ref:
            raise ValueError("A youtube source needs a source_ref naming the video to fetch")

        return self._ingestion.store_youtube(payload.source_ref, project_id)

    async def _clean(self, text: str, source_type: str) -> str:
        """
        Pick the cleaning rules this text's source can actually survive.

        The transcript rules delete every parenthesised and bracketed span.
        That's the right call for `(laughs)` and `[inaudible]`, and the wrong
        call for `f(x)`, `[0,1]`, `O(n log n)` and anything with a bracketed
        citation in it. Point them at a document and nothing complains. You get
        a knowledge core, and every artifact under it, quietly built on mangled
        text. So anything we don't know was transcribed is treated as a
        document, which keeps a source type someone adds later on the safe side
        until they decide otherwise.
        """
        if source_type in TRANSCRIBED_SOURCE_TYPES:
            return await self._cleaner.clean_transcript(text)
        return await self._cleaner.clean(text)

    async def _read(self, source: StoredSource, staged: Optional[Path]):
        """
        Read the source's text, out of the staged upload while there still is one.

        `extract_stored` has to copy the object back out of the store before it
        can read it, and a staged upload is already a local file holding exactly
        those bytes. A downloaded source never had a staged copy, so that one
        gets read from the store.
        """
        if staged is not None:
            return await self._extraction.extract(str(staged))
        return await self._extraction.extract_stored(source.key)

    def _release_staged_upload(self, payload: IngestPayload, project_id: str) -> None:
        """
        Free the staging slot now that the source has a durable copy and a core.

        This only runs when the job succeeded. The staged upload is the only copy
        of what the caller sent us, so deleting it on failure turned every
        transient failure into a permanent one. The retry found nothing to read
        and died for a reason that had nothing to do with why the first attempt
        died. A job that runs out of attempts does leave one file sitting in the
        project's staging folder, and that's the cheaper of the two costs.

        Nothing else ever gets deleted here. A staged key names a slot this
        project's own upload endpoint wrote, `UploadStaging` refuses a key of any
        other shape, and source material the caller supplied themselves can't be
        addressed this way at all.
        """
        if payload.staged_key:
            self._staging.discard(payload.staged_key, project_id)

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
