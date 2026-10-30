"""Storage-backed media serving for the MongoDB backend (Phase 11).

The filesystem backend keeps StaticFiles (untouched). Included ONLY when
the storage backend is MongoDB — and LAST, since `/{kind}/{id}/{name}`
must not shadow real routes. Serves GridFS bytes with Range support so
<video> seeking works; URLs are identical to the filesystem mounts.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from backend.services import storage
from backend.services.storage import MongoStorage

router = APIRouter(tags=["media"])

_MEDIA_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png"}
_KINDS = ("uploads", "frames", "masks", "outputs")


def parse_range(header: str | None, total: int) -> tuple[int, int] | None:
    """Parse a single `bytes=start-end` range; None means serve 200."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].strip()
    if "," in spec:
        return None
    start_s, _, end_s = spec.partition("-")
    try:
        start = int(start_s) if start_s else None
        end = int(end_s) if end_s else None
    except ValueError:
        return None
    if start is None:
        if not end:
            return None
        start, end = max(0, total - end), total - 1
    else:
        if start >= total:
            return None
        end = total - 1 if end is None else min(end, total - 1)
        if end < start:
            return None
    return start, end


@router.get("/{kind}/{video_id}/{name}")
async def serve_media(kind: str, video_id: str, name: str, request: Request):
    store = storage.get_storage()
    if not isinstance(store, MongoStorage):
        raise HTTPException(status_code=404, detail="not found")
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="not found")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    media_type = _MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise HTTPException(status_code=404, detail="not found")
    probe = store.read_media(kind, video_id, name, 0, 0)
    if probe is None:
        raise HTTPException(status_code=404, detail="not found")
    _, total = probe
    span = parse_range(request.headers.get("range"), total)
    if span is None:
        data, _ = store.read_media(kind, video_id, name)
        return Response(content=data, media_type=media_type,
                        headers={"Accept-Ranges": "bytes"})
    start, end = span
    data, _ = store.read_media(kind, video_id, name, start, end)
    return Response(content=data, status_code=206, media_type=media_type,
                    headers={"Accept-Ranges": "bytes",
                             "Content-Range": f"bytes {start}-{end}/{total}"})
