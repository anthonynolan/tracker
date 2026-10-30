"""Phase 11 tests: MongoStorage conformance (needs local mongod; else skip)."""

from pathlib import Path

import pytest

pytest.importorskip("pymongo")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.services.storage as storage_module
from backend.config import get_settings
from backend.models.schemas import VideoMetadata
from backend.routers import media, projects, videos
from backend.services.storage import MongoStorage
from backend.tests.test_sam3 import _FakeSAM3

TEST_URL = "mongodb://localhost:27017/"
TEST_DB = "tracker_test"
FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"

mongo_app = FastAPI()
mongo_app.include_router(videos.router)
mongo_app.include_router(projects.router)
mongo_app.include_router(media.router)


def _meta(vid):
    return VideoMetadata(video_id=vid, filename="clip.mp4", width=64,
                         height=48, fps=30.0, duration=1.0, total_frames=30,
                         codec="h264")


@pytest.fixture(scope="module")
def mongo_store(tmp_path_factory):
    from pymongo import MongoClient

    try:
        MongoClient(TEST_URL, serverSelectionTimeoutMS=2000).server_info()
    except Exception:
        pytest.skip("needs local mongod on :27017")
    store = MongoStorage(url=TEST_URL, database=TEST_DB,
                         cache_root=tmp_path_factory.mktemp("mongocache"))
    yield store
    store.drop_database()


@pytest.fixture
def mongo_client(mongo_store, monkeypatch):
    monkeypatch.setattr(storage_module, "get_storage", lambda: mongo_store)
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        yield TestClient(mongo_app)
    finally:
        get_settings.cache_clear()


def test_mongo_video_roundtrip(mongo_store):
    vid = "d" * 32
    original = mongo_store.create_video(vid, "clip.mp4", b"data")
    assert original.name == "original.mp4"
    assert original.read_bytes() == b"data"
    assert mongo_store.original_path(vid) == original
    mongo_store.write_metadata(vid, _meta(vid))
    assert mongo_store.read_metadata(vid) == _meta(vid)
    mongo_store.delete_video(vid)
    assert mongo_store.original_path(vid) is None
    assert mongo_store.read_metadata(vid) is None
    mongo_store.delete_video(vid)  # missing is a no-op


def test_mongo_miss_semantics(mongo_store):
    assert mongo_store.read_metadata("0" * 32) is None
    assert mongo_store.read_metadata("nope") is None
    assert mongo_store.original_path("nope") is None
    assert mongo_store.list_frames("nope") == []
    assert mongo_store.read_keyframes("nope") is None
    assert mongo_store.read_track("nope") is None
    assert mongo_store.read_render_params("nope") is None
    assert mongo_store.read_project("nope") is None
    assert mongo_store.output_exists("nope") is False
    assert mongo_store.read_media("frames", "nope", "000001.jpg") is None
    assert mongo_store.read_media("nope", "0" * 32, "x.jpg") is None
    with pytest.raises(ValueError):
        mongo_store.delete_video("nope")
    with pytest.raises(ValueError):
        mongo_store.write_project("nope", {})
    with pytest.raises(ValueError):
        mongo_store.sync_media("nope", "0" * 32, "x")
    with pytest.raises(ValueError):
        mongo_store.sync_media("frames", "nope", "x")


def test_mongo_frames_masks_track_output(mongo_store):
    vid = "c" * 32
    assert mongo_store.list_frames(vid) == []
    assert mongo_store.read_keyframes(vid) is None
    assert mongo_store.read_track(vid) is None
    assert mongo_store.read_render_params(vid) is None
    assert mongo_store.output_exists(vid) is False
    for idx in (7, 3):
        path = mongo_store.frame_path(vid, idx)
        assert path.name == f"{idx:06d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"j" + bytes([idx]))
        mongo_store.sync_media("frames", vid, path.name)
    assert mongo_store.list_frames(vid) == [3, 7]
    mask = mongo_store.mask_path(vid, 3)
    mask.parent.mkdir(parents=True, exist_ok=True)
    mask.write_bytes(b"mask-bytes")
    mongo_store.sync_media("masks", vid, mask.name)
    data, total = mongo_store.read_media("frames", vid, "000003.jpg")
    assert (data, total) == (b"j\x03", 2)
    data, total = mongo_store.read_media("masks", vid, "000003.png", 0, 3)
    assert (data, total) == (b"mask", 10)
    assert mongo_store.read_media("frames", vid, "missing.jpg") is None
    mongo_store.write_keyframes(vid, {"prompt": "p"})
    mongo_store.write_track(vid, {"boxes": []})
    mongo_store.write_render_params(vid, {"padding": 0.1})
    assert mongo_store.read_keyframes(vid) == {"prompt": "p"}
    assert mongo_store.read_track(vid) == {"boxes": []}
    assert mongo_store.read_render_params(vid) == {"padding": 0.1}
    out = mongo_store.output_path(vid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"video-bytes")
    mongo_store.sync_media("outputs", vid, out.name)
    assert mongo_store.output_exists(vid) is True


def test_mongo_projects(mongo_store):
    pid, pid2 = "a" * 32, "b" * 32
    mongo_store.write_project(pid, {"projectId": pid, "name": "P",
                                    "createdAt": "2026-01-02T00:00:00+00:00",
                                    "videoIds": []})
    mongo_store.write_project(pid2, {"projectId": pid2, "name": "Q",
                                     "createdAt": "2026-01-01T00:00:00+00:00",
                                     "videoIds": ["v"]})
    assert mongo_store.read_project(pid)["name"] == "P"
    assert [p["projectId"] for p in mongo_store.list_projects()] == [pid2, pid]


def test_mongo_gridfs_is_truth_across_instances(mongo_store, tmp_path):
    vid = "b" * 32
    mongo_store.write_metadata(vid, _meta(vid))
    path = mongo_store.frame_path(vid, 5)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpeg-bytes")
    mongo_store.sync_media("frames", vid, path.name)
    fresh = MongoStorage(url=TEST_URL, database=TEST_DB,
                         cache_root=tmp_path / "freshcache")
    assert fresh.read_metadata(vid) == _meta(vid)
    assert fresh.list_frames(vid) == [5]
    assert fresh.frame_path(vid, 5).read_bytes() == b"jpeg-bytes"


def test_parse_range():
    assert media.parse_range(None, 100) is None
    assert media.parse_range("bytes=0-99", 100) == (0, 99)
    assert media.parse_range("bytes=10-", 100) == (10, 99)
    assert media.parse_range("bytes=0-999", 100) == (0, 99)
    assert media.parse_range("bytes=-10", 100) == (90, 99)
    assert media.parse_range("bytes=100-200", 100) is None
    assert media.parse_range("bytes=50-40", 100) is None
    assert media.parse_range("bytes=0-0,2-2", 100) is None
    assert media.parse_range("items=0-1", 100) is None
    assert media.parse_range("bytes=abc", 100) is None


def test_mongo_full_flow(mongo_client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    with open(FIXTURE, "rb") as fh:
        up = mongo_client.post("/api/videos/upload",
                               files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert up.status_code == 200, up.text
    vid = up.json()["videoId"]
    assert mongo_client.get(f"/api/videos/{vid}/status").status_code == 200
    seg = mongo_client.post(f"/api/videos/{vid}/segment",
                            json={"prompt": "sq", "numSamples": 2})
    assert seg.status_code == 200, seg.text
    assert seg.json()["sam3Calls"] == 2
    assert mongo_client.post(f"/api/videos/{vid}/track",
                             json={"prompt": "sq"}).status_code == 200
    assert len(mongo_client.get(
        f"/api/videos/{vid}/track").json()["interpolatedBoxes"]) > 0
    assert mongo_client.post(f"/api/videos/{vid}/render",
                             json={"trackId": vid, "padding": 0.1}
                             ).status_code == 200
    out = mongo_client.get(f"/api/videos/{vid}/output")
    assert out.status_code == 200 and out.headers["content-type"] == "video/mp4"
    frame = mongo_client.get(f"/frames/{vid}/000000.jpg")
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert len(frame.content) > 0
    assert mongo_client.get(f"/frames/{vid}/missing.jpg").status_code == 404
    assert mongo_client.get(f"/api/videos/{vid}/status").status_code == 200
    ranged = mongo_client.get(f"/outputs/{vid}/cropped.mp4",
                              headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert ranged.headers["Content-Range"].startswith("bytes 0-99/")
    assert len(ranged.content) == 100
    assert mongo_client.get("/nope/x/y").status_code == 404
    projects = mongo_client.get("/api/projects").json()["projects"]
    assert any(vid in p["videoIds"] for p in projects)
