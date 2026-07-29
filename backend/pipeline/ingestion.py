"""Brings source material into the system and files it in storage."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Union
from urllib.parse import urlparse

import yt_dlp

from backend.core.config import get_settings
from backend.services.files import FileStore, get_file_store

logger = logging.getLogger(__name__)

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


class IngestionError(RuntimeError):
    """A source could not be fetched or stored."""


class UnsafeSourceError(IngestionError):
    """
    A source URL was refused before anything was fetched.

    This gets its own class so a refusal reads as a decision we made, not a
    download that went wrong. It also has to be permanent. `is_transient` in the
    job runner decides what to retry from the exception type and the words in
    the message, and nothing here looks like a busy upstream, so a refused job
    fails once and stays failed. Otherwise we'd replay the same blocked request
    until the job ran out of attempts.
    """


@dataclass(frozen=True)
class StoredSource:
    """Where a source ended up and what it was called."""

    key: str
    original_name: str
    source_type: str
    size_bytes: int


class HostResolver:
    """Looks up every address a hostname currently points at."""

    def addresses(self, host: str) -> List[str]:
        """Return every address this host resolves to, refusing it if there are none."""
        try:
            records = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as error:
            raise UnsafeSourceError(f"The host '{host}' does not resolve: {error}") from error

        found = [str(record[4][0]) for record in records]
        if not found:
            raise UnsafeSourceError(f"The host '{host}' resolves to no address")
        return found


class YouTubeUrlGuard:
    """
    Refuses any URL that is not a public YouTube address.

    `source_type: "youtube"` is just a label the caller picked. It doesn't
    constrain where the fetch actually goes. Hand yt-dlp a URL it doesn't
    recognise and its generic extractor downloads whatever the far end returns,
    and then we store those bytes, pull text out of them, and commit the result
    as an artifact the caller can read back. So without this check the field is
    a full-response SSRF against anything the server can reach. That's why the
    guard sits here, one line before the call that makes the request, and not
    only at the HTTP door. A route bypassed the request model there once already.

    We accept a host that equals an allowed name or is a proper subdomain of
    one. A substring test would happily let `youtube.com.evil.tld` through. Then
    we check every address the host resolved to, and one disallowed answer is
    enough to refuse the lot, because an allowed name can still point inward and
    a resolver can hand back several addresses with only one of them internal.
    """

    ALLOWED_HOSTS = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})

    NON_PUBLIC_RANGES = (
        "is_private",
        "is_loopback",
        "is_link_local",
        "is_multicast",
        "is_reserved",
        "is_unspecified",
    )

    def __init__(self, resolver: Optional[HostResolver] = None) -> None:
        self._resolver = resolver or HostResolver()

    def check(self, url: str) -> None:
        """Raise `UnsafeSourceError` unless this URL names a public YouTube host."""
        host = self._host(url)

        if not self._is_youtube(host):
            raise UnsafeSourceError(
                f"'{host}' is not a YouTube host. A youtube source must name one of: "
                f"{', '.join(sorted(self.ALLOWED_HOSTS))}."
            )

        for text in self._resolver.addresses(host):
            address = self._address(text)
            if not self._is_public(address):
                raise UnsafeSourceError(
                    f"'{host}' resolves to {address}, which is not on the public internet."
                )

    @staticmethod
    def _host(url: str) -> str:
        """
        Return the hostname we have to authorise.

        We lowercase it and trim the surrounding space and any trailing dot, so
        `YouTube.com.` and `youtube.com` can't come out as two different hosts.
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeSourceError(
                f"A youtube source must be an http(s) URL, not '{parsed.scheme or url}'"
            )

        host = (parsed.hostname or "").strip().rstrip(".").lower()
        if not host:
            raise UnsafeSourceError("A youtube source URL must name a host")
        return host

    def _is_youtube(self, host: str) -> bool:
        return any(
            host == allowed or host.endswith(f".{allowed}") for allowed in self.ALLOWED_HOSTS
        )

    def _is_public(self, address: IPAddress) -> bool:
        return not any(getattr(address, name) for name in self.NON_PUBLIC_RANGES)

    @staticmethod
    def _address(text: str) -> IPAddress:
        """
        Turn one resolved answer into an address object we can test.

        When the answer is an IPv4-mapped IPv6 address we test the IPv4 address
        it stands for, so `::ffff:127.0.0.1` still gets caught as loopback. If it
        won't parse at all we refuse it. Failing closed is the only safe
        direction here.
        """
        try:
            address: IPAddress = ipaddress.ip_address(text.split("%")[0])
        except ValueError as error:
            raise UnsafeSourceError(f"Could not read the resolved address '{text}'") from error

        return getattr(address, "ipv4_mapped", None) or address


class IngestionService:
    """Stores uploads and downloads remote sources into the file store."""

    def __init__(
        self,
        store: Optional[FileStore] = None,
        guard: Optional[YouTubeUrlGuard] = None,
    ) -> None:
        self._store = store or get_file_store()
        self._guard = guard or YouTubeUrlGuard()

    def store_upload(self, file_path: str, project_id: str, original_name: str, source_type: str) -> StoredSource:
        """Put a file that's already on local disk into the store, under its project."""
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
        self._guard.check(url)
        logger.info("Fetching YouTube audio: %s", url)

        with tempfile.TemporaryDirectory() as workspace:
            options = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(workspace, "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "max_filesize": self._download_limit_bytes(),
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
    def _download_limit_bytes() -> int:
        """
        Cap a download at the same size we cap an upload at.

        A download is the other way into the file store, and the upload route's
        limit never covered it. With no `max_filesize` set, yt-dlp writes
        whatever the far end sends until the disk fills up or the job times out.
        """
        return get_settings().upload_max_mb * 1024 * 1024

    @staticmethod
    def _downloaded_path(downloader: Any, info: Any, workspace: Path) -> Path:
        """
        Find the file yt-dlp actually left on disk.

        The name we get out of the output template is only a guess, because
        format merging and post-processing rewrite the extension. So we trust the
        paths yt-dlp reports first, and if none of them are really there we fall
        back to whatever turned up in the workspace.
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
