"""Reads the text out of whatever the user uploaded."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pypdf

from backend.pipeline.media import Transcriber
from backend.services.files import FileStore, get_file_store

logger = logging.getLogger(__name__)

AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg", ".wma", ".aac"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"})


class ExtractionError(RuntimeError):
    """A source file could not be read."""


@dataclass
class Extracted:
    """The text of a source, plus what was learned about it on the way through."""

    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class DocumentReader:
    """Pulls text out of documents that already contain it."""

    def read(self, path: Path) -> Extracted:
        readers: Dict[str, Callable[[Path], Extracted]] = {
            ".pdf": self._pdf,
            ".pptx": self._pptx,
            ".ppt": self._pptx,
            ".docx": self._docx,
        }
        reader = readers.get(path.suffix.lower(), self._plain_text)
        return reader(path)

    def _pdf(self, path: Path) -> Extracted:
        pages = []
        for number, page in enumerate(pypdf.PdfReader(str(path)).pages, start=1):
            text = page.extract_text()
            if text and text.strip():
                pages.append(f"--- Page {number} ---\n{text}")

        if not pages:
            raise ExtractionError(
                f"{path.name} has no extractable text. Scanned PDFs need OCR first."
            )
        return Extracted("\n\n".join(pages), {"page_count": len(pages)})

    def _pptx(self, path: Path) -> Extracted:
        from pptx import Presentation

        presentation = Presentation(str(path))
        slides = []

        for number, slide in enumerate(presentation.slides, start=1):
            lines = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text.strip():
                    lines.append(shape.text.strip())
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                        if cells:
                            lines.append(" | ".join(cells))

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    lines.append(f"[Speaker notes: {notes}]")

            if lines:
                slides.append(f"--- Slide {number} ---\n" + "\n".join(lines))

        return Extracted("\n\n".join(slides), {"slide_count": len(presentation.slides)})

    def _docx(self, path: Path) -> Extracted:
        from docx import Document

        document = Document(str(path))
        blocks = [para.text for para in document.paragraphs if para.text.strip()]

        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    blocks.append(" | ".join(cells))

        return Extracted("\n\n".join(blocks), {"paragraph_count": len(document.paragraphs)})

    def _plain_text(self, path: Path) -> Extracted:
        return Extracted(path.read_text(encoding="utf-8", errors="ignore"), {})


class ExtractionService:
    """
    Routes a source file to the reader that understands it.

    Documents are read directly; recordings go through transcription first.
    """

    def __init__(
        self,
        reader: Optional[DocumentReader] = None,
        transcriber: Optional[Transcriber] = None,
        store: Optional[FileStore] = None,
    ) -> None:
        self._reader = reader or DocumentReader()
        self._transcriber = transcriber or Transcriber()
        self._store = store or get_file_store()

    async def extract(self, file_path: str) -> Extracted:
        """Read a local file and return its text."""
        path = Path(file_path)
        if not path.exists():
            raise ExtractionError(f"File not found: {file_path}")

        suffix = path.suffix.lower()
        logger.info("Extracting %s (%s)", path.name, suffix or "no suffix")

        if suffix in AUDIO_SUFFIXES or suffix in VIDEO_SUFFIXES:
            result = Extracted(await self._transcriber.transcribe(str(path)), {"transcribed": True})
        else:
            result = self._reader.read(path)

        result.metadata.update({
            "source": path.name,
            "suffix": suffix,
            "char_count": len(result.text),
            "word_count": result.word_count,
        })
        logger.info("Extracted %d words from %s", result.word_count, path.name)
        return result

    async def extract_stored(self, key: str) -> Extracted:
        """Read a file out of the store, extract it, then drop the local copy."""
        with tempfile.TemporaryDirectory() as workspace:
            local = Path(workspace) / Path(key).name
            self._store.copy_to(key, str(local))
            return await self.extract(str(local))
