"""
GenerateHandler: turns one or more source artifacts into a new study artifact.

Responsibilities, in order:

1. **Resolve sources.** Every incoming edge of a generator node is a source. They
   are fetched in one batch query and each is reduced to a ``KnowledgeCore`` -
   either directly (it is a core), by reading its content (it is a generated
   artifact being chained), or by walking up to its parent core.
2. **Merge.** One source passes straight through. Several go through
   ``CoreMerger``'s map/reduce so multiple lectures become one context.
3. **Generate.** ``ArtifactGenerator`` produces and validates the typed model.
4. **Render.** Exams and slides also get a PDF/PPTX written to object storage.
5. **Bundle.** One artifact plus one ``derived_from`` edge per source, committed
   atomically by the job runner.

Step 5 is what makes the canvas a real DAG: N inputs produce N provenance edges,
so the graph the user drew is the graph that gets stored.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from backend.core.knowledge_core import Concept, KeyFact, KnowledgeCore
from backend.handlers.base import JobHandler
from backend.models.artifacts import GENERATED_ARTIFACT_TYPES
from backend.models.jobs import JobModel
from backend.models.protocol import ArtifactPayload, EdgePayload, JobBundle
from backend.services.binary_renderer import BinaryRenderer
from backend.services.core_merger import CoreMerger
from backend.services.db_interface import DBInterface
from backend.services.generators import ArtifactGenerator

logger = logging.getLogger(__name__)


# ============================================================================
# Contracts
# ============================================================================

# What may be generated from what. A knowledge core can produce anything; a
# generated artifact can be chained into any other type except itself, because
# "make a quiz from this quiz" is a refine operation, not a generate one.
_ALL_TARGETS = set(GENERATED_ARTIFACT_TYPES)

ALLOWED_GENERATIONS: Dict[str, set] = {
    "knowledge_core": set(_ALL_TARGETS),
    **{source: _ALL_TARGETS - {source} for source in _ALL_TARGETS},
}

# Artifact types whose content can be flattened back into text for chaining.
CHAINABLE_SOURCE_TYPES = set(_ALL_TARGETS) | {"text", "flat_text", "transcription"}


class SourceResolutionError(ValueError):
    """Raised when a source artifact cannot be reduced to a Knowledge Core."""


class GenerateHandler(JobHandler):
    """Handles ``generate`` jobs."""

    def __init__(
        self,
        db: Optional[DBInterface] = None,
        generator: Optional[ArtifactGenerator] = None,
        merger: Optional[CoreMerger] = None,
        renderer: Optional[BinaryRenderer] = None,
    ):
        self.db = db or DBInterface()
        self.generator = generator or ArtifactGenerator()
        self.core_merger = merger or CoreMerger()
        self.binary_renderer = renderer or BinaryRenderer()

    # -- payload ------------------------------------------------------------

    @staticmethod
    def _source_ids(payload: Dict[str, Any]) -> List[str]:
        """Accept both the multi-source field and the original single-source one."""
        ids = payload.get("source_artifact_ids") or []
        if not ids and payload.get("source_artifact_id"):
            ids = [payload["source_artifact_id"]]
        # Preserve order, drop duplicates: wiring the same source into a node
        # twice should not double the provenance edges.
        seen: set = set()
        return [str(i) for i in ids if str(i) not in seen and not seen.add(str(i))]

    @staticmethod
    def _parse_uuid(value: Any) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError) as exc:
            raise SourceResolutionError(f"Not a valid artifact id: {value!r}") from exc

    # -- source resolution --------------------------------------------------

    def _resolve_core(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """Reduce one artifact to the Knowledge Core that should drive generation."""
        source_type = artifact.get("type")
        content = artifact.get("content") or {}

        # 1. It is already a core.
        if source_type == "knowledge_core":
            core_data = content.get("core")
            if core_data:
                return KnowledgeCore(**core_data)

        # 2. It is a generated artifact being chained. Its own content is the
        #    context - not its ancestor's - otherwise "notes -> quiz" would
        #    quietly regenerate from the original lecture and ignore the notes.
        if source_type in CHAINABLE_SOURCE_TYPES:
            text = self._flatten(artifact)
            if text and text.strip():
                logger.info("Chaining: using the content of %s as a synthetic core", source_type)
                return KnowledgeCore(
                    title=f"Source: {content.get('title') or artifact.get('alias') or source_type}",
                    summary=text,
                    concepts=[], key_facts=[], section_hierarchy=[],
                    notes=[], definitions=[], examples=[],
                )

        # 3. Fall back to the parent core (a source file node, say).
        for edge in self.db.get_all_parent_edges(artifact["id"]):
            parent = self.db.get_artifact(edge.get("parent_artifact_id"))
            if parent and parent.get("type") == "knowledge_core":
                core_data = (parent.get("content") or {}).get("core")
                if core_data:
                    return KnowledgeCore(**core_data)

        raise SourceResolutionError(
            f"Could not resolve a Knowledge Core for artifact {artifact['id']} (type={source_type})"
        )

    @staticmethod
    def _flatten(artifact: Dict[str, Any]) -> Optional[str]:
        """Render an artifact's content as plain text, for chaining."""
        artifact_type = artifact.get("type")
        content = artifact.get("content") or {}
        data = content.get("data") or {}
        lines: List[str] = []

        if artifact_type in {"notes", "study_guide"}:
            return data.get("body") or data.get("markdown") or data.get("content")

        if artifact_type in {"text", "flat_text", "transcription"}:
            return data.get("text") or content.get("text")

        if artifact_type == "quiz":
            lines.append("Quiz content:")
            for question in data.get("questions", []):
                options = question.get("options") or []
                index = question.get("correct_answer_index", 0)
                answer = options[index] if 0 <= index < len(options) else ""
                lines.append(f"Q: {question.get('text', '')}")
                lines.append(f"Answer: {answer}")
                lines.append(f"Why: {question.get('explanation', '')}")

        elif artifact_type == "flashcards":
            lines.append("Flashcard content:")
            for card in data.get("cards") or data.get("flashcards", []):
                lines.append(f"Front: {card.get('front', '')}")
                lines.append(f"Back: {card.get('back', '')}")

        elif artifact_type == "exam":
            lines.append("Exam content:")
            for question in data.get("questions", []):
                lines.append(f"Q: {question.get('text', '')} [{question.get('type', '')}]")
                lines.append(f"Model answer: {question.get('model_answer', '')}")
                lines.append(f"Grading: {question.get('grading_notes', '')}")

        elif artifact_type == "slides":
            lines.append("Slide content:")
            for slide in data.get("slides", []):
                lines.append(f"# {slide.get('heading', '')}")
                lines.append(slide.get("main_idea", ""))
                lines.extend(f"- {point}" for point in slide.get("bullet_points", []))
                lines.append(f"Speaker notes: {slide.get('speaker_notes', '')}")

        elif artifact_type == "cheatsheet":
            lines.append("Cheat sheet content:")
            for section in data.get("sections", []):
                lines.append(f"## {section.get('heading', '')}")
                lines.extend(f"- {entry}" for entry in section.get("entries", []))

        elif artifact_type == "mindmap":
            def walk(node: Dict[str, Any], depth: int = 0) -> None:
                lines.append(f"{'  ' * depth}- {node.get('label', '')}: {node.get('detail') or ''}")
                for child in node.get("children", []):
                    walk(child, depth + 1)

            lines.append("Mind map content:")
            root = data.get("root")
            if isinstance(root, dict):
                walk(root)

        return "\n".join(lines) if lines else None

    def resolve_sources(self, source_ids: List[str], target_type: str) -> List[KnowledgeCore]:
        """Fetch every source in one query and reduce each to a Knowledge Core."""
        artifacts = self.db.get_artifacts(source_ids)
        by_id = {str(artifact["id"]): artifact for artifact in artifacts}

        missing = [sid for sid in source_ids if sid not in by_id]
        if missing:
            raise SourceResolutionError(f"Source artifacts not found: {', '.join(missing)}")

        cores: List[KnowledgeCore] = []
        for source_id in source_ids:
            artifact = by_id[source_id]
            source_type = artifact.get("type")

            allowed = ALLOWED_GENERATIONS.get(source_type)
            if allowed is not None and target_type not in allowed:
                raise SourceResolutionError(
                    f"Cannot generate '{target_type}' from '{source_type}'. "
                    f"Allowed from '{source_type}': {', '.join(sorted(allowed)) or 'nothing'}"
                )

            cores.append(self._resolve_core(artifact))
        return cores

    # -- context ------------------------------------------------------------

    async def build_context(self, cores: List[KnowledgeCore]) -> KnowledgeCore:
        """Collapse N cores into the single core the generator will read."""
        if not cores:
            raise SourceResolutionError("No Knowledge Cores resolved")
        if len(cores) == 1:
            return cores[0]

        # Synthetic cores (produced by chaining) carry their whole payload in
        # `summary` and have no structured concepts. Summarising them would
        # throw away the very content the user chained in, so concatenate.
        if all(not core.concepts and core.summary for core in cores):
            logger.info("Concatenating %d chained text sources", len(cores))
            return KnowledgeCore(
                title=f"Combined: {', '.join(core.title for core in cores)}",
                summary="\n\n".join(f"### Content from {c.title}:\n{c.summary}" for c in cores),
                concepts=[], key_facts=[], section_hierarchy=[],
                notes=[], definitions=[], examples=[],
            )

        logger.info("Hierarchical merge of %d Knowledge Cores", len(cores))
        combined = await self.core_merger.merge_cores(cores)
        if combined.conflict_notes:
            logger.warning("Sources disagree: %s", combined.conflict_notes)

        return KnowledgeCore(
            title=f"Combined: {', '.join(combined.source_titles)}",
            summary=combined.unified_summary,
            concepts=[Concept(name=c, description="", importance_score=7) for c in combined.all_concepts],
            key_facts=[KeyFact(fact=f, category="Combined") for f in combined.all_facts],
            section_hierarchy=[], notes=[], definitions=[], examples=[],
        )

    # -- run ----------------------------------------------------------------

    async def run(self, job: JobModel) -> JobBundle:
        payload = job.payload
        source_ids = self._source_ids(payload)
        target_type = payload.get("target_type")
        instructions = payload.get("instructions")

        if not source_ids:
            raise ValueError("source_artifact_ids (or source_artifact_id) is required")
        if not target_type:
            raise ValueError("target_type is required")
        if target_type not in GENERATED_ARTIFACT_TYPES:
            raise ValueError(
                f"Unknown target_type '{target_type}'. "
                f"Expected one of: {', '.join(sorted(GENERATED_ARTIFACT_TYPES))}"
            )

        logger.info(
            "[GenerateHandler] job=%s target=%s sources=%d%s",
            job.id, target_type, len(source_ids), " (steered)" if instructions else "",
        )

        cores = self.resolve_sources(source_ids, target_type)
        context = await self.build_context(cores)
        model = await self.generator.generate(target_type, context, instructions)

        return self.build_bundle(job, source_ids, target_type, model, instructions)

    # -- bundle -------------------------------------------------------------

    def build_bundle(
        self,
        job: JobModel,
        source_ids: List[str],
        target_type: str,
        model,
        instructions: Optional[str] = None,
    ) -> JobBundle:
        """Assemble the artifact, its binary rendering and one edge per source."""
        artifact_id = uuid.uuid4()

        content: Dict[str, Any] = {
            "kind": "generated",
            "target_type": target_type,
            "data": model.model_dump(),
        }
        if instructions:
            content["instructions"] = instructions

        binary = self.binary_renderer.render(target_type, model, job.project_id, artifact_id)
        if binary:
            content["binary"] = binary

        artifact = ArtifactPayload(
            id=artifact_id,
            project_id=job.project_id,
            type=target_type,
            content=content,
        )

        # One provenance edge per source. This is the multi-input DAG made durable.
        edges = [
            EdgePayload(
                parent_artifact_id=self._parse_uuid(source_id),
                child_artifact_id=artifact_id,
                relationship_type="derived_from",
                project_id=job.project_id,
            )
            for source_id in source_ids
        ]

        return JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[artifact],
            edges=edges,
            renderings=[],
            result={
                "status": "success",
                "artifact_id": str(artifact_id),
                "artifact_type": target_type,
                "source_count": len(source_ids),
            },
        )
