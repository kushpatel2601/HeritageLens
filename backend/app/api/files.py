"""Serving stored blobs with HTTP caching (ETag / immutable) and Range support on local disk."""

from __future__ import annotations

import mimetypes

from fastapi import Request, Response
from fastapi.responses import FileResponse

from app.core.errors import NotFoundError
from app.services.storage import Storage

IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("model/gltf-binary", ".glb")


def guess_type(key: str, default: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(key)[0] or default


async def blob_response(
    request: Request,
    storage: Storage,
    key: str | None,
    *,
    media_type: str | None = None,
    etag: str | None = None,
    immutable: bool = False,
    filename: str | None = None,
) -> Response:
    if not key:
        raise NotFoundError("blob not available")
    headers = {"Cache-Control": IMMUTABLE if immutable else SHORT}
    if etag:
        headers["ETag"] = f'"{etag}"'
        if request.headers.get("if-none-match") == headers["ETag"]:
            return Response(status_code=304, headers=headers)
    media_type = media_type or guess_type(key)
    path = storage.local_path(key)
    if path is not None:
        if not path.is_file():
            raise NotFoundError("blob missing from storage")
        return FileResponse(
            path, media_type=media_type, headers=headers, filename=filename, content_disposition_type="inline"
        )
    try:
        data = await storage.get(key)
    except Exception as exc:
        raise NotFoundError("blob missing from storage") from exc
    return Response(data, media_type=media_type, headers=headers)
