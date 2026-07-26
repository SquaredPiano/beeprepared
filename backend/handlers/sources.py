"""Resolves the artifacts feeding a generator into knowledge cores."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.models.artifacts import GENERATED_TYPES
from backend.pipeline.knowledge import KnowledgeCore
from backend.services.database import Database

logger = logging.getLogger(__name__)

CHAINABLE_TYPES = GENERATED_TYPES | {"text", "flat_text", "transcription"}

ALLOWED_TARGETS: Dict[str, frozenset] = {
    "knowledge_core": GENERATED_TYPES,
    **{source: GENERATED_TYPES - {source} for source in GENERATED_TYPES},
}


class SourceResolutionError(ValueError):
    """A source artifact could not be reduced to a knowledge core."""


class ArtifactFlattener:
    """Renders a generated artifact back into plain text so it can be chained."""

    def flatten(self, artifact: Dict[str, Any]) -> Optional[str]:
        """Return a text view of the artifact's content, or None if it has none."""
        renderers = {
            "notes": self._body,
            "study_guide": self._body,
            "text": self._raw_text,
            "flat_text": self._raw_text,
            "transcription": self._raw_text,
            "quiz": self._quiz,
            "flashcards": self._flashcards,
            "exam": self._exam,
            "slides": self._slides,
            "cheatsheet": self._cheatsheet,
            "mindmap": self._mindmap,
        }
        renderer = renderers.get(artifact.get("type"))
        if renderer is None:
            return None

        data = (artifact.get("content") or {}).get("data") or {}
        return renderer(data) or None

    @staticmethod
    def _body(data: Dict[str, Any]) -> Optional[str]:
        return data.get("body") or data.get("markdown") or data.get("content")

    @staticmethod
    def _raw_text(data: Dict[str, Any]) -> Optional[str]:
        return data.get("text")

    @staticmethod
    def _quiz(data: Dict[str, Any]) -> str:
        lines = ["Quiz content:"]
        for question in data.get("questions", []):
            options = question.get("options") or []
            index = question.get("correct_answer_index", 0)
            answer = options[index] if 0 <= index < len(options) else ""
            lines += [
                f"Q: {question.get('text', '')}",
                f"Answer: {answer}",
                f"Why: {question.get('explanation', '')}",
            ]
        return "\n".join(lines)

    @staticmethod
    def _flashcards(data: Dict[str, Any]) -> str:
        lines = ["Flashcard content:"]
        for card in data.get("cards", []):
            lines += [f"Front: {card.get('front', '')}", f"Back: {card.get('back', '')}"]
        return "\n".join(lines)

    @staticmethod
    def _exam(data: Dict[str, Any]) -> str:
        lines = ["Exam content:"]
        for question in data.get("questions", []):
            lines += [
                f"Q: {question.get('text', '')} [{question.get('type', '')}]",
                f"Model answer: {question.get('model_answer', '')}",
                f"Grading: {question.get('grading_notes', '')}",
            ]
        return "\n".join(lines)

    @staticmethod
    def _slides(data: Dict[str, Any]) -> str:
        lines = ["Slide content:"]
        for slide in data.get("slides", []):
            lines += [f"# {slide.get('heading', '')}", slide.get("main_idea", "")]
            lines += [f"- {point}" for point in slide.get("bullet_points", [])]
            lines.append(f"Speaker notes: {slide.get('speaker_notes', '')}")
        return "\n".join(lines)

    @staticmethod
    def _cheatsheet(data: Dict[str, Any]) -> str:
        lines = ["Cheat sheet content:"]
        for section in data.get("sections", []):
            lines.append(f"## {section.get('heading', '')}")
            lines += [f"- {entry}" for entry in section.get("entries", [])]
        return "\n".join(lines)

    @staticmethod
    def _mindmap(data: Dict[str, Any]) -> str:
        lines = ["Mind map content:"]

        def walk(node: Dict[str, Any], depth: int = 0) -> None:
            lines.append(f"{'  ' * depth}- {node.get('label', '')}: {node.get('detail') or ''}")
            for child in node.get("children", []):
                walk(child, depth + 1)

        root = data.get("root")
        if isinstance(root, dict):
            walk(root)
        return "\n".join(lines)


class SourceResolver:
    """
    Reduces every artifact feeding a generator to a knowledge core.

    A generated artifact resolves to its own content rather than its ancestor's,
    so chaining notes into a quiz reads the notes instead of quietly
    regenerating from the original lecture.
    """

    def __init__(self, database: Database, flattener: Optional[ArtifactFlattener] = None) -> None:
        self._database = database
        self._flattener = flattener or ArtifactFlattener()

    def resolve(self, artifact_ids: List[str], target_type: str) -> List[KnowledgeCore]:
        """Fetch every source in one query and turn each into a knowledge core."""
        artifacts = {
            str(artifact["id"]): artifact
            for artifact in self._database.get_artifacts(artifact_ids)
        }

        missing = [artifact_id for artifact_id in artifact_ids if artifact_id not in artifacts]
        if missing:
            raise SourceResolutionError(f"Source artifacts not found: {', '.join(missing)}")

        for artifact_id in artifact_ids:
            self._check_transition(artifacts[artifact_id].get("type"), target_type)

        return [self.to_core(artifacts[artifact_id]) for artifact_id in artifact_ids]

    def to_core(self, artifact: Dict[str, Any]) -> KnowledgeCore:
        """Reduce a single artifact to the core that should drive generation."""
        source_type = artifact.get("type")
        content = artifact.get("content") or {}

        if source_type == "knowledge_core" and content.get("core"):
            return KnowledgeCore(**content["core"])

        if source_type in CHAINABLE_TYPES:
            text = self._flattener.flatten(artifact)
            if text and text.strip():
                logger.info("Chaining from a %s artifact", source_type)
                return self._synthetic(content.get("title") or source_type, text)

        parent_core = self._parent_core(artifact["id"])
        if parent_core is not None:
            return parent_core

        raise SourceResolutionError(
            f"Could not resolve a knowledge core for artifact {artifact['id']} ({source_type})"
        )

    def _parent_core(self, artifact_id: Any) -> Optional[KnowledgeCore]:
        for edge in self._database.get_parent_edges(artifact_id):
            parent = self._database.get_artifact(edge["parent_artifact_id"])
            if parent and parent.get("type") == "knowledge_core":
                core = (parent.get("content") or {}).get("core")
                if core:
                    return KnowledgeCore(**core)
        return None

    @staticmethod
    def _check_transition(source_type: Optional[str], target_type: str) -> None:
        allowed = ALLOWED_TARGETS.get(source_type)
        if allowed is not None and target_type not in allowed:
            raise SourceResolutionError(
                f"Cannot generate '{target_type}' from '{source_type}'. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )

    @staticmethod
    def _synthetic(title: str, text: str) -> KnowledgeCore:
        """Wrap chained text as a core so the generator has one uniform input."""
        return KnowledgeCore(
            title=f"Source: {title}",
            summary=text,
            concepts=[], section_hierarchy=[], notes=[],
            definitions=[], examples=[], key_facts=[],
        )
