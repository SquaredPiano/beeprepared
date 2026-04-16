"""
RefineHandler: regenerate an existing artifact against a plain-English request.

This is what backs the assistant panel. Instead of re-rolling generation and
hoping for something better, the user says what they want changed - "make the
quiz harder", "focus on chapter 3", "shorter answers" - and the artifact is
rebuilt with that instruction plus the *current* artifact as context, so the
model revises rather than starting over.

Refinement produces a **new** artifact rather than mutating the old one, with a
``derived_from`` edge back to it. That preserves the graph's append-only
history: every revision is visible, and nothing the user already exported
changes underneath them.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from backend.core.knowledge_core import KnowledgeCore
from backend.handlers.base import JobHandler
from backend.handlers.generate_handler import GenerateHandler, SourceResolutionError
from backend.models.artifacts import GENERATED_ARTIFACT_TYPES
from backend.models.jobs import JobModel
from backend.models.protocol import ArtifactPayload, EdgePayload, JobBundle

logger = logging.getLogger(__name__)

MAX_INSTRUCTION_CHARS = 4000


class RefineHandler(JobHandler):
    """
    Handles ``refine`` jobs.

    Payload::

        {
            "source_artifact_id": "<artifact to revise>",
            "instructions": "make the questions harder and drop the true/false ones",
            "target_type": "quiz"   # optional; defaults to the source's own type
        }
    """

    def __init__(self, generate_handler: Optional[GenerateHandler] = None):
        # Refinement is generation with extra context, so it reuses the same
        # resolution, merging and bundling logic rather than duplicating it.
        self.generate = generate_handler or GenerateHandler()
        self.db = self.generate.db

    # -- context ------------------------------------------------------------

    def _revision_context(self, artifact: Dict[str, Any], base: KnowledgeCore) -> KnowledgeCore:
        """
        Build the core the model will revise from.

        The current artifact is folded into the summary so the model can see
        what it is changing. Without it, "make it harder" produces a different
        quiz rather than a harder version of this one.
        """
        current = self.generate._flatten(artifact)
        if not current:
            return base

        return KnowledgeCore(
            title=base.title,
            summary=(
                f"{base.summary}\n\n"
                "--- CURRENT VERSION OF THE ARTIFACT (revise this) ---\n"
                f"{current}"
            ),
            concepts=base.concepts,
            key_facts=base.key_facts,
            section_hierarchy=base.section_hierarchy,
            notes=base.notes,
            definitions=base.definitions,
            examples=base.examples,
        )

    # -- run ----------------------------------------------------------------

    async def run(self, job: JobModel) -> JobBundle:
        payload = job.payload
        source_id = payload.get("source_artifact_id") or payload.get("artifact_id")
        instructions = (payload.get("instructions") or "").strip()

        if not source_id:
            raise ValueError("source_artifact_id is required")
        if not instructions:
            raise ValueError("instructions is required - refinement needs something to act on")
        if len(instructions) > MAX_INSTRUCTION_CHARS:
            raise ValueError(f"instructions must be under {MAX_INSTRUCTION_CHARS} characters")

        artifact = self.db.get_artifact(source_id)
        if not artifact:
            raise SourceResolutionError(f"Artifact not found: {source_id}")

        target_type = payload.get("target_type") or artifact.get("type")
        if target_type not in GENERATED_ARTIFACT_TYPES:
            raise ValueError(
                f"'{target_type}' cannot be refined. Refinable types: "
                f"{', '.join(sorted(GENERATED_ARTIFACT_TYPES))}"
            )

        logger.info("[RefineHandler] job=%s artifact=%s target=%s", job.id, source_id, target_type)

        # Resolve the material the artifact was built from, then layer the
        # current version and the user's request on top.
        self.report("loading source material", 20)
        base = self._source_core(artifact)

        self.report("revising", 45)
        context = self._revision_context(artifact, base)
        model = await self.generate.generator.generate(target_type, context, instructions)

        self.report("saving revision", 90)
        return self._bundle(job, str(source_id), target_type, model, instructions)

    def _source_core(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """The Knowledge Core behind this artifact, or the artifact itself as one."""
        for edge in self.db.get_all_parent_edges(artifact["id"]):
            parent = self.db.get_artifact(edge.get("parent_artifact_id"))
            if parent and parent.get("type") == "knowledge_core":
                core_data = (parent.get("content") or {}).get("core")
                if core_data:
                    return KnowledgeCore(**core_data)
        return self.generate._resolve_core(artifact)

    def _bundle(
        self,
        job: JobModel,
        source_id: str,
        target_type: str,
        model,
        instructions: str,
    ) -> JobBundle:
        artifact_id = uuid.uuid4()
        binary = self.generate.binary_renderer.render(target_type, model, job.project_id, artifact_id)

        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
            "refined_from": str(source_id),
            "instructions": instructions,
        }
        if binary:
            content["binary"] = binary

        edges: List[EdgePayload] = [
            EdgePayload(
                parent_artifact_id=self.generate._parse_uuid(source_id),
                child_artifact_id=artifact_id,
                relationship_type="derived_from",
                project_id=job.project_id,
            )
        ]

        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[
                ArtifactPayload(
                    id=artifact_id,
                    project_id=job.project_id,
                    type=target_type,
                    content=content,
                )
            ],
            edges=edges,
            renderings=[],
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "refined_from": str(source_id),
            },
        )
