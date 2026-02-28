"""
Object storage abstraction.

The pipeline needs somewhere to put uploads and rendered binaries (PDF, PPTX).
Historically that was hard-wired to Cloudflare R2, which meant the whole
generation path failed closed the moment R2 credentials went stale.

This module puts a small interface in front of storage and ships two drivers:

- ``LocalObjectStore``  - files on disk, served back through ``/api/files``
- ``R2ObjectStore``     - S3-compatible Cloudflare R2

``get_object_store()`` picks R2 when it is fully configured and reachable, and
falls back to local disk otherwise. Callers never branch on the backend.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import shutil
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

_STORE: "ObjectStore | None" = None
_STORE_LOCK = threading.Lock()


class StorageError(RuntimeError):
    """Raised when an object cannot be written or read."""


class ObjectStore(ABC):
    """Minimal object-store contract used by the ingestion and render paths."""

    backend_name: str = "unknown"

    @abstractmethod
    def put_file(self, local_path: str, key: str, content_type: Optional[str] = None) -> str:
        """Store ``local_path`` under ``key``. Returns the stored key."""

    @abstractmethod
    def put_bytes(self, data: bytes, key: str, content_type: Optional[str] = None) -> str:
        """Store raw ``data`` under ``key``. Returns the stored key."""

    @abstractmethod
    def download_to(self, key: str, local_path: str) -> str:
        """Copy the object at ``key`` to ``local_path``. Returns ``local_path``."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object. Missing objects are not an error."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """True when the object is present."""

    @abstractmethod
    def signed_url(self, key: str, *, filename: str, inline: bool = False, expires_in: int = 3600) -> str:
        """A time-limited URL a browser can fetch directly."""


def _guess_content_type(key: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# Local disk
# ---------------------------------------------------------------------------

class LocalObjectStore(ObjectStore):
    """
    Stores objects under a root directory and hands out HMAC-signed URLs that
    the ``/api/files`` route validates. Good enough for local development and
    single-node deploys, and it keeps the product working when R2 is down.
    """

    backend_name = "local"

    def __init__(self, root: Path, signing_secret: str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._secret = signing_secret.encode("utf-8")

    # -- path safety --------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        cleaned = key.strip().lstrip("/")
        if not cleaned:
            raise StorageError("Empty storage key")
        candidate = (self.root / cleaned).resolve()
        # Refuse anything that escapes the storage root ("../../etc/passwd").
        if not str(candidate).startswith(str(self.root)):
            raise StorageError(f"Refusing to access key outside storage root: {key}")
        return candidate

    # -- ObjectStore --------------------------------------------------------

    def put_file(self, local_path: str, key: str, content_type: Optional[str] = None) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        logger.info("Stored object locally: %s (%d bytes)", key, target.stat().st_size)
        return key

    def put_bytes(self, data: bytes, key: str, content_type: Optional[str] = None) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def download_to(self, key: str, local_path: str) -> str:
        source = self._resolve(key)
        if not source.exists():
            raise StorageError(f"Object not found: {key}")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, local_path)
        return local_path

    def delete(self, key: str) -> None:
        try:
            self._resolve(key).unlink(missing_ok=True)
        except StorageError:
            raise
        except OSError as exc:
            logger.warning("Failed to delete local object %s: %s", key, exc)

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).exists()
        except StorageError:
            return False

    def signed_url(self, key: str, *, filename: str, inline: bool = False, expires_in: int = 3600) -> str:
        expiry = int(time.time()) + expires_in
        signature = self.sign(key, expiry)
        disposition = "inline" if inline else "attachment"
        return (
            f"/api/files/{quote(key)}"
            f"?expires={expiry}&signature={signature}"
            f"&disposition={disposition}&filename={quote(filename)}"
        )

    # -- signing ------------------------------------------------------------

    def sign(self, key: str, expiry: int) -> str:
        message = f"{key}:{expiry}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, key: str, expiry: int, signature: str) -> bool:
        if expiry < int(time.time()):
            return False
        return hmac.compare_digest(self.sign(key, expiry), signature)

    def open_path(self, key: str) -> Path:
        path = self._resolve(key)
        if not path.exists():
            raise StorageError(f"Object not found: {key}")
        return path


# ---------------------------------------------------------------------------
# Cloudflare R2
# ---------------------------------------------------------------------------

class R2ObjectStore(ObjectStore):
    """S3-compatible driver for Cloudflare R2."""

    backend_name = "r2"

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )

    def put_file(self, local_path: str, key: str, content_type: Optional[str] = None) -> str:
        self.client.upload_file(
            local_path,
            self.bucket,
            key,
            ExtraArgs={"ContentType": _guess_content_type(key, content_type)},
        )
        return key

    def put_bytes(self, data: bytes, key: str, content_type: Optional[str] = None) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=_guess_content_type(key, content_type),
        )
        return key

    def download_to(self, key: str, local_path: str) -> str:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, local_path)
        return local_path

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Failed to delete R2 object %s: %s", key, exc)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def signed_url(self, key: str, *, filename: str, inline: bool = False, expires_in: int = 3600) -> str:
        disposition = "inline" if inline else f'attachment; filename="{filename}"'
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": disposition,
                "ResponseContentType": _guess_content_type(key, None),
            },
            ExpiresIn=expires_in,
        )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _build_store() -> ObjectStore:
    settings = get_settings()

    if settings.storage_backend == "local":
        logger.info("Storage backend: local (forced by STORAGE_BACKEND)")
        return LocalObjectStore(settings.storage_dir, settings.storage_signing_secret)

    if settings.storage_backend in {"r2", "auto"} and settings.has_r2:
        try:
            store = R2ObjectStore(
                settings.r2_endpoint_url,
                settings.r2_access_key_id,
                settings.r2_secret_access_key,
                settings.r2_bucket_name,
            )
            # A cheap reachability probe: if the bucket is gone or the keys have
            # been revoked we want to find out at startup, not mid-pipeline.
            store.client.head_bucket(Bucket=settings.r2_bucket_name)
            logger.info("Storage backend: r2 (bucket=%s)", settings.r2_bucket_name)
            return store
        except Exception as exc:
            if settings.storage_backend == "r2":
                raise StorageError(f"R2 storage was requested but is unreachable: {exc}") from exc
            logger.warning("R2 unreachable (%s). Falling back to local disk storage.", exc)

    logger.info("Storage backend: local (dir=%s)", settings.storage_dir)
    return LocalObjectStore(settings.storage_dir, settings.storage_signing_secret)


def get_object_store() -> ObjectStore:
    """Process-wide object store singleton."""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = _build_store()
    return _STORE


def reset_object_store() -> None:
    """Drop the cached store. Used by tests."""
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def storage_backend_name() -> str:
    return get_object_store().backend_name
