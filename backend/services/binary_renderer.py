"""
Binary rendering: turning a generated artifact into a downloadable file.

Two things changed here from the original implementation:

- **Storage is pluggable.** Rendering writes through ``ObjectStore``, so a PDF
  lands on local disk or in R2 depending on what is configured. Previously a
  missing R2 credential meant exams and slides could not be generated at all.
- **Rendering never fails a job.** A study artifact is defined by its JSON
  content; the PDF is a convenience. If LaTeX is missing or PowerPoint
  generation throws, the artifact is still committed - just without a binary.

``render()`` dispatches on target type; everything else here is format detail.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from typing import Any, Callable, Dict, Optional

from backend.models.artifacts import FinalExamModel, SlidesModel
from backend.services.pdf_renderer import PDFRenderer
from backend.services.storage import ObjectStore, get_object_store

logger = logging.getLogger(__name__)

MIME_PDF = "application/pdf"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_MARKDOWN = "text/markdown"


class BinaryRenderer:
    """Renders artifacts to files and stores them via the configured object store."""

    def __init__(self, store: Optional[ObjectStore] = None):
        self.store = store or get_object_store()
        self.pdf_renderer = PDFRenderer(output_dir=tempfile.gettempdir())

    # -- dispatch -----------------------------------------------------------

    def render(
        self,
        target_type: str,
        model: Any,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
    ) -> Optional[Dict[str, Any]]:
        """
        Render ``model`` to its natural file format, if it has one.

        Returns binary metadata to attach to the artifact's content, or ``None``
        when the type has no binary form or rendering failed.
        """
        renderers: Dict[str, Callable[[Any, uuid.UUID, uuid.UUID], Optional[Dict[str, Any]]]] = {
            "exam": self.render_exam_pdf,
            "slides": self.render_slides_pptx,
            "notes": self.render_markdown,
            "study_guide": self.render_markdown,
            "cheatsheet": self.render_markdown,
        }
        renderer = renderers.get(target_type)
        if renderer is None:
            return None

        try:
            return renderer(model, project_id, artifact_id)
        except Exception as exc:
            # Deliberately swallowed: see the module docstring. The artifact is
            # still valid without its binary, and failing the job would lose it.
            logger.warning("Binary rendering failed for %s (%s); artifact kept without a binary",
                           target_type, exc, exc_info=True)
            return None

    # -- storage ------------------------------------------------------------

    def _store(self, local_path: str, key: str, mime_type: str, fmt: str) -> Dict[str, Any]:
        size = os.path.getsize(local_path)
        self.store.put_file(local_path, key, mime_type)
        logger.info("Stored %s rendering: %s (%d bytes, backend=%s)",
                    fmt, key, size, self.store.backend_name)
        return {
            "format": fmt,
            "storage_path": key,
            "mime_type": mime_type,
            "size_bytes": size,
            "backend": self.store.backend_name,
        }

    @staticmethod
    def _cleanup(*paths: str) -> None:
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                logger.debug("Temp cleanup failed for %s: %s", path, exc)

    # -- markdown -----------------------------------------------------------

    def render_markdown(
        self, model: Any, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Write a Markdown export. Cheap, dependency-free, and always available."""
        body = self._as_markdown(model)
        if not body:
            return None

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp.write(body)
            path = tmp.name
        try:
            key = f"{project_id}/artifacts/{artifact_id}.md"
            return self._store(path, key, MIME_MARKDOWN, "md")
        finally:
            self._cleanup(path)

    @staticmethod
    def _as_markdown(model: Any) -> Optional[str]:
        data = model.model_dump() if hasattr(model, "model_dump") else dict(model)

        if data.get("body"):
            parts = [str(data["body"])]
            if data.get("checklist"):
                parts.append("\n## Self-check\n")
                parts.extend(f"- [ ] {item}" for item in data["checklist"])
            return "\n".join(parts)

        if data.get("sections"):
            lines = [f"# {data.get('title', 'Cheat Sheet')}\n"]
            for section in data["sections"]:
                lines.append(f"## {section.get('heading', '')}\n")
                lines.extend(f"- {entry}" for entry in section.get("entries", []))
                lines.append("")
            return "\n".join(lines)

        return None

    # -- exam PDF -----------------------------------------------------------

    def render_exam_pdf(
        self, exam: FinalExamModel, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Typeset the exam with LaTeX and store the PDF."""
        filename = f"exam_{artifact_id}"
        self.pdf_renderer.render_exam(exam, filename=filename)

        pdf_path = os.path.join(self.pdf_renderer.output_dir, f"{filename}.pdf")
        tex_path = os.path.join(self.pdf_renderer.output_dir, f"{filename}.tex")

        if not os.path.exists(pdf_path):
            # pdflatex is not installed in every environment; the .tex source is
            # still worth keeping so the exam can be typeset elsewhere.
            if os.path.exists(tex_path):
                logger.info("pdflatex unavailable; storing the LaTeX source instead")
                try:
                    key = f"{project_id}/artifacts/{artifact_id}.tex"
                    return self._store(tex_path, key, "application/x-tex", "tex")
                finally:
                    self._cleanup(tex_path)
            logger.warning("Exam rendering produced neither a PDF nor a .tex file")
            return None

        try:
            key = f"{project_id}/artifacts/{artifact_id}.pdf"
            return self._store(pdf_path, key, MIME_PDF, "pdf")
        finally:
            self._cleanup(pdf_path, tex_path)

    # -- slides PPTX --------------------------------------------------------

    @staticmethod
    def _validate_slides(slides: SlidesModel) -> None:
        if not slides.title:
            raise ValueError("Slides are missing a title")
        if not slides.slides:
            raise ValueError("Slides model contains no slides")
        for index, slide in enumerate(slides.slides):
            if not getattr(slide, "heading", None):
                raise ValueError(f"Slide {index} is missing a heading")
            bullets = getattr(slide, "bullet_points", None) or []
            if not isinstance(bullets, list):
                raise ValueError(f"Slide {index}: bullet_points must be a list")

    def render_slides_pptx(
        self, slides: SlidesModel, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Build a 16:9 deck with a title slide plus one slide per entry."""
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches, Pt

        self._validate_slides(slides)
        logger.info("Rendering %d slides for artifact %s", len(slides.slides), artifact_id)

        primary = RGBColor(0x1E, 0x1B, 0x4B)
        accent = RGBColor(0x63, 0x66, 0xF1)
        body_text = RGBColor(0x36, 0x36, 0x36)
        subtitle = RGBColor(0xCB, 0xD5, 0xE1)
        white = RGBColor(0xFF, 0xFF, 0xFF)

        presentation = Presentation()
        presentation.slide_width = Inches(13.333)
        presentation.slide_height = Inches(7.5)
        blank = presentation.slide_layouts[6]

        # --- title slide ---
        title_slide = presentation.slides.add_slide(blank)
        fill = title_slide.background.fill
        fill.solid()
        fill.fore_color.rgb = primary

        title_box = title_slide.shapes.add_textbox(Inches(0), Inches(2.25), Inches(13.333), Inches(1.5))
        title_box.text_frame.word_wrap = True
        paragraph = title_box.text_frame.paragraphs[0]
        paragraph.text = str(slides.title)
        paragraph.font.size = Pt(44)
        paragraph.font.bold = True
        paragraph.font.color.rgb = white
        paragraph.alignment = PP_ALIGN.CENTER

        sub_box = title_slide.shapes.add_textbox(Inches(0), Inches(3.75), Inches(13.333), Inches(0.6))
        sub_paragraph = sub_box.text_frame.paragraphs[0]
        sub_paragraph.text = f"Audience: {slides.audience_level or 'General'}"
        sub_paragraph.font.size = Pt(20)
        sub_paragraph.font.color.rgb = subtitle
        sub_paragraph.alignment = PP_ALIGN.CENTER

        bar = title_slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(7.1), Inches(13.333), Inches(0.4))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()

        # --- content slides ---
        for index, entry in enumerate(slides.slides):
            slide = presentation.slides.add_slide(blank)

            header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(1.0))
            header.fill.solid()
            header.fill.fore_color.rgb = RGBColor(0xF1, 0xF5, 0xF9)
            header.line.fill.background()

            heading_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.1), Inches(12.333), Inches(0.8))
            heading_box.text_frame.word_wrap = True
            heading = heading_box.text_frame.paragraphs[0]
            heading.text = str(entry.heading or f"Slide {index + 1}")
            heading.font.size = Pt(32)
            heading.font.bold = True
            heading.font.color.rgb = primary
            heading.alignment = PP_ALIGN.CENTER

            rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(1.1), Inches(11.333), Inches(0.03))
            rule.fill.solid()
            rule.fill.fore_color.rgb = accent
            rule.line.fill.background()

            if entry.main_idea:
                idea_box = slide.shapes.add_textbox(Inches(1.5), Inches(1.4), Inches(10.333), Inches(0.8))
                idea_box.text_frame.word_wrap = True
                idea = idea_box.text_frame.paragraphs[0]
                idea.text = str(entry.main_idea)
                idea.font.size = Pt(20)
                idea.font.italic = True
                idea.font.color.rgb = RGBColor(0x43, 0x38, 0xCA)
                idea.alignment = PP_ALIGN.CENTER

            if entry.bullet_points:
                bullet_box = slide.shapes.add_textbox(Inches(1.0), Inches(2.4), Inches(11.333), Inches(4.5))
                frame = bullet_box.text_frame
                frame.word_wrap = True
                for position, bullet in enumerate(entry.bullet_points):
                    paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
                    paragraph.text = f"{position + 1}. {bullet}"
                    paragraph.font.size = Pt(20)
                    paragraph.font.color.rgb = body_text
                    paragraph.space_after = Pt(16)

            if entry.speaker_notes:
                try:
                    slide.notes_slide.notes_text_frame.text = str(entry.speaker_notes)
                except Exception as exc:
                    logger.debug("Could not attach speaker notes to slide %d: %s", index + 1, exc)

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
            path = tmp.name
        try:
            presentation.save(path)
            key = f"{project_id}/artifacts/{artifact_id}.pptx"
            return self._store(path, key, MIME_PPTX, "pptx")
        finally:
            self._cleanup(path)
