"""Phase 7 tests: storage backends + env selection."""

import json

import pydantic
import pytest

from backend.config import get_settings
from backend.models.schemas import VideoMetadata
from backend.services.storage import (
    FileSystemStorage, MongoStorage, get_storage)

VID = "f" * 32


def _meta() -> VideoMetadata:
    return VideoMetadata(video_id=VID, filename="clip.mp4", width=64,
                         height=48, fps=30.0, duration=1.0, total_frames=30,
                         codec="h264")


def test_filesystem_video_roundtrip(tmp_path):
    store = FileSystemStorage(tmp_path)
    original = store.create_video(VID, "clip.mp4", b"data")
    assert original == tmp_path / "uploads" / VID / "original.mp4"
    assert original.read_bytes() == b"data"
    assert store.original_path(VID) == original
    store.write_metadata(VID, _meta())
    assert store.read_metadata(VID) == _meta()
    store.delete_video(VID)
    assert not (tmp_path / "uploads" / VID).exists()
    assert store.read_metadata(VID) is None
    store.delete_video(VID)  # missing dir is a no-op


def test_filesystem_unknown_and_malformed_ids(tmp_path):
    store = FileSystemStorage(tmp_path)
    assert store.read_metadata("0" * 32) is None
    assert store.read_metadata("nope") is None
    assert store.original_path("nope") is None
    assert store.list_frames("nope") == []
    assert store.read_keyframes("nope") is None
    assert store.read_track("nope") is None
    assert store.read_render_params("nope") is None
    assert store.output_exists("nope") is False
    with pytest.raises(ValueError):
        store.delete_video("nope")


def test_filesystem_frames_masks_track_output(tmp_path):
    store = FileSystemStorage(tmp_path)
    assert store.frame_path(VID, 7) == tmp_path / "frames" / VID / "000007.jpg"
    assert store.mask_path(VID, 7) == tmp_path / "masks" / VID / "000007.png"
    assert store.output_path(VID) == tmp_path / "outputs" / VID / "cropped.mp4"
    assert store.output_exists(VID) is False
    assert store.list_frames(VID) == []
    assert store.read_keyframes(VID) is None
    assert store.read_track(VID) is None
    assert store.read_render_params(VID) is None
    frames_dir = tmp_path / "frames" / VID
    frames_dir.mkdir(parents=True)
    (frames_dir / "000007.jpg").write_bytes(b"j")
    (frames_dir / "000003.jpg").write_bytes(b"j")
    (frames_dir / "cover.jpg").write_bytes(b"j")
    assert store.list_frames(VID) == [3, 7]
    store.write_keyframes(VID, {"prompt": "p"})
    store.write_track(VID, {"boxes": []})
    store.write_render_params(VID, {"padding": 0.1})
    assert store.read_keyframes(VID) == {"prompt": "p"}
    assert store.read_track(VID) == {"boxes": []}
    assert store.read_render_params(VID) == {"padding": 0.1}
    assert json.loads(
        (tmp_path / "masks" / VID / "keyframes.json").read_text()) == {
            "prompt": "p"}
    store.output_path(VID).write_bytes(b"v")
    assert store.output_exists(VID) is True
    assert store.media_dir("frames") == tmp_path / "frames"


def test_filesystem_projects(tmp_path):
    store = FileSystemStorage(tmp_path)
    assert store.list_projects() == []
    assert store.read_project("0" * 32) is None
    assert store.read_project("nope") is None
    with pytest.raises(ValueError):
        store.write_project("nope", {})
    pid, pid2 = "a" * 32, "b" * 32
    store.write_project(pid, {"projectId": pid, "name": "P",
                              "createdAt": "2026-01-02T00:00:00+00:00",
                              "videoIds": []})
    store.write_project(pid2, {"projectId": pid2, "name": "Q",
                               "createdAt": "2026-01-01T00:00:00+00:00",
                               "videoIds": ["v"]})
    assert store.read_project(pid)["name"] == "P"
    assert [p["projectId"] for p in store.list_projects()] == [pid2, pid]
    assert (tmp_path / "projects" / f"{pid}.json").exists()


def test_get_storage_defaults_to_filesystem(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_settings.cache_clear()
    get_storage.cache_clear()
    try:
        store = get_storage()
        assert isinstance(store, FileSystemStorage)
        assert store.root.name == "data"
    finally:
        get_settings.cache_clear()
        get_storage.cache_clear()


def test_get_storage_mongodb_selected_but_unimplemented(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
    get_settings.cache_clear()
    get_storage.cache_clear()
    try:
        store = get_storage()
        assert isinstance(store, MongoStorage)
        with pytest.raises(NotImplementedError):
            store.read_metadata(VID)
    finally:
        get_settings.cache_clear()
        get_storage.cache_clear()


def test_get_storage_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    get_settings.cache_clear()
    get_storage.cache_clear()
    try:
        with pytest.raises(pydantic.ValidationError):
            get_storage()
    finally:
        get_settings.cache_clear()
        get_storage.cache_clear()
