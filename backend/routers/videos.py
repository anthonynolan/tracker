"""Video endpoints (Phase 1)."""

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.models.schemas import StatusResponse, UploadResponse
from backend.services import video_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=UploadResponse, response_model_by_alias=True)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        return video_service.save_upload(file.filename or "upload.mp4", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{video_id}/status", response_model=StatusResponse,
            response_model_by_alias=True)
async def video_status(video_id: str) -> StatusResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    return StatusResponse(video_id=video_id, status="uploaded", metadata=metadata)


@router.get("/{video_id}/output")
async def video_output(video_id: str) -> dict:
    if video_service.get_metadata(video_id) is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    raise HTTPException(status_code=404, detail="no rendered output yet (Phase 5)")
