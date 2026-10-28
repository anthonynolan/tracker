"""Fixed-window crop rendering (Phase 5).

Renders in DISPLAY space (autorotated, matching the extracted keyframe JPEGs
that SAM3 boxes are normalized against) — never coded dimensions. Decodes to
rawvideo, crops per-frame positions in numpy, re-encodes, then muxes the
original audio track.
"""

from __future__ import annotations

import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.services import video_service

logger = logging.getLogger("tracker")

_ASPECT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")


def parse_aspect_ratio(value: str | None) -> float | None:
    """Parse 'W:H' into a float ratio. None/empty stays None (content shape)."""
    if value is None or value == "":
        return None
    match = _ASPECT_RE.fullmatch(value.strip())
    if not match or float(match.group(2)) == 0:
        raise ValueError(f"invalid aspectRatio, expected 'W:H': {value!r}")
    return float(match.group(1)) / float(match.group(2))


def compute_crop_window(boxes: list[dict], frame_w: int, frame_h: int,
                        padding: float = 0.1,
                        aspect_ratio: str | None = None) -> tuple[int, int]:
    """Fixed crop size: track-max box + padding, aspect-expanded, even-px.

    Aspect is enforced by EXPANDING (object stays inside); if the window would
    exceed the frame it is scaled down to fit (keeping aspect).
    """
    if not boxes:
        raise ValueError("no boxes to cover")
    if padding < 0:
        raise ValueError("padding must be >= 0")
    target = parse_aspect_ratio(aspect_ratio)
    px_w = max(b["w"] for b in boxes) * (1 + padding) * frame_w
    px_h = max(b["h"] for b in boxes) * (1 + padding) * frame_h
    if target is not None and px_h > 0:
        if px_w / px_h < target:
            px_w = px_h * target
        else:
            px_h = px_w / target
    if px_w > frame_w or px_h > frame_h:
        scale = min(frame_w / px_w, frame_h / px_h)
        px_w, px_h = px_w * scale, px_h * scale
    return max(2, int(px_w) // 2 * 2), max(2, int(px_h) // 2 * 2)


def crop_position(box: dict, frame_w: int, frame_h: int,
                  crop_w: int, crop_h: int) -> tuple[int, int]:
    """Top-left crop origin following the box center, clamped to frame."""
    cx = (box["x"] + box["w"] / 2) * frame_w
    cy = (box["y"] + box["h"] / 2) * frame_h
    return (min(max(round(cx - crop_w / 2), 0), frame_w - crop_w),
            min(max(round(cy - crop_h / 2), 0), frame_h - crop_h))


@lru_cache(maxsize=1)
def _video_encoder() -> str:
    probe = subprocess.run(
        [video_service.ffmpeg_exe(), "-hide_banner", "-h", "encoder=libx264"],
        capture_output=True, text=True)
    return "libx264" if probe.returncode == 0 else "mpeg4"


def _has_audio(path: Path) -> bool:
    proc = subprocess.run([video_service.ffmpeg_exe(), "-i", str(path)],
                          capture_output=True, text=True)
    return re.search(r"Stream #\d+:\d+.*Audio:", proc.stderr) is not None


def _read_exact(stream, size: int) -> bytes | None:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def render_cropped_video(original: Path, output: Path, boxes: list[dict],
                         frame_w: int, frame_h: int, fps: float,
                         padding: float = 0.1,
                         aspect_ratio: str | None = None) -> dict:
    """Render the fixed-window crop. Returns {width, height, numFrames}."""
    crop_w, crop_h = compute_crop_window(boxes, frame_w, frame_h,
                                         padding, aspect_ratio)
    positions = [crop_position(b, frame_w, frame_h, crop_w, crop_h) for b in boxes]
    output.parent.mkdir(parents=True, exist_ok=True)
    silent = output.with_name(output.stem + ".silent.mp4")
    exe = video_service.ffmpeg_exe()
    frame_bytes = frame_w * frame_h * 3
    decode = subprocess.Popen(
        [exe, "-loglevel", "error", "-autorotate", "-i", str(original),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    encode = subprocess.Popen(
        [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{crop_w}x{crop_h}", "-framerate", str(fps), "-i", "pipe:0",
         "-c:v", _video_encoder(), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(silent)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    written = 0
    try:
        for x, y in positions:
            raw = _read_exact(decode.stdout, frame_bytes)
            if raw is None:
                logger.warning("decode ended at frame %d of %d",
                               written, len(positions))
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(frame_h, frame_w, 3)
            encode.stdin.write(frame[y:y + crop_h, x:x + crop_w].tobytes())
            written += 1
    finally:
        try:
            encode.stdin.close()
        except BrokenPipeError:
            pass
        # Close our read end first: a decoder blocked writing to a full pipe
        # cannot shut down gracefully, so unblock it, then terminate.
        decode.stdout.close()
        decode.terminate()
        try:
            encode.wait(timeout=300)
        except subprocess.TimeoutExpired:
            encode.kill()
            decode.kill()
            raise RuntimeError("encode timed out")
        try:
            decode.wait(timeout=60)
        except subprocess.TimeoutExpired:
            decode.kill()
            decode.wait(timeout=60)
        encode_err = encode.stderr.read()
    if written == 0:
        raise RuntimeError("no frames decoded")
    if encode.returncode != 0:
        raise RuntimeError(f"encode failed: {encode_err.decode()[-500:]}")
    if _has_audio(original):
        mux = subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", str(silent), "-i", str(original),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
             "-shortest", str(output)], capture_output=True, text=True)
        if mux.returncode != 0:
            raise RuntimeError(f"audio mux failed: {mux.stderr[-500:]}")
        silent.unlink(missing_ok=True)
    else:
        silent.replace(output)
    return {"width": crop_w, "height": crop_h, "numFrames": written}
