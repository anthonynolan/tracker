"""Pydantic schemas for the video API (Phase 1)."""

from pydantic import BaseModel, ConfigDict, Field


class VideoMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    video_id: str = Field(alias="videoId")
    width: int
    height: int
    fps: float
    duration: float
    total_frames: int = Field(alias="totalFrames")
    filename: str


class UploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    video_id: str = Field(alias="videoId")
    metadata: VideoMetadata
    original_url: str = Field(alias="originalUrl")


class StatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    video_id: str = Field(alias="videoId")
    status: str
    metadata: VideoMetadata


class FrameRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    frame_idx: int = Field(alias="frameIdx")
    url: str


class FramesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    video_id: str = Field(alias="videoId")
    frames: list[FrameRef]


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class Keyframe(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    frame_idx: int = Field(alias="frameIdx")
    timestamp: float
    bbox: BBox | None  # None = processed, nothing found
    mask_path: str | None = Field(default=None, alias="maskPath")
    prompt: str
    confidence: float | None = None
    origin: str = "sampled"  # sampled | fix (default covers pre-Phase-6 files)


class SegmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(min_length=1)
    num_samples: int = Field(default=15, ge=1, alias="numSamples")


class SegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    keyframes: list[Keyframe]
    sam3_calls: int = Field(alias="sam3Calls")


class TrackRequest(BaseModel):
    prompt: str = Field(min_length=1)


class TrackResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    track_id: str = Field(alias="trackId")
    video_id: str = Field(alias="videoId")
    prompt: str
    num_frames: int = Field(alias="numFrames")
    keyframe_count: int = Field(alias="keyframeCount")


class TrackData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    video_id: str = Field(alias="videoId")
    prompt: str
    keyframes: list[Keyframe]
    interpolated_boxes: list[BBox] = Field(alias="interpolatedBoxes")


class RenderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    track_id: str = Field(alias="trackId")
    padding: float = Field(default=0.1, ge=0.0)
    aspect_ratio: str | None = Field(default=None, alias="aspectRatio")


class RenderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    output_url: str = Field(alias="outputUrl")
    width: int
    height: int
    num_frames: int = Field(alias="numFrames")


class FixKeyframeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    frame_idx: int = Field(ge=0, alias="frameIdx")


class FixKeyframeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    keyframe: Keyframe
    sam3_calls: int = Field(alias="sam3Calls")
    track_rebuilt: bool = Field(alias="trackRebuilt")
    rerendered: bool
    output_url: str | None = Field(default=None, alias="outputUrl")
