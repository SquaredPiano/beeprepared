"""Content-addressed file storage with expiring, signed download links."""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import shutil
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from backend.core.config import get_settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """A file could not be written, read, or addressed."""


class FileStore:
    """
    Stores uploads and rendered exports beneath a single root directory.

    Download links are HMAC-signed over the key and expiry together, so a link
    cannot be extended or repointed by editing the query string.
    """

    def __init__(self, root: Optional[Path] = None, secret: Optional[str] = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.data_dir / "files").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._secret = (secret or settings.signing_secret).encode()

        logger.info("File store ready at %s", self.root)

    def put(self, source_path: str, key: str) -> str:
        """Copy a file into the store under `key` and return that key."""
        target = self.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        logger.info("Stored %s (%d bytes)", key, target.stat().st_size)
        return key

    def put_bytes(self, data: bytes, key: str) -> str:
        """Write raw bytes into the store under `key` and return that key."""
        target = self.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def copy_to(self, key: str, destination: str) -> str:
        """Copy a stored object out to a local path."""
        source = self.resolve(key)
        if not source.exists():
            raise StorageError(f"Object not found: {key}")
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    def delete(self, key: str) -> None:
        """Remove a stored object. A missing object is not an error."""
        self.resolve(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.resolve(key).exists()

    def size_of(self, key: str) -> int:
        return self.resolve(key).stat().st_size

    def resolve(self, key: str) -> Path:
        """Map a key to a path, refusing anything that escapes the store root."""
        cleaned = key.strip().lstrip("/")
        if not cleaned:
            raise StorageError("Empty storage key")

        candidate = (self.root / cleaned).resolve()
        if not candidate.is_relative_to(self.root):
            raise StorageError(f"Key escapes the storage root: {key}")
        return candidate

    def open_path(self, key: str) -> Path:
        """The path of a stored object, raising if it is not there."""
        path = self.resolve(key)
        if not path.exists():
            raise StorageError(f"Object not found: {key}")
        return path

    def signed_url(
        self,
        key: str,
        *,
        filename: str,
        inline: bool = False,
        expires_in: int = 3600,
    ) -> str:
        """A time-limited URL the browser can fetch directly."""
        expiry = int(time.time()) + expires_in
        disposition = "inline" if inline else "attachment"
        return (
            f"/api/files/{quote(key)}"
            f"?expires={expiry}&signature={self.sign(key, expiry)}"
            f"&disposition={disposition}&filename={quote(filename)}"
        )

    def sign(self, key: str, expiry: int) -> str:
        return hmac.new(self._secret, f"{key}:{expiry}".encode(), hashlib.sha256).hexdigest()

    def verify(self, key: str, expiry: int, signature: str) -> bool:
        """True when the signature matches and the link has not expired."""
        if expiry < int(time.time()):
            return False
        return hmac.compare_digest(self.sign(key, expiry), signature)

    @staticmethod
    def content_type(key: str) -> str:
        guessed, _ = mimetypes.guess_type(key)
        return guessed or "application/octet-stream"


_store: Optional[FileStore] = None
_lock = threading.Lock()


def get_file_store() -> FileStore:
    """The shared file store, opened on first use."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = FileStore()
    return _store


def reset_file_store() -> None:
    """Discard the cached store so the next call reopens it."""
    global _store
    with _lock:
        _store = None
