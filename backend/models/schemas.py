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
