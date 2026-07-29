"""Holding area for an accepted upload, until the process that ingests it turns up."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from backend.services.files import FileStore, StorageError, get_file_store

logger = logging.getLogger(__name__)


class StagingError(StorageError):
    """We couldn't address a staged upload, or it was never this project's to read."""


@dataclass(frozen=True)
class StagedUpload:
    """An upload sitting in the store, named by the key its ingest job carries."""

    key: str
    size_bytes: int


class UploadStaging:
    """
    Keeps an accepted upload in the file store until its ingest job comes for it.

    The process that takes the upload and the process that runs the ingest are
    only the same process while the worker pool lives inside the API. Once the job
    goes out to Celery they're separate containers. The one thing they share is
    the data volume the file store sits on, and what they don't share is /tmp. So
    an upload staged in the API container's temp directory named a file the worker
    couldn't open, and the job it belonged to could never run. Upload simply never
    worked in the distributed setup.

    We stage through the file store instead. The job carries a storage key, and
    that key resolves to the same bytes whichever process picks it up.

    A key is also safe to hand out to a caller and to take back from one. It names
    a slot inside a single project's staging folder, not a location on the server's
    filesystem, and every lookup gets checked against the project doing the asking.
    """

    FOLDER = "staged"

    def __init__(self, store: Optional[FileStore] = None) -> None:
        self._store = store or get_file_store()

    def stage(self, source_path: str, project_id: str, filename: Optional[str] = None) -> StagedUpload:
        """Move a received upload into the store, under a key that names its project."""
        key = f"{project_id}/{self.FOLDER}/{uuid.uuid4()}{Path(filename or '').suffix}"
        self._store.put(source_path, key)
        return StagedUpload(key=key, size_bytes=self._store.size_of(key))

    def path_for(self, key: str, project_id: str) -> Path:
        """
        Local path of a staged upload, for the project that staged it.

        A missing one gets its own error message, because that's the case an
        operator will actually run into. We let the slot go the moment its ingest
        succeeds, so running a job that already finished finds nothing there.
        """
        self._require_staged_by(key, project_id)
        if not self._store.exists(key):
            raise StagingError(
                f"No staged upload at {key}. A staged upload is released once its ingest "
                "succeeds, so a job that already finished cannot be run again; upload again."
            )
        return self._store.open_path(key)

    def discard(self, key: str, project_id: str) -> None:
        """Let a staged upload go, once something durable has been made out of it."""
        self._require_staged_by(key, project_id)
        self._store.delete(key)
        logger.info("Released the staged upload %s", key)

    @classmethod
    def _require_staged_by(cls, key: str, project_id: str) -> None:
        """
        Refuse any key that this project didn't stage itself.

        The key rides along in the job payload, which means that anywhere a caller
        can queue a job, it's a string the caller chose. So we accept only the exact
        shape `stage` writes: three parts, the project id, then `staged`, then a
        name. That's what stops a job from reading or deleting an export, or another
        project's source file, or anything it could reach by climbing out of the
        folder with `..`.
        """
        parts = PurePosixPath(key).parts
        if len(parts) != 3 or parts[:2] != (project_id, cls.FOLDER) or ".." in parts:
            raise StagingError(f"'{key}' is not an upload staged by project {project_id}")
