"""Phase 6 tests: span-limited re-interpolation + fix endpoint."""

import json
import os
from pathlib import Path

import pytest

from backend.services.track_builder import insert_keyframe, interpolate_boxes
from backend.tests.test_sam3 import _FakeSAM3, _NullSAM3

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


def _box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def test_insert_recomputes_span_only():
    keyframes = [{"frameIdx": 0, "bbox": _box(0.0, 0.0, 0.2, 0.2)},
                 {"frameIdx": 20, "bbox": _box(0.4, 0.4, 0.4, 0.4)}]
    old = interpolate_boxes(keyframes, 30, smooth_window=0)
    new, merged = insert_keyframe(old, keyframes,
                                  {"frameIdx": 10, "bbox": _box(0.1, 0.1, 0.3, 0.3)},
                                  30, smooth_window=0)
    assert [k["frameIdx"] for k in merged] == [0, 10, 20]
    assert new[10] == pytest.approx(_box(0.1, 0.1, 0.3, 0.3))
    assert new[5] == pytest.approx(_box(0.05, 0.05, 0.25, 0.25))
    assert new[21:] == old[21:]  # outside the span: byte-identical


def test_insert_at_edge_extends_hold_range():
    keyframes = [{"frameIdx": 0, "bbox": _box(0.0, 0.0, 0.2, 0.2)},
                 {"frameIdx": 20, "bbox": _box(0.4, 0.4, 0.4, 0.4)}]
    old = interpolate_boxes(keyframes, 30, smooth_window=0)
    new, _ = insert_keyframe(old, keyframes,
                             {"frameIdx": 25, "bbox": _box(0.5, 0.5, 0.5, 0.5)},
                             30, smooth_window=0)
    assert new[:20] == old[:20]
    assert new[29] == pytest.approx(_box(0.5, 0.5, 0.5, 0.5))


def test_insert_smoothing_keeps_outside_identical():
    keyframes = [{"frameIdx": 0, "bbox": _box(0.0, 0.0, 0.2, 0.2)},
                 {"frameIdx": 20, "bbox": _box(0.4, 0.4, 0.4, 0.4)}]
    old = interpolate_boxes(keyframes, 30, smooth_window=5)
    new, _ = insert_keyframe(old, keyframes,
                             {"frameIdx": 10, "bbox": _box(0.9, 0.9, 0.9, 0.9)},
                             30, smooth_window=5)
    assert new[21:] == old[21:]
    assert new[10] != pytest.approx(old[10])


def test_insert_guards():
    keyframes = [{"frameIdx": 0, "bbox": _box(0, 0, 0.1, 0.1)}]
    boxes = interpolate_boxes(keyframes, 10, smooth_window=0)
    with pytest.raises(ValueError):
        insert_keyframe(boxes, keyframes, {"frameIdx": 0, "bbox": _box(0, 0, 0.1, 0.1)}, 10)
    with pytest.raises(ValueError):
        insert_keyframe(boxes, keyframes, {"frameIdx": 10, "bbox": _box(0, 0, 0.1, 0.1)}, 10)
    with pytest.raises(ValueError):
        insert_keyframe(boxes, keyframes, {"frameIdx": 5, "bbox": None}, 10)
    with pytest.raises(ValueError):
        insert_keyframe(boxes[:-1], keyframes,
                        {"frameIdx": 5, "bbox": _box(0, 0, 0.1, 0.1)}, 10)


def _upload(client) -> dict:
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    return resp.json()


def _segment_and_track(client, video_id: str, num_samples: int = 3) -> None:
    seg = client.post(f"/api/videos/{video_id}/segment",
                      json={"prompt": "sq", "numSamples": num_samples})
    assert seg.status_code == 200
    track = client.post(f"/api/videos/{video_id}/track", json={"prompt": "sq"})
    assert track.status_code == 200


def test_fix_flow_rebuilds_span_only(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    _segment_and_track(client, video_id, num_samples=3)  # indices [0, 15, 29]
    before = client.get(f"/api/videos/{video_id}/track").json()["interpolatedBoxes"]
    resp = client.post(f"/api/videos/{video_id}/keyframes", json={"frameIdx": 7})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["sam3Calls"] == 1
    assert payload["keyframe"]["origin"] == "fix"
    assert payload["trackRebuilt"] is True
    assert payload["rerendered"] is False
    stored = json.loads((tmp_path / "masks" / video_id / "keyframes.json").read_text())
    assert [k["frameIdx"] for k in stored["keyframes"]] == [0, 7, 15, 29]
    after = client.get(f"/api/videos/{video_id}/track").json()["interpolatedBoxes"]
    assert after[16:] == before[16:]  # outside [0, 15]: untouched
    assert (tmp_path / "frames" / video_id / "000007.jpg").exists()
    assert (tmp_path / "masks" / video_id / "000007.png").exists()


def test_fix_guards(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    total = body["metadata"]["totalFrames"]
    assert client.post(f"/api/videos/{video_id}/keyframes",
                       json={"frameIdx": 1}).status_code == 404
    assert client.post("/api/videos/" + "f" * 32 + "/keyframes",
                       json={"frameIdx": 1}).status_code == 404
    _segment_and_track(client, video_id, num_samples=2)  # indices [0, 29]
    assert client.post(f"/api/videos/{video_id}/keyframes",
                       json={"frameIdx": 0}).status_code == 409
    assert client.post(f"/api/videos/{video_id}/keyframes",
                       json={"frameIdx": total}).status_code == 400
    assert client.post(f"/api/videos/{video_id}/keyframes",
                       json={"frameIdx": -1}).status_code == 422


def test_fix_miss_keeps_track_untouched(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    _segment_and_track(client, video_id, num_samples=2)
    before = (tmp_path / "outputs" / video_id / "track.json").read_bytes()
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _NullSAM3)
    resp = client.post(f"/api/videos/{video_id}/keyframes", json={"frameIdx": 10})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["sam3Calls"] == 1
    assert payload["keyframe"]["bbox"] is None
    assert payload["trackRebuilt"] is False
    assert (tmp_path / "outputs" / video_id / "track.json").read_bytes() == before
    stored = json.loads((tmp_path / "masks" / video_id / "keyframes.json").read_text())
    assert [k["frameIdx"] for k in stored["keyframes"]] == [0, 10, 29]


def test_fix_without_track_skips_rebuild(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    client.post(f"/api/videos/{video_id}/segment",
                json={"prompt": "sq", "numSamples": 2})
    resp = client.post(f"/api/videos/{video_id}/keyframes", json={"frameIdx": 10})
    assert resp.status_code == 200
    assert resp.json()["trackRebuilt"] is False
    assert not (tmp_path / "outputs" / video_id / "track.json").exists()


def test_fix_auto_rerenders_with_stored_params(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    _segment_and_track(client, video_id, num_samples=2)
    render = client.post(f"/api/videos/{video_id}/render",
                         json={"trackId": video_id, "padding": 0,
                               "aspectRatio": "1:1"})
    assert render.status_code == 200
    params_path = tmp_path / "outputs" / video_id / "render.json"
    assert json.loads(params_path.read_text())["aspectRatio"] == "1:1"
    cropped = tmp_path / "outputs" / video_id / "cropped.mp4"
    os.utime(cropped, (1000000000, 1000000000))
    resp = client.post(f"/api/videos/{video_id}/keyframes", json={"frameIdx": 10})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["rerendered"] is True
    assert payload["outputUrl"] == f"/outputs/{video_id}/cropped.mp4"
    assert cropped.stat().st_mtime > 1000000000
