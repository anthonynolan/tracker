"""Video endpoints (Phase 1)."""

import json

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.config import DATA_DIR, get_settings
from backend.models.schemas import (
    FrameRef,
    FramesResponse,
    Keyframe,
    SegmentRequest,
    SegmentResponse,
    StatusResponse,
    UploadResponse,
)
from backend.services import frame_service, video_service
from backend.services.sam3_service import SAM3Service, save_mask_png

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


@router.get("/{video_id}/frames", response_model=FramesResponse,
            response_model_by_alias=True)
async def video_frames(video_id: str,
                       numSamples: int = Query(default=15, ge=1)) -> FramesResponse:
    # Extract-on-first-read: keyframes are written on the first call, then served
    # from disk (idempotent; later fix frames from Phase 6 land in the same dir).
    frames = frame_service.ensure_keyframes(video_id, numSamples)
    if frames is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    return FramesResponse(video_id=video_id, frames=[FrameRef(**f) for f in frames])


@router.post("/{video_id}/segment", response_model=SegmentResponse,
             response_model_by_alias=True)
async def segment_video(video_id: str, req: SegmentRequest) -> SegmentResponse:
    # SAM3 runs ONLY on the sampled keyframes (sequential in V1).
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    frames = frame_service.ensure_keyframes(video_id, req.num_samples)
    if frames is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    service = SAM3Service(api_key=get_settings().model_api_key.get_secret_value())
    keyframes: list[Keyframe] = []
    for ref in frames:
        idx = ref["frameIdx"]
        image_path = DATA_DIR / "frames" / video_id / f"{idx:06d}.jpg"
        try:
            seg = await service.segment(image_path, req.prompt)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502,
                                detail=f"SAM3 failed on frame {idx}: {exc}") from exc
        if seg is None:
            # Processed, nothing found — kept explicit so the UI can show it.
            keyframes.append(Keyframe(
                frame_idx=idx, timestamp=idx / metadata.fps, bbox=None,
                mask_path=None, prompt=req.prompt, confidence=None))
            continue
        mask_name = f"{idx:06d}.png"
        save_mask_png(DATA_DIR / "masks" / video_id / mask_name,
                      seg.mask_raster, seg.width, seg.height)
        keyframes.append(Keyframe(
            frame_idx=idx, timestamp=idx / metadata.fps, bbox=seg.bbox,
            mask_path=f"/masks/{video_id}/{mask_name}", prompt=req.prompt,
            confidence=None))
    masks_dir = DATA_DIR / "masks" / video_id
    masks_dir.mkdir(parents=True, exist_ok=True)
    (masks_dir / "keyframes.json").write_text(json.dumps(
        {"videoId": video_id, "prompt": req.prompt, "sam3Calls": len(keyframes),
         "keyframes": [k.model_dump(by_alias=True) for k in keyframes]}, indent=2))
    return SegmentResponse(keyframes=keyframes, sam3_calls=len(keyframes))
