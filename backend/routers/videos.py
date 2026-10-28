"""Video endpoints (Phase 1)."""

import json

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from backend.config import DATA_DIR, get_settings
from backend.models.schemas import (
    FrameRef,
    FramesResponse,
    Keyframe,
    RenderRequest,
    RenderResponse,
    SegmentRequest,
    SegmentResponse,
    StatusResponse,
    TrackData,
    TrackRequest,
    TrackResponse,
    UploadResponse,
)
from backend.services import frame_service, render_service, track_builder, video_service
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
async def video_output(video_id: str):
    if video_service.get_metadata(video_id) is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    path = DATA_DIR / "outputs" / video_id / "cropped.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no rendered output yet")
    return FileResponse(path, media_type="video/mp4", filename="cropped.mp4")


@router.post("/{video_id}/render", response_model=RenderResponse,
             response_model_by_alias=True)
async def render_video(video_id: str, req: RenderRequest) -> RenderResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    if req.track_id != video_id:
        raise HTTPException(status_code=400,
                            detail="unknown trackId (V1 supports one track per video)")
    track_path = DATA_DIR / "outputs" / video_id / "track.json"
    if not track_path.exists():
        raise HTTPException(status_code=404, detail="no track: build it first")
    track = json.loads(track_path.read_text())
    original = video_service.get_original_path(video_id)
    if original is None:
        raise HTTPException(status_code=404, detail="original file missing")
    display = frame_service.get_display_size(video_id)
    if display is None:
        raise HTTPException(status_code=404, detail="no keyframes extracted")
    try:
        result = render_service.render_cropped_video(
            original, DATA_DIR / "outputs" / video_id / "cropped.mp4",
            track["interpolatedBoxes"], display[0], display[1], metadata.fps,
            padding=req.padding, aspect_ratio=req.aspect_ratio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RenderResponse(output_url=f"/outputs/{video_id}/cropped.mp4", **result)


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


@router.post("/{video_id}/track", response_model=TrackResponse,
             response_model_by_alias=True)
async def build_track(video_id: str, req: TrackRequest) -> TrackResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    stored_path = DATA_DIR / "masks" / video_id / "keyframes.json"
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="no keyframes: segment first")
    stored = json.loads(stored_path.read_text())
    if stored.get("prompt") != req.prompt:
        raise HTTPException(
            status_code=400,
            detail="prompt does not match segmented prompt: re-segment to change it")
    try:
        boxes = track_builder.interpolate_boxes(stored.get("keyframes", []),
                                                metadata.total_frames)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    valid = [k for k in stored["keyframes"] if k.get("bbox") is not None]
    track = {"videoId": video_id, "prompt": req.prompt, "keyframes": valid,
             "interpolatedBoxes": boxes}
    out_dir = DATA_DIR / "outputs" / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "track.json").write_text(json.dumps(track, indent=2))
    return TrackResponse(track_id=video_id, video_id=video_id, prompt=req.prompt,
                         num_frames=metadata.total_frames,
                         keyframe_count=len(valid))


@router.get("/{video_id}/track", response_model=TrackData,
            response_model_by_alias=True)
async def get_track(video_id: str) -> TrackData:
    if video_service.get_metadata(video_id) is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    path = DATA_DIR / "outputs" / video_id / "track.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no track: build it first")
    return TrackData.model_validate_json(path.read_text())
