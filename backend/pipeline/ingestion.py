"""Brings source material into the system and files it in storage."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yt_dlp

from backend.services.files import FileStore, get_file_store

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """A source could not be fetched or stored."""


@dataclass(frozen=True)
class StoredSource:
    """Where a source ended up and what it was called."""

    key: str
    original_name: str
    source_type: str
    size_bytes: int


class IngestionService:
    """Stores uploads and downloads remote sources into the file store."""

    def __init__(self, store: Optional[FileStore] = None) -> None:
        self._store = store or get_file_store()

    def store_upload(self, file_path: str, project_id: str, original_name: str, source_type: str) -> StoredSource:
        """File an already-downloaded upload under its project."""
        suffix = Path(original_name).suffix or Path(file_path).suffix
        key = f"{project_id}/sources/{uuid.uuid4()}{suffix}"

        self._store.put(file_path, key)
        return StoredSource(
            key=key,
            original_name=original_name,
            source_type=source_type,
            size_bytes=self._store.size_of(key),
        )

    def store_youtube(self, url: str, project_id: str) -> StoredSource:
        """Download a video's audio track and file it under its project."""
        logger.info("Fetching YouTube audio: %s", url)

        with tempfile.TemporaryDirectory() as workspace:
            options = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(workspace, "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }

            try:
                with yt_dlp.YoutubeDL(options) as downloader:
                    info = downloader.extract_info(url, download=True)
                    downloaded = self._downloaded_path(downloader, info, Path(workspace))
                    title = info.get("title") or "YouTube video"
            except IngestionError:
                raise
            except Exception as error:
                raise IngestionError(f"Could not download {url}: {error}") from error

            key = f"{project_id}/sources/{uuid.uuid4()}{downloaded.suffix}"
            self._store.put(str(downloaded), key)

        return StoredSource(
            key=key,
            original_name=title,
            source_type="youtube",
            size_bytes=self._store.size_of(key),
        )

    @staticmethod
    def _downloaded_path(downloader: Any, info: Any, workspace: Path) -> Path:
        """
        The file yt-dlp actually left on disk.

        The name built from the output template is a prediction: format merging
        and post-processing rewrite the extension, so the path yt-dlp reports
        wins and the workspace itself is the last resort.
        """
        if not isinstance(info, dict):
            raise IngestionError("yt-dlp returned no metadata for this video")

        candidates = [
            download.get("filepath")
            for download in info.get("requested_downloads") or []
            if isinstance(download, dict)
        ]
        candidates.append(downloader.prepare_filename(info))

        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)

        produced = sorted(path for path in workspace.iterdir() if path.is_file())
        if not produced:
            raise IngestionError("yt-dlp reported success but wrote no file")
        return produced[0]
