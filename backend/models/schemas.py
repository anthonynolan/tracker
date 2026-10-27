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


class SegmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(min_length=1)
    num_samples: int = Field(default=15, ge=1, alias="numSamples")


class SegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    keyframes: list[Keyframe]
    sam3_calls: int = Field(alias="sam3Calls")
