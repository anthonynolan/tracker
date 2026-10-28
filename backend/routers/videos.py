"""Video endpoints (Phase 1)."""

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from backend.config import get_settings
from backend.models.schemas import (
    FixKeyframeRequest,
    FixKeyframeResponse,
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
from backend.services import (
    frame_service, render_service, storage, track_builder, video_service)
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
    store = storage.get_storage()
    if not store.output_exists(video_id):
        raise HTTPException(status_code=404, detail="no rendered output yet")
    return FileResponse(store.output_path(video_id), media_type="video/mp4",
                        filename="cropped.mp4")


@router.post("/{video_id}/render", response_model=RenderResponse,
             response_model_by_alias=True)
async def render_video(video_id: str, req: RenderRequest) -> RenderResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    if req.track_id != video_id:
        raise HTTPException(status_code=400,
                            detail="unknown trackId (V1 supports one track per video)")
    store = storage.get_storage()
    track = store.read_track(video_id)
    if track is None:
        raise HTTPException(status_code=404, detail="no track: build it first")
    original = video_service.get_original_path(video_id)
    if original is None:
        raise HTTPException(status_code=404, detail="original file missing")
    display = frame_service.get_display_size(video_id)
    if display is None:
        raise HTTPException(status_code=404, detail="no keyframes extracted")
    try:
        result = render_service.render_cropped_video(
            original, store.output_path(video_id),
            track["interpolatedBoxes"], display[0], display[1], metadata.fps,
            padding=req.padding, aspect_ratio=req.aspect_ratio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    store.write_render_params(video_id, {"padding": req.padding,
                                         "aspectRatio": req.aspect_ratio,
                                         **result})
    return RenderResponse(output_url=f"/outputs/{video_id}/cropped.mp4", **result)


@router.post("/{video_id}/keyframes", response_model=FixKeyframeResponse,
             response_model_by_alias=True)
async def fix_keyframe(video_id: str, req: FixKeyframeRequest) -> FixKeyframeResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    store = storage.get_storage()
    stored = store.read_keyframes(video_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no keyframes: segment first")
    if any(k["frameIdx"] == req.frame_idx for k in stored["keyframes"]):
        raise HTTPException(status_code=409, detail="frame is already a keyframe")
    try:
        ensured = frame_service.ensure_frame(video_id, req.frame_idx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if ensured is None:
        raise HTTPException(status_code=404, detail="original file missing")
    service = SAM3Service(api_key=get_settings().model_api_key.get_secret_value())
    image_path = store.frame_path(video_id, req.frame_idx)
    try:
        seg = await service.segment(image_path, stored["prompt"])
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502,
                            detail=f"SAM3 failed on frame {req.frame_idx}: {exc}"
                            ) from exc
    if seg is None:
        keyframe = Keyframe(frame_idx=req.frame_idx,
                            timestamp=req.frame_idx / metadata.fps, bbox=None,
                            mask_path=None, prompt=stored["prompt"],
                            confidence=None, origin="fix")
    else:
        mask_name = f"{req.frame_idx:06d}.png"
        save_mask_png(store.mask_path(video_id, req.frame_idx),
                      seg.mask_raster, seg.width, seg.height)
        keyframe = Keyframe(
            frame_idx=req.frame_idx, timestamp=req.frame_idx / metadata.fps,
            bbox=seg.bbox, mask_path=f"/masks/{video_id}/{mask_name}",
            prompt=stored["prompt"], confidence=None, origin="fix")
    stored["keyframes"] = sorted([*stored["keyframes"],
                                  keyframe.model_dump(by_alias=True)],
                                 key=lambda k: k["frameIdx"])
    store.write_keyframes(video_id, stored)
    track = store.read_track(video_id)
    if seg is None or track is None:
        return FixKeyframeResponse(keyframe=keyframe, sam3_calls=1,
                                   track_rebuilt=False, rerendered=False,
                                   output_url=None)
    valid = [k for k in track["keyframes"] if k.get("bbox") is not None]
    new_boxes, _ = track_builder.insert_keyframe(
        track["interpolatedBoxes"], valid,
        {"frameIdx": req.frame_idx, "bbox": seg.bbox}, metadata.total_frames)
    track["keyframes"] = sorted(
        [*track["keyframes"], keyframe.model_dump(by_alias=True)],
        key=lambda k: k["frameIdx"])
    track["interpolatedBoxes"] = new_boxes
    store.write_track(video_id, track)
    output_url = None
    rerendered = False
    cropped = store.output_path(video_id)
    if store.output_exists(video_id):
        params = (store.read_render_params(video_id)
                  or {"padding": 0.1, "aspectRatio": None})
        display = frame_service.get_display_size(video_id)
        original = video_service.get_original_path(video_id)
        try:
            render_service.render_cropped_video(
                original, cropped, new_boxes, display[0], display[1],
                metadata.fps, padding=params.get("padding", 0.1),
                aspect_ratio=params.get("aspectRatio"))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=500,
                                detail=f"re-render failed: {exc}") from exc
        rerendered = True
        output_url = f"/outputs/{video_id}/cropped.mp4"
    return FixKeyframeResponse(keyframe=keyframe, sam3_calls=1,
                               track_rebuilt=True, rerendered=rerendered,
                               output_url=output_url)


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
    store = storage.get_storage()
    service = SAM3Service(api_key=get_settings().model_api_key.get_secret_value())
    keyframes: list[Keyframe] = []
    for ref in frames:
        idx = ref["frameIdx"]
        image_path = store.frame_path(video_id, idx)
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
        save_mask_png(store.mask_path(video_id, idx),
                      seg.mask_raster, seg.width, seg.height)
        keyframes.append(Keyframe(
            frame_idx=idx, timestamp=idx / metadata.fps, bbox=seg.bbox,
            mask_path=f"/masks/{video_id}/{mask_name}", prompt=req.prompt,
            confidence=None))
    store.write_keyframes(video_id, {"videoId": video_id, "prompt": req.prompt,
                                     "sam3Calls": len(keyframes),
                                     "keyframes": [k.model_dump(by_alias=True)
                                                   for k in keyframes]})
    return SegmentResponse(keyframes=keyframes, sam3_calls=len(keyframes))


@router.post("/{video_id}/track", response_model=TrackResponse,
             response_model_by_alias=True)
async def build_track(video_id: str, req: TrackRequest) -> TrackResponse:
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    store = storage.get_storage()
    stored = store.read_keyframes(video_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no keyframes: segment first")
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
    store.write_track(video_id, track)
    return TrackResponse(track_id=video_id, video_id=video_id, prompt=req.prompt,
                         num_frames=metadata.total_frames,
                         keyframe_count=len(valid))


@router.get("/{video_id}/track", response_model=TrackData,
            response_model_by_alias=True)
async def get_track(video_id: str) -> TrackData:
    if video_service.get_metadata(video_id) is None:
        raise HTTPException(status_code=404, detail="unknown videoId")
    track = storage.get_storage().read_track(video_id)
    if track is None:
        raise HTTPException(status_code=404, detail="no track: build it first")
    return TrackData.model_validate(track)
