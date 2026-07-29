"""Turns one or more source artifacts into a new study artifact."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from backend.handlers.base import JobHandler
from backend.handlers.sources import SourceResolver
from backend.models.artifacts import GENERATED_TYPES
from backend.models.graph import ArtifactPayload, EdgePayload, JobBundle, as_uuid
from backend.models.jobs import GeneratePayload, JobModel
from backend.pipeline.knowledge import Concept, KeyFact, KnowledgeCore
from backend.services.database import Database, get_database
from backend.services.exports import ExportService
from backend.services.generators import ArtifactGenerator
from backend.services.merger import CoreMerger

logger = logging.getLogger(__name__)


class GenerateHandler(JobHandler):
    """
    Resolves the sources, merges them into one context, generates, then exports.

    Every source turns into its own `derived_from` edge. An artifact built from
    three lectures gets three parent edges, because provenance here is a DAG and
    not a tree. The graph the user drew is the graph we store.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        resolver: Optional[SourceResolver] = None,
        generator: Optional[ArtifactGenerator] = None,
        merger: Optional[CoreMerger] = None,
        exporter: Optional[ExportService] = None,
    ) -> None:
        self._database = database or get_database()
        self._resolver = resolver or SourceResolver(self._database)
        self._generator = generator or ArtifactGenerator()
        self._merger = merger or CoreMerger()
        self._exporter = exporter or ExportService()

    async def run(self, job: JobModel) -> JobBundle:
        payload = GeneratePayload(**job.payload)
        source_ids = self._unique(payload.source_artifact_ids)

        if not source_ids:
            raise ValueError("source_artifact_ids is required")
        if payload.target_type not in GENERATED_TYPES:
            raise ValueError(
                f"Unknown target type '{payload.target_type}'. "
                f"Expected one of: {', '.join(sorted(GENERATED_TYPES))}"
            )

        logger.info(
            "Generating %s from %d source(s)%s",
            payload.target_type, len(source_ids), " with instructions" if payload.instructions else "",
        )

        self.report("loading sources", 20)
        cores = self._resolver.resolve(source_ids, payload.target_type)

        self.report("merging sources", 35)
        context = await self.build_context(cores)

        self.report(f"writing {payload.target_type}", 55)
        model = await self._generator.generate(payload.target_type, context, payload.instructions)

        self.report("saving", 90)
        return self.bundle(job, source_ids, payload.target_type, model, payload.instructions)

    async def build_context(self, cores: List[KnowledgeCore]) -> KnowledgeCore:
        """Collapse however many cores we have into the one the generator reads."""
        if not cores:
            raise ValueError("No knowledge cores to generate from")
        if len(cores) == 1:
            return cores[0]

        if all(not core.concepts and core.summary for core in cores):
            return self._concatenate(cores)

        combined = await self._merger.merge(cores)
        if combined.conflict_notes:
            logger.warning("Sources disagree: %s", combined.conflict_notes)

        return KnowledgeCore(
            title=f"Combined: {', '.join(combined.source_titles)}",
            summary=combined.unified_summary,
            concepts=[
                Concept(name=name, description="", importance_score=7)
                for name in combined.all_concepts
            ],
            key_facts=[KeyFact(fact=fact, category="Combined") for fact in combined.all_facts],
            section_hierarchy=[], notes=[], definitions=[], examples=[],
        )

    def bundle(
        self,
        job: JobModel,
        source_ids: List[str],
        target_type: str,
        model: BaseModel,
        instructions: Optional[str] = None,
    ) -> JobBundle:
        """Put together the artifact, its export, and one edge back to each source."""
        artifact_id = uuid.uuid4()

        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
        }
        if instructions:
            content["instructions"] = instructions

        export = self._exporter.export(target_type, model, job.project_id, artifact_id)
        if export:
            content["binary"] = export.as_dict()

        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[ArtifactPayload(
                id=artifact_id,
                project_id=job.project_id,
                type=target_type,
                content=content,
            )],
            edges=[
                EdgePayload(
                    parent_artifact_id=as_uuid(source_id),
                    child_artifact_id=artifact_id,
                    project_id=job.project_id,
                )
                for source_id in source_ids
            ],
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "source_count": len(source_ids),
            },
        )

    @staticmethod
    def _concatenate(cores: List[KnowledgeCore]) -> KnowledgeCore:
        """
        Glue chained sources together without summarising them.

        A chained core keeps its whole payload in `summary`. Compress that and we
        throw away the exact content the user wired into the canvas.
        """
        logger.info("Concatenating %d chained sources", len(cores))
        return KnowledgeCore(
            title=f"Combined: {', '.join(core.title for core in cores)}",
            summary="\n\n".join(f"### From {core.title}:\n{core.summary}" for core in cores),
            concepts=[], section_hierarchy=[], notes=[],
            definitions=[], examples=[], key_facts=[],
        )

    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        """The sources in the order they were wired up, with duplicates dropped."""
        return list(dict.fromkeys(str(value) for value in values))
