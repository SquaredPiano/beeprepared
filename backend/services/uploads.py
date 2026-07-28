"""Where an accepted upload waits for the process that will ingest it."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from backend.services.files import FileStore, StorageError, get_file_store

logger = logging.getLogger(__name__)


class StagingError(StorageError):
    """A staged upload could not be addressed, or was never this project's."""


@dataclass(frozen=True)
class StagedUpload:
    """An upload waiting in the store, named by the key its ingest job carries."""

    key: str
    size_bytes: int


class UploadStaging:
    """
    Holds an accepted upload in the file store until its ingest job reads it.

    The process that accepts an upload and the process that runs the ingest are
    the same one only while the worker pool lives inside the API. Dispatch the
    job to Celery and they are separate containers whose one shared surface is
    the data volume the file store sits on, so an upload staged in the API's
    temp directory names a file the worker cannot open and a job that can never
    run. Staging goes through the store instead, and what the job carries is a
    storage key, which resolves to the same bytes in every one of those
    processes.

    A key is also safe to hand back to a caller and to accept from one: it names
    a slot inside one project's staging folder rather than a location on the
    server's filesystem, and every lookup is checked against the project asking.
    """

    FOLDER = "staged"

    def __init__(self, store: Optional[FileStore] = None) -> None:
        self._store = store or get_file_store()

    def stage(self, source_path: str, project_id: str, filename: Optional[str] = None) -> StagedUpload:
        """Take a received upload into the store under a key naming its project."""
        key = f"{project_id}/{self.FOLDER}/{uuid.uuid4()}{Path(filename or '').suffix}"
        self._store.put(source_path, key)
        return StagedUpload(key=key, size_bytes=self._store.size_of(key))

    def path_for(self, key: str, project_id: str) -> Path:
        """
        The staged upload's local path, for the project that staged it.

        An absent one gets its own message because it is the one an operator
        will meet: the slot is released the moment its ingest succeeds, so the
        second run of a job that already finished finds nothing.
        """
        self._require_staged_by(key, project_id)
        if not self._store.exists(key):
            raise StagingError(
                f"No staged upload at {key}. A staged upload is released once its ingest "
                "succeeds, so a job that already finished cannot be run again; upload again."
            )
        return self._store.open_path(key)

    def discard(self, key: str, project_id: str) -> None:
        """Release a staged upload once something durable has been made of it."""
        self._require_staged_by(key, project_id)
        self._store.delete(key)
        logger.info("Released the staged upload %s", key)

    @classmethod
    def _require_staged_by(cls, key: str, project_id: str) -> None:
        """
        Refuse a key that is not one this project staged.

        The key travels in the job payload, so wherever a caller can queue a job
        it is a caller-supplied string. Only the exact shape `stage` writes is
        accepted, which is what keeps a job from reading, or deleting, an
        export, another project's source, or anything reached by climbing out of
        the folder.
        """
        parts = PurePosixPath(key).parts
        if len(parts) != 3 or parts[:2] != (project_id, cls.FOLDER) or ".." in parts:
            raise StagingError(f"'{key}' is not an upload staged by project {project_id}")
