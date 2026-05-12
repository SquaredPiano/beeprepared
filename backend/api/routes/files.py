"""
File serving for the local storage backend.

When artifacts live on local disk there is no CDN to presign against, so the
backend serves them itself. Access is controlled by the same HMAC signature the
store hands out with the URL: the path and expiry are signed together, so a link
cannot be extended or pointed at a different object by editing the query string.

Requests are not authenticated with a session on purpose - these URLs are handed
to ``<img>``, ``<iframe>`` and download managers that will not send a bearer
token. The signature *is* the credential, and it expires.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.services.storage import LocalObjectStore, StorageError, get_object_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{key:path}")
def serve_file(
    key: str,
    expires: int = Query(..., description="Unix timestamp after which the link is dead"),
    signature: str = Query(..., description="HMAC over the key and expiry"),
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    filename: str = Query("download"),
) -> FileResponse:
    """Serve a locally stored object, if the signature checks out."""
    store = get_object_store()
    if not isinstance(store, LocalObjectStore):
        raise HTTPException(
            status_code=404,
            detail="This deployment serves files from object storage, not from the API",
        )

    if not store.verify(key, expires, signature):
        # One message for both cases: a tampered signature and an expired link
        # should be indistinguishable to a caller probing for valid keys.
        raise HTTPException(status_code=403, detail="This link is invalid or has expired")

    try:
        path = store.open_path(key)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    safe_name = quote(filename)
    return FileResponse(
        path,
        filename=filename,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{safe_name}",
            "Cache-Control": "private, max-age=300",
        },
    )
