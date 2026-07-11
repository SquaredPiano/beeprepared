"""Rebuilds an existing artifact against a plain-English request."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel

from backend.handlers.base import JobHandler
from backend.handlers.sources import ArtifactFlattener, SourceResolutionError, SourceResolver
from backend.models.artifacts import GENERATED_TYPES
from backend.models.graph import ArtifactPayload, EdgePayload, JobBundle, as_uuid
from backend.models.jobs import JobModel, RefinePayload
from backend.pipeline.knowledge import KnowledgeCore
from backend.services.database import Database, get_database
from backend.services.exports import ExportService
from backend.services.generators import ArtifactGenerator

logger = logging.getLogger(__name__)

MAX_INSTRUCTION_LENGTH = 4_000


class RefineHandler(JobHandler):
    """
    Regenerates an artifact with the user's request and the current version in view.

    Refinement appends a new artifact linked back to the old one rather than
    editing in place, so every revision stays visible and nothing already
    exported changes underneath the user.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        resolver: Optional[SourceResolver] = None,
        generator: Optional[ArtifactGenerator] = None,
        exporter: Optional[ExportService] = None,
        flattener: Optional[ArtifactFlattener] = None,
    ) -> None:
        self._database = database or get_database()
        self._resolver = resolver or SourceResolver(self._database)
        self._generator = generator or ArtifactGenerator()
        self._exporter = exporter or ExportService()
        self._flattener = flattener or ArtifactFlattener()

    async def run(self, job: JobModel) -> JobBundle:
        payload = RefinePayload(**job.payload)
        instructions = payload.instructions.strip()

        if not instructions:
            raise ValueError("instructions is required: refinement needs something to act on")
        if len(instructions) > MAX_INSTRUCTION_LENGTH:
            raise ValueError(f"instructions must be under {MAX_INSTRUCTION_LENGTH} characters")

        artifact = self._database.get_artifact(payload.source_artifact_id)
        if not artifact:
            raise SourceResolutionError(f"Artifact not found: {payload.source_artifact_id}")

        target_type = payload.target_type or artifact.get("type")
        if target_type not in GENERATED_TYPES:
            raise ValueError(
                f"'{target_type}' cannot be refined. "
                f"Refinable types: {', '.join(sorted(GENERATED_TYPES))}"
            )

        logger.info("Refining %s artifact %s", target_type, artifact["id"])

        self.report("loading source material", 25)
        context = self._revision_context(artifact)

        self.report(f"revising {target_type}", 50)
        model = await self._generator.generate(target_type, context, instructions)

        self.report("saving revision", 90)
        return self._bundle(job, str(artifact["id"]), target_type, model, instructions)

    def _revision_context(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """
        Build the core to revise from.

        The current artifact is folded in so the model revises this version;
        without it, "make it harder" produces a different artifact rather than a
        harder version of this one.
        """
        base = self._resolver.to_core(artifact)
        current = self._flattener.flatten(artifact)
        if not current:
            return base

        return base.model_copy(update={
            "summary": (
                f"{base.summary}\n\n"
                "--- CURRENT VERSION OF THE ARTIFACT (revise this) ---\n"
                f"{current}"
            )
        })

    def _bundle(
        self,
        job: JobModel,
        source_id: str,
        target_type: str,
        model: BaseModel,
        instructions: str,
    ) -> JobBundle:
        artifact_id = uuid.uuid4()

        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
            "refined_from": source_id,
            "instructions": instructions,
        }

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
            edges=[EdgePayload(
                parent_artifact_id=as_uuid(source_id),
                child_artifact_id=artifact_id,
                project_id=job.project_id,
            )],
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "refined_from": source_id,
            },
        )
