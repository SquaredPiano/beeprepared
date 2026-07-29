"""Serves stored files to holders of a valid signed link."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.services.files import FileStore, StorageError, get_file_store

router = APIRouter(prefix="/api/files", tags=["files"])

CACHE_SECONDS = 300


@router.get("/{key:path}")
def serve_file(
    key: str,
    expires: int = Query(description="Unix timestamp after which the link is dead"),
    signature: str = Query(description="HMAC over the key and expiry"),
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    filename: str = Query("download"),
    store: FileStore = Depends(get_file_store),
) -> FileResponse:
    """
    Serve a stored object.

    The signature is the credential here. These links end up in an `<img>` tag,
    in an iframe previewing a PDF, and in the browser's own download manager, and
    none of those can send a bearer token. Once the credential lives in the URL it
    gets logged, pasted into chat and left in browser history, so the link expires
    to put a limit on what a leaked one is worth.
    """
    if not store.verify(key, expires, signature):
        raise HTTPException(status_code=403, detail="This link is invalid or has expired")

    try:
        path = store.open_path(key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return FileResponse(
        path,
        media_type=store.content_type(key),
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": f"private, max-age={CACHE_SECONDS}",
        },
    )
