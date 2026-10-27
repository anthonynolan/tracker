"""Upload storage + metadata probing (Phase 1)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import imageio_ffmpeg

from backend.config import DATA_DIR
from backend.models.schemas import UploadResponse, VideoMetadata

UPLOAD_DIRNAME = "uploads"
_VIDEO_ID_RE = re.compile(r"[0-9a-f]{32}")


def ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def probe_metadata(path: Path) -> dict:
    """Probe `{width,height,fps,duration,totalFrames}`.

    Uses `ffprobe` JSON when available (exact frame count); otherwise parses
    `ffmpeg -i` output and estimates `totalFrames` as `duration * fps`.
    Raises `ValueError` when the file is not a readable video.
    """
    ffprobe = shutil.which("ffprobe")
    try:
        if ffprobe:
            return _probe_with_ffprobe(ffprobe, path)
        return _probe_with_ffmpeg(path)
    except (subprocess.CalledProcessError, KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"unreadable video upload: {path.name}") from exc


def _probe_with_ffprobe(ffprobe: str, path: Path) -> dict:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,duration,nb_frames",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    info = json.loads(out)
    stream = info["streams"][0]
    num, den = stream["avg_frame_rate"].split("/")
    fps = float(num) / float(den)
    duration = float(stream.get("duration") or info["format"]["duration"])
    total = stream.get("nb_frames")
    total_frames = int(total) if total not in (None, "N/A") else int(duration * fps)
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "fps": fps, "duration": duration, "totalFrames": total_frames}


def _probe_with_ffmpeg(path: Path) -> dict:
    proc = subprocess.run([ffmpeg_exe(), "-i", str(path)],
                          capture_output=True, text=True, timeout=60)
    err = proc.stderr
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not match:
        raise ValueError("no duration found")
    duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    video = re.search(r"Stream #\d+:\d+.*Video:.*?, (\d+)x(\d+)", err)
    if not video:
        raise ValueError("no video stream found")
    rate = re.search(r"(\d+(?:\.\d+)?) fps", err) or re.search(r"(\d+(?:\.\d+)?) tbr", err)
    if not rate:
        raise ValueError("no frame rate found")
    fps = float(rate.group(1))
    return {"width": int(video.group(1)), "height": int(video.group(2)),
            "fps": fps, "duration": duration, "totalFrames": int(duration * fps)}


def save_upload(filename: str, content: bytes) -> UploadResponse:
    """Store an upload under a UUID, probe it, and write `meta.json`."""
    video_id = uuid.uuid4().hex
    target = DATA_DIR / UPLOAD_DIRNAME / video_id
    target.mkdir(parents=True, exist_ok=False)
    suffix = Path(filename).suffix.lower() or ".mp4"
    original = target / f"original{suffix}"
    try:
        original.write_bytes(content)
        meta = probe_metadata(original)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    metadata = VideoMetadata(video_id=video_id, filename=filename, **meta)
    (target / "meta.json").write_text(metadata.model_dump_json(by_alias=True, indent=2))
    return UploadResponse(video_id=video_id, metadata=metadata,
                          original_url=f"/uploads/{video_id}/original{suffix}")


def get_metadata(video_id: str) -> VideoMetadata | None:
    """Read `meta.json` for an upload, or `None` for unknown/malformed ids."""
    if not _VIDEO_ID_RE.fullmatch(video_id):
        return None
    meta_file = DATA_DIR / UPLOAD_DIRNAME / video_id / "meta.json"
    if not meta_file.exists():
        return None
    return VideoMetadata.model_validate_json(meta_file.read_text())


def get_original_path(video_id: str) -> Path | None:
    """Locate the stored original file for an upload, if any."""
    if not _VIDEO_ID_RE.fullmatch(video_id):
        return None
    matches = sorted((DATA_DIR / UPLOAD_DIRNAME / video_id).glob("original.*"))
    return matches[0] if matches else None
