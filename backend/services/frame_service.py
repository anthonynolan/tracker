"""Keyframe sampling + extraction (Phase 2). No SAM3 here."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image

from backend.config import DATA_DIR
from backend.services import video_service

FRAMES_DIRNAME = "frames"


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
    frames = sorted((DATA_DIR / FRAMES_DIRNAME / video_id).glob("*.jpg"))
    if not frames:
        return None
    with Image.open(frames[0]) as img:
        return img.size


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
    out_dir = DATA_DIR / FRAMES_DIRNAME / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx in indices:
        target = out_dir / f"{idx:06d}.jpg"
        if target.exists():
            continue
        _extract_frame(original, target, idx / metadata.fps, 1 / metadata.fps)
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
