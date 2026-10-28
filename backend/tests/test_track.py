"""Phase 4 tests: interpolation math + track endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.services.track_builder import interpolate_boxes
from backend.tests.test_sam3 import _FakeSAM3, _NullSAM3

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.video_service.DATA_DIR", tmp_path)
    monkeypatch.setattr("backend.services.frame_service.DATA_DIR", tmp_path)
    monkeypatch.setattr("backend.routers.videos.DATA_DIR", tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        from backend.main import app

        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def _box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def test_midpoint_and_edges():
    keyframes = [{"frameIdx": 0, "bbox": _box(0.0, 0.0, 0.2, 0.2)},
                 {"frameIdx": 10, "bbox": _box(0.1, 0.1, 0.4, 0.4)}]
    boxes = interpolate_boxes(keyframes, 11, smooth_window=0)
    assert len(boxes) == 11
    assert boxes[0] == pytest.approx(_box(0.0, 0.0, 0.2, 0.2))
    assert boxes[5] == pytest.approx(_box(0.05, 0.05, 0.3, 0.3))
    assert boxes[10] == pytest.approx(_box(0.1, 0.1, 0.4, 0.4))


def test_holds_outside_range_and_skips_misses():
    keyframes = [{"frameIdx": 2, "bbox": None},
                 {"frameIdx": 4, "bbox": _box(0.2, 0.2, 0.2, 0.2)},
                 {"frameIdx": 6, "bbox": _box(0.4, 0.4, 0.4, 0.4)}]
    boxes = interpolate_boxes(keyframes, 9, smooth_window=0)
    assert boxes[0] == boxes[3] == pytest.approx(_box(0.2, 0.2, 0.2, 0.2))
    assert boxes[5] == pytest.approx(_box(0.3, 0.3, 0.3, 0.3))
    assert boxes[8] == pytest.approx(_box(0.4, 0.4, 0.4, 0.4))


def test_single_keyframe_constant_and_no_valid_raises():
    keyframes = [{"frameIdx": 7, "bbox": _box(0.1, 0.2, 0.3, 0.4)}]
    boxes = interpolate_boxes(keyframes, 4, smooth_window=0)
    assert all(b == pytest.approx(_box(0.1, 0.2, 0.3, 0.4)) for b in boxes)
    with pytest.raises(ValueError):
        interpolate_boxes([{"frameIdx": 0, "bbox": None}], 4)


def test_smoothing_dampens_spike():
    keyframes = [{"frameIdx": i,
                  "bbox": _box(1.0 if i == 2 else 0.0, 0.0, 0.1, 0.1)}
                 for i in range(5)]
    raw = interpolate_boxes(keyframes, 5, smooth_window=0)
    assert raw[2]["x"] == pytest.approx(1.0)
    smooth = interpolate_boxes(keyframes, 5, smooth_window=3)
    assert smooth[2]["x"] == pytest.approx(1 / 3)
    assert all(0.0 <= b[k] <= 1.0 for b in smooth for k in b)


def _upload(client) -> dict:
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    return resp.json()


def test_track_flow(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    total = body["metadata"]["totalFrames"]
    seg = client.post(f"/api/videos/{video_id}/segment",
                      json={"prompt": "sq", "numSamples": 3})
    assert seg.status_code == 200
    resp = client.post(f"/api/videos/{video_id}/track", json={"prompt": "sq"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["trackId"] == video_id
    assert payload["numFrames"] == total and payload["keyframeCount"] == 3
    assert (tmp_path / "outputs" / video_id / "track.json").exists()
    fetched = client.get(f"/api/videos/{video_id}/track")
    assert fetched.status_code == 200
    assert len(fetched.json()["interpolatedBoxes"]) == total


def test_track_guards(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    assert client.post(f"/api/videos/{video_id}/track",
                       json={"prompt": "sq"}).status_code == 404
    assert client.get(f"/api/videos/{video_id}/track").status_code == 404
    client.post(f"/api/videos/{video_id}/segment",
                json={"prompt": "sq", "numSamples": 2})
    assert client.post(f"/api/videos/{video_id}/track",
                       json={"prompt": "other"}).status_code == 400


def test_track_rejects_all_miss(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _NullSAM3)
    body = _upload(client)
    client.post(f"/api/videos/{body['videoId']}/segment",
                json={"prompt": "nothing", "numSamples": 2})
    resp = client.post(f"/api/videos/{body['videoId']}/track",
                       json={"prompt": "nothing"})
    assert resp.status_code == 400
