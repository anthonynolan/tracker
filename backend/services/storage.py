"""Storage abstraction (Phase 7).

All persistence flows through the `Storage` protocol. `FileSystemStorage`
keeps the exact Phase 1-6 on-disk layout; `MongoStorage` is prep only (every
op raises until implemented). Selected via STORAGE_BACKEND.
"""

from __future__ import annotations

import json
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from backend.config import ROOT, get_settings
from backend.models.schemas import VideoMetadata

_VIDEO_ID_RE = re.compile(r"[0-9a-f]{32}")


def _valid_video_id(video_id: str) -> bool:
    return _VIDEO_ID_RE.fullmatch(video_id) is not None


# Project ids share the uuid-hex shape.
_valid_project_id = _valid_video_id


class Storage(Protocol):
    """Persistence for videos, frames, masks, tracks, outputs."""

    def create_video(self, video_id: str, filename: str, content: bytes) -> Path: ...
    def delete_video(self, video_id: str) -> None: ...
    def write_metadata(self, video_id: str, metadata: VideoMetadata) -> None: ...
    def read_metadata(self, video_id: str) -> VideoMetadata | None: ...
    def original_path(self, video_id: str) -> Path | None: ...
    def frame_path(self, video_id: str, frame_idx: int) -> Path: ...
    def list_frames(self, video_id: str) -> list[int]: ...
    def mask_path(self, video_id: str, frame_idx: int) -> Path: ...
    def write_keyframes(self, video_id: str, payload: dict) -> None: ...
    def read_keyframes(self, video_id: str) -> dict | None: ...
    def write_track(self, video_id: str, payload: dict) -> None: ...
    def read_track(self, video_id: str) -> dict | None: ...
    def output_path(self, video_id: str) -> Path: ...
    def output_exists(self, video_id: str) -> bool: ...
    def write_render_params(self, video_id: str, payload: dict) -> None: ...
    def read_render_params(self, video_id: str) -> dict | None: ...
    def write_project(self, project_id: str, payload: dict) -> None: ...
    def read_project(self, project_id: str) -> dict | None: ...
    def list_projects(self) -> list[dict]: ...


class FileSystemStorage(Storage):
    """Filesystem backend. Layout (unchanged from Phases 1-6):
    `{root}/uploads/{id}/original.* + meta.json`,
    `frames/{id}/{idx}.jpg`, `masks/{id}/{idx}.png + keyframes.json`,
    `outputs/{id}/track.json + render.json + cropped.mp4`.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ROOT / "data"

    def media_dir(self, name: str) -> Path:
        """Ensure and return a top-level media dir (for static mounts)."""
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_video(self, video_id: str, filename: str, content: bytes) -> Path:
        target = self.root / "uploads" / video_id
        target.mkdir(parents=True, exist_ok=False)
        suffix = Path(filename).suffix.lower() or ".mp4"
        original = target / f"original{suffix}"
        original.write_bytes(content)
        return original

    def delete_video(self, video_id: str) -> None:
        if not _valid_video_id(video_id):
            raise ValueError(f"malformed videoId: {video_id!r}")
        shutil.rmtree(self.root / "uploads" / video_id, ignore_errors=True)

    def write_metadata(self, video_id: str, metadata: VideoMetadata) -> None:
        (self.root / "uploads" / video_id / "meta.json").write_text(
            metadata.model_dump_json(by_alias=True, indent=2))

    def read_metadata(self, video_id: str) -> VideoMetadata | None:
        if not _valid_video_id(video_id):
            return None
        meta_file = self.root / "uploads" / video_id / "meta.json"
        if not meta_file.exists():
            return None
        return VideoMetadata.model_validate_json(meta_file.read_text())

    def original_path(self, video_id: str) -> Path | None:
        if not _valid_video_id(video_id):
            return None
        matches = sorted((self.root / "uploads" / video_id).glob("original.*"))
        return matches[0] if matches else None

    def frame_path(self, video_id: str, frame_idx: int) -> Path:
        return self.root / "frames" / video_id / f"{frame_idx:06d}.jpg"

    def list_frames(self, video_id: str) -> list[int]:
        if not _valid_video_id(video_id):
            return []
        out = []
        for path in (self.root / "frames" / video_id).glob("*.jpg"):
            if path.stem.isdigit():
                out.append(int(path.stem))
        return sorted(out)

    def mask_path(self, video_id: str, frame_idx: int) -> Path:
        return self.root / "masks" / video_id / f"{frame_idx:06d}.png"

    def write_keyframes(self, video_id: str, payload: dict) -> None:
        target = self.root / "masks" / video_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "keyframes.json").write_text(json.dumps(payload, indent=2))

    def read_keyframes(self, video_id: str) -> dict | None:
        if not _valid_video_id(video_id):
            return None
        path = self.root / "masks" / video_id / "keyframes.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def write_track(self, video_id: str, payload: dict) -> None:
        target = self.root / "outputs" / video_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "track.json").write_text(json.dumps(payload, indent=2))

    def read_track(self, video_id: str) -> dict | None:
        if not _valid_video_id(video_id):
            return None
        path = self.root / "outputs" / video_id / "track.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def output_path(self, video_id: str) -> Path:
        return self.root / "outputs" / video_id / "cropped.mp4"

    def output_exists(self, video_id: str) -> bool:
        return _valid_video_id(video_id) and self.output_path(video_id).exists()

    def write_render_params(self, video_id: str, payload: dict) -> None:
        target = self.root / "outputs" / video_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "render.json").write_text(json.dumps(payload, indent=2))

    def read_render_params(self, video_id: str) -> dict | None:
        if not _valid_video_id(video_id):
            return None
        path = self.root / "outputs" / video_id / "render.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def write_project(self, project_id: str, payload: dict) -> None:
        if not _valid_project_id(project_id):
            raise ValueError(f"malformed projectId: {project_id!r}")
        target = self.root / "projects"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{project_id}.json").write_text(json.dumps(payload, indent=2))

    def read_project(self, project_id: str) -> dict | None:
        if not _valid_project_id(project_id):
            return None
        path = self.root / "projects" / f"{project_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_projects(self) -> list[dict]:
        target = self.root / "projects"
        if not target.exists():
            return []
        projects = [json.loads(p.read_text())
                    for p in sorted(target.glob("*.json"))]
        return sorted(projects, key=lambda p: p.get("createdAt", ""))


class MongoStorage:
    """MongoDB backend: prep only. Every op raises until implemented."""

    def __init__(self, url: str, database: str) -> None:
        self._url = url
        self._database = database

    def __getattr__(self, name: str):
        raise NotImplementedError(
            f"MongoDB storage is not implemented yet (called {name}); "
            "set STORAGE_BACKEND=filesystem")


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "mongodb":
        return MongoStorage(url=settings.mongo_url,
                            database=settings.mongo_database)
    return FileSystemStorage()
