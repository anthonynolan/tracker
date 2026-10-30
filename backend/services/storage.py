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
from urllib.parse import quote

import gridfs
from pymongo import MongoClient

from backend.config import ROOT, get_settings
from backend.models.schemas import VideoMetadata

_VIDEO_ID_RE = re.compile(r"[0-9a-f]{32}")


def _valid_video_id(video_id: str) -> bool:
    return _VIDEO_ID_RE.fullmatch(video_id) is not None


# Project ids share the uuid-hex shape.
_valid_project_id = _valid_video_id
_valid_id = _valid_video_id


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
    def sync_media(self, kind: str, video_id: str, name: str) -> None: ...


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

    def sync_media(self, kind: str, video_id: str, name: str) -> None:
        """No-op on filesystem: media is already on disk."""


class MongoStorage(Storage):
    """MongoDB backend. Documents per concern (`videos`, `keyframes`,
    `tracks`, `renders`, `projects` keyed by id); all binaries in the
    `media` GridFS bucket as `{kind}/{video_id}/{name}` with
    `{videoId, kind}` metadata. A write-through cache under
    `.mongo-cache/{database}/` mirrors the filesystem layout so path-based
    callers (ffmpeg, PIL, FileResponse) work unchanged.
    """

    KINDS = ("uploads", "frames", "masks", "outputs")

    def __init__(self, url: str, database: str,
                 cache_root: Path | None = None) -> None:
        self._client = MongoClient(url, serverSelectionTimeoutMS=5000)
        self._database_name = database
        self._db = self._client[database]
        self._media = gridfs.GridFS(self._db, collection="media")
        self.cache = (cache_root or ROOT / "data" / ".mongo-cache") / database

    @property
    def database_name(self) -> str:
        return self._database_name

    def drop_database(self) -> None:
        """Drop the database + cache (tests, import --drop)."""
        self._client.drop_database(self._database_name)
        shutil.rmtree(self.cache, ignore_errors=True)

    def _grid_name(self, kind: str, video_id: str, name: str) -> str:
        return f"{kind}/{video_id}/{name}"

    def _cache_path(self, kind: str, video_id: str, name: str) -> Path:
        return self.cache / kind / video_id / name

    def _ensure_local(self, kind: str, video_id: str, name: str) -> Path:
        """Download-through: return the cache path, fetching on miss."""
        path = self._cache_path(kind, video_id, name)
        if not path.exists():
            grid = self._media.find_one(
                {"filename": self._grid_name(kind, video_id, name)})
            if grid is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(grid.read())
        return path

    def _put(self, kind: str, video_id: str, name: str) -> None:
        for old in self._media.find(
                {"filename": self._grid_name(kind, video_id, name)}):
            self._media.delete(old._id)
        with open(self._cache_path(kind, video_id, name), "rb") as fh:
            self._media.put(fh, filename=self._grid_name(kind, video_id, name),
                            metadata={"videoId": video_id, "kind": kind})

    def _read_doc(self, collection: str, doc_id: str) -> dict | None:
        if not _valid_id(doc_id):
            return None
        doc = self._db[collection].find_one({"_id": doc_id})
        if doc is None:
            return None
        return {k: v for k, v in doc.items() if k != "_id"}

    def _write_doc(self, collection: str, doc_id: str, payload: dict) -> None:
        self._db[collection].replace_one({"_id": doc_id},
                                         {"_id": doc_id, **payload},
                                         upsert=True)

    def create_video(self, video_id: str, filename: str, content: bytes) -> Path:
        suffix = Path(filename).suffix.lower() or ".mp4"
        return self.stage_media("uploads", video_id, f"original{suffix}",
                                content)

    def stage_media(self, kind: str, video_id: str, name: str,
                    data: bytes) -> Path:
        """Write bytes to cache + GridFS (import path)."""
        if kind not in self.KINDS:
            raise ValueError(f"unknown media kind: {kind!r}")
        if not _valid_id(video_id):
            raise ValueError(f"malformed videoId: {video_id!r}")
        path = self._cache_path(kind, video_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._put(kind, video_id, name)
        return path

    def delete_video(self, video_id: str) -> None:
        if not _valid_id(video_id):
            raise ValueError(f"malformed videoId: {video_id!r}")
        for old in self._media.find({"metadata.videoId": video_id,
                                     "metadata.kind": "uploads"}):
            self._media.delete(old._id)
        self._db["videos"].delete_one({"_id": video_id})
        shutil.rmtree(self.cache / "uploads" / video_id, ignore_errors=True)

    def write_metadata(self, video_id: str, metadata: VideoMetadata) -> None:
        self._write_doc("videos", video_id, metadata.model_dump(by_alias=True))

    def read_metadata(self, video_id: str) -> VideoMetadata | None:
        doc = self._read_doc("videos", video_id)
        return VideoMetadata(**doc) if doc is not None else None

    def original_path(self, video_id: str) -> Path | None:
        if not _valid_id(video_id):
            return None
        found = list(self._media.find(
            {"metadata.videoId": video_id,
             "metadata.kind": "uploads"}).sort("filename").limit(1))
        if not found:
            return None
        return self._ensure_local(
            "uploads", video_id, found[0].filename.rsplit("/", 1)[-1])

    def frame_path(self, video_id: str, frame_idx: int) -> Path:
        return self._ensure_local("frames", video_id, f"{frame_idx:06d}.jpg")

    def list_frames(self, video_id: str) -> list[int]:
        if not _valid_id(video_id):
            return []
        out = []
        for grid in self._media.find({"metadata.videoId": video_id,
                                      "metadata.kind": "frames"}):
            name = grid.filename.rsplit("/", 1)[-1]
            if name.endswith(".jpg") and name[:-4].isdigit():
                out.append(int(name[:-4]))
        return sorted(out)

    def mask_path(self, video_id: str, frame_idx: int) -> Path:
        return self._ensure_local("masks", video_id, f"{frame_idx:06d}.png")

    def write_keyframes(self, video_id: str, payload: dict) -> None:
        self._write_doc("keyframes", video_id, payload)

    def read_keyframes(self, video_id: str) -> dict | None:
        return self._read_doc("keyframes", video_id)

    def write_track(self, video_id: str, payload: dict) -> None:
        self._write_doc("tracks", video_id, payload)

    def read_track(self, video_id: str) -> dict | None:
        return self._read_doc("tracks", video_id)

    def output_path(self, video_id: str) -> Path:
        return self._ensure_local("outputs", video_id, "cropped.mp4")

    def output_exists(self, video_id: str) -> bool:
        return (_valid_id(video_id) and self._media.find_one(
            {"metadata.videoId": video_id,
             "metadata.kind": "outputs"}) is not None)

    def write_render_params(self, video_id: str, payload: dict) -> None:
        self._write_doc("renders", video_id, payload)

    def read_render_params(self, video_id: str) -> dict | None:
        return self._read_doc("renders", video_id)

    def write_project(self, project_id: str, payload: dict) -> None:
        if not _valid_id(project_id):
            raise ValueError(f"malformed projectId: {project_id!r}")
        self._write_doc("projects", project_id, payload)

    def read_project(self, project_id: str) -> dict | None:
        return self._read_doc("projects", project_id)

    def list_projects(self) -> list[dict]:
        return sorted(
            ({k: v for k, v in doc.items() if k != "_id"}
             for doc in self._db["projects"].find()),
            key=lambda p: p.get("createdAt", ""))

    def sync_media(self, kind: str, video_id: str, name: str) -> None:
        if kind not in self.KINDS:
            raise ValueError(f"unknown media kind: {kind!r}")
        if not _valid_id(video_id):
            raise ValueError(f"malformed videoId: {video_id!r}")
        self._put(kind, video_id, name)

    def read_media(self, kind: str, video_id: str, name: str,
                   start: int | None = None,
                   end: int | None = None) -> tuple[bytes, int] | None:
        """GridFS bytes (+ total) for serving; slice [start, end] inclusive."""
        if kind not in self.KINDS or not _valid_id(video_id):
            return None
        grid = self._media.find_one(
            {"filename": self._grid_name(kind, video_id, name)})
        if grid is None:
            return None
        total = grid.length
        grid.seek(start or 0)
        if end is None:
            return grid.read(), total
        return grid.read(end - (start or 0) + 1), total


def build_mongo_url(settings) -> str:
    """Connection string: MONGO_URL override, else Atlas SRV from
    MONGODB_* parts (password quoted, authSource=admin), else localhost."""
    if settings.mongo_url:
        return settings.mongo_url
    if settings.mongodb_host:
        user = quote((settings.mongodb_user or "").strip(), safe="")
        password = quote(settings.mongodb_password.get_secret_value()
                         if settings.mongodb_password else "", safe="")
        host = settings.mongodb_host.strip().rstrip("/")
        auth = f"{user}:{password}@" if user or password else ""
        return (f"mongodb+srv://{auth}{host}"
                "?authSource=admin&retryWrites=true&w=majority")
    return "mongodb://localhost:27017/"


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "mongodb":
        return MongoStorage(url=build_mongo_url(settings),
                            database=settings.mongo_database)
    return FileSystemStorage()
