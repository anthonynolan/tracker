"""Keyframe sampling + extraction (Phase 2). No SAM3 here."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image

from backend.services import storage, video_service


def getSampleFrameIndices(total_frames: int, num_samples: int = 15) -> list[int]:
    """Evenly spaced frame indices, inclusive of first and last.

    When `total_frames <= num_samples`, returns every index (clamp).
    """
    if total_frames <= 0:
        raise ValueError("total_frames must be positive")
    if num_samples <= 0:
        raise ValueError("num_samples must be positive")
    if num_samples == 1:
        return [0]
    if total_frames <= num_samples:
        return list(range(total_frames))
    step = total_frames / (num_samples - 1)
    return [*(math.floor(i * step) for i in range(num_samples - 1)), total_frames - 1]


def get_display_size(video_id: str) -> tuple[int, int] | None:
    """Display-space (W, H) measured from the first extracted keyframe JPEG."""
    store = storage.get_storage()
    frames = store.list_frames(video_id)
    if not frames:
        return None
    with Image.open(store.frame_path(video_id, frames[0])) as img:
        return img.size


def ensure_frame(video_id: str, frame_idx: int) -> dict | None:
    """Extract a single frame JPEG on demand (idempotent).

    Returns `{frameIdx, url}`, None for unknown video. Raises ValueError when
    the index is out of range.
    """
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        return None
    if not (0 <= frame_idx < metadata.total_frames):
        raise ValueError(f"frame {frame_idx} out of range")
    original = video_service.get_original_path(video_id)
    if original is None:
        return None
    store = storage.get_storage()
    target = store.frame_path(video_id, frame_idx)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        _extract_frame(original, target, frame_idx / metadata.fps,
                       1 / metadata.fps)
        store.sync_media("frames", video_id, target.name)
    return {"frameIdx": frame_idx,
            "url": f"/frames/{video_id}/{frame_idx:06d}.jpg"}


def ensure_keyframes(video_id: str, num_samples: int = 15) -> list[dict] | None:
    """Extract the sampled keyframes for an upload (idempotent).

    Returns `[{frameIdx, url}]`, or `None` for an unknown video.
    """
    metadata = video_service.get_metadata(video_id)
    if metadata is None:
        return None
    original = video_service.get_original_path(video_id)
    if original is None:
        return None
    indices = getSampleFrameIndices(metadata.total_frames, num_samples)
    if not indices:
        return []
    store = storage.get_storage()
    store.frame_path(video_id, indices[0]).parent.mkdir(parents=True,
                                                        exist_ok=True)
    for idx in indices:
        target = store.frame_path(video_id, idx)
        if target.exists():
            continue
        _extract_frame(original, target, idx / metadata.fps, 1 / metadata.fps)
        store.sync_media("frames", video_id, target.name)
    return [{"frameIdx": idx, "url": f"/frames/{video_id}/{idx:06d}.jpg"}
            for idx in indices]


def _extract_frame(original: Path, target: Path, timestamp: float, frame_step: float,
                   attempts: int = 10) -> None:
    """Extract one frame, stepping back if the timestamp overshoots EOF.

    `totalFrames` is estimated when ffprobe is absent, so the tail index can map
    past the last real frame — ffmpeg then exits 0 with no output. Step back up
    to `attempts` frames to land on decodable content; the file keeps the
    requested index (tail index may hold the nearest earlier frame).
    """
    for attempt in range(attempts):
        seek = max(timestamp - attempt * frame_step, 0.0)
        subprocess.run(
            [video_service.ffmpeg_exe(), "-y", "-loglevel", "error",
             "-ss", f"{seek:.6f}", "-i", str(original),
             "-frames:v", "1", "-q:v", "3", str(target)],
            check=True, timeout=120,
        )
        if target.exists() and target.stat().st_size > 0:
            return
    raise ValueError(f"could not extract frame near t={timestamp:.3f}s")
