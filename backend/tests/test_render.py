"""Phase 5 tests: crop math + render endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.services.render_service import (
    _has_audio,
    compute_crop_window,
    crop_position,
    parse_aspect_ratio,
)
from backend.services.video_service import probe_metadata
from backend.tests.test_sam3 import _FakeSAM3

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"
FIXTURE_AV = Path(__file__).parent / "fixtures" / "tiny_av.mp4"


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


def test_window_math_padding_aspect_clamp():
    boxes = [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.25}]
    assert compute_crop_window(boxes, 100, 200, padding=0.1) == (54, 54)
    assert compute_crop_window(boxes, 100, 200, padding=0.0,
                               aspect_ratio="1:1") == (50, 50)
    # 2:1 on a square content box overflows -> scaled to fit, aspect kept.
    assert compute_crop_window(boxes, 100, 200, padding=0.1,
                               aspect_ratio="2:1") == (100, 50)


def test_window_rejects_bad_input():
    with pytest.raises(ValueError):
        compute_crop_window([], 100, 100)
    with pytest.raises(ValueError):
        compute_crop_window([{"x": 0, "y": 0, "w": 0.1, "h": 0.1}],
                            100, 100, padding=-0.5)
    assert parse_aspect_ratio(None) is None
    assert parse_aspect_ratio("") is None
    assert parse_aspect_ratio("16:9") == pytest.approx(16 / 9)
    with pytest.raises(ValueError):
        parse_aspect_ratio("wide")
    with pytest.raises(ValueError):
        parse_aspect_ratio("16:0")


def test_position_centers_and_clamps():
    assert crop_position({"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2},
                         100, 100, 40, 40) == (30, 30)
    assert crop_position({"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1},
                         100, 100, 40, 40) == (0, 0)
    assert crop_position({"x": 0.9, "y": 0.9, "w": 0.1, "h": 0.1},
                         100, 100, 40, 40) == (60, 60)


def _upload(client, fixture=FIXTURE) -> dict:
    with open(fixture, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": (fixture.name, fh, "video/mp4")})
    assert resp.status_code == 200
    return resp.json()


def _segment_and_track(client, video_id: str) -> None:
    seg = client.post(f"/api/videos/{video_id}/segment",
                      json={"prompt": "sq", "numSamples": 2})
    assert seg.status_code == 200
    track = client.post(f"/api/videos/{video_id}/track", json={"prompt": "sq"})
    assert track.status_code == 200


def test_render_flow_and_output_serving(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    _segment_and_track(client, video_id)
    resp = client.post(f"/api/videos/{video_id}/render",
                       json={"trackId": video_id, "padding": 0,
                             "aspectRatio": "1:1"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["outputUrl"] == f"/outputs/{video_id}/cropped.mp4"
    assert payload["width"] == payload["height"] and payload["width"] % 2 == 0
    assert payload["numFrames"] == body["metadata"]["totalFrames"]
    cropped = tmp_path / "outputs" / video_id / "cropped.mp4"
    assert cropped.exists()
    probed = probe_metadata(cropped)
    assert (probed["width"], probed["height"]) == (payload["width"],
                                                   payload["height"])
    served = client.get(f"/api/videos/{video_id}/output")
    assert served.status_code == 200
    assert served.headers["content-type"] == "video/mp4"


def test_render_keeps_audio(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client, FIXTURE_AV)
    video_id = body["videoId"]
    _segment_and_track(client, video_id)
    resp = client.post(f"/api/videos/{video_id}/render",
                       json={"trackId": video_id})
    assert resp.status_code == 200, resp.text
    assert _has_audio(tmp_path / "outputs" / video_id / "cropped.mp4")


def test_render_guards(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    render = {"trackId": video_id}
    assert client.post(f"/api/videos/{video_id}/render",
                       json=render).status_code == 404
    _segment_and_track(client, video_id)
    assert client.post(f"/api/videos/{video_id}/render",
                       json={"trackId": "f" * 32}).status_code == 400
    assert client.post(f"/api/videos/{video_id}/render",
                       json={**render, "aspectRatio": "wide"}).status_code == 400
    assert client.post(f"/api/videos/{video_id}/render",
                       json={**render, "padding": -1}).status_code == 422
    assert client.post("/api/videos/" + "f" * 32 + "/render",
                       json=render).status_code == 404
