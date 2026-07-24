"""Turns generated artifacts into downloadable files."""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

from backend.services.exports.exam_pdf import ExamPdfRenderer
from backend.services.exports.slides_pptx import SlidesPptxRenderer
from backend.services.files import FileStore, get_file_store

logger = logging.getLogger(__name__)

MIME_TYPES = {
    "pdf": "application/pdf",
    "tex": "application/x-tex",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "md": "text/markdown",
}

MARKDOWN_TYPES = frozenset({"notes", "study_guide", "cheatsheet"})

EXAM_ARTEFACTS = (".pdf", ".tex", ".aux", ".log")


@dataclass(frozen=True)
class Export:
    """Where a rendered file lives and what it is."""

    format: str
    storage_key: str
    mime_type: str
    size_bytes: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "storage_path": self.storage_key,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }


class ExportService:
    """
    Renders an artifact to its natural file format, when it has one.

    Rendering never fails a job: an artifact is defined by its content and the
    file is a convenience, so a missing LaTeX install costs the download rather
    than the whole generation.
    """

    def __init__(
        self,
        store: Optional[FileStore] = None,
        exam_renderer: Optional[ExamPdfRenderer] = None,
        slides_renderer: Optional[SlidesPptxRenderer] = None,
    ) -> None:
        self._store = store or get_file_store()
        self._exam = exam_renderer or ExamPdfRenderer(Path(tempfile.gettempdir()))
        self._slides = slides_renderer or SlidesPptxRenderer()

    def export(
        self,
        artifact_type: str,
        model: BaseModel,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
    ) -> Optional[Export]:
        """Render `model` and return where it was stored, or None if it has no file form."""
        try:
            if artifact_type == "exam":
                return self._export_exam(model, project_id, artifact_id)
            if artifact_type == "slides":
                return self._export_slides(model, project_id, artifact_id)
            if artifact_type in MARKDOWN_TYPES:
                return self._export_markdown(model, project_id, artifact_id)
        except Exception as error:
            logger.warning("Export failed for %s (%s); keeping the artifact", artifact_type, error)
        return None

    def _export_exam(self, exam, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Optional[Export]:
        """
        Render into the scratch directory and clear every intermediate afterwards.

        The cleanup covers rendering itself, not just storage: a LaTeX run that
        dies partway still leaves its source and logs behind, and nothing else
        ever revisits that directory.
        """
        stem = self._exam.output_dir / f"exam_{artifact_id}"

        try:
            rendered = self._exam.render(exam, stem.name)
            if rendered is None:
                return None
            return self._store_file(rendered, project_id, artifact_id, rendered.suffix.lstrip("."))
        finally:
            self._cleanup(*(stem.with_suffix(suffix) for suffix in EXAM_ARTEFACTS))

    def _export_slides(self, deck, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Export:
        with tempfile.TemporaryDirectory() as workspace:
            path = self._slides.render(deck, Path(workspace) / f"{artifact_id}.pptx")
            return self._store_file(path, project_id, artifact_id, "pptx")

    def _export_markdown(self, model, project_id: uuid.UUID, artifact_id: uuid.UUID) -> Optional[Export]:
        body = self._to_markdown(model)
        if not body:
            return None

        key = f"{project_id}/exports/{artifact_id}.md"
        self._store.put_bytes(body.encode("utf-8"), key)
        return Export("md", key, MIME_TYPES["md"], self._store.size_of(key))

    def _store_file(
        self,
        path: Path,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        extension: str,
    ) -> Export:
        key = f"{project_id}/exports/{artifact_id}.{extension}"
        self._store.put(str(path), key)
        size = self._store.size_of(key)
        logger.info("Exported %s (%d bytes)", key, size)
        return Export(extension, key, MIME_TYPES.get(extension, "application/octet-stream"), size)

    @staticmethod
    def _to_markdown(model: BaseModel) -> Optional[str]:
        data = model.model_dump()

        if data.get("body"):
            parts = [str(data["body"])]
            if data.get("checklist"):
                parts.append("\n## Self-check\n")
                parts.extend(f"- [ ] {item}" for item in data["checklist"])
            return "\n".join(parts)

        if data.get("sections"):
            lines = [f"# {data.get('title', 'Cheat sheet')}\n"]
            for section in data["sections"]:
                lines.append(f"## {section.get('heading', '')}\n")
                lines.extend(f"- {entry}" for entry in section.get("entries", []))
                lines.append("")
            return "\n".join(lines)

        return None

    @staticmethod
    def _cleanup(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove %s", path)
