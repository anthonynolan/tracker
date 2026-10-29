"""Phase 8 tests: selective re-segment, GET segment, SSE stream."""

import asyncio
import json
from pathlib import Path

import pytest

from backend.services.sam3_service import Segmentation
from backend.tests.test_sam3 import _FakeSAM3

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


class _PromptSAM3(_FakeSAM3):
    async def segment(self, image_path, text_prompt):
        type(self).calls.append((image_path, text_prompt))
        x = 0.5 if text_prompt == "circle" else 0.1
        return Segmentation(bbox={"x": x, "y": 0.2, "w": 0.3, "h": 0.4},
                            mask_raster=bytes(32 * 24), width=32, height=24)


class _SlowSAM3(_FakeSAM3):
    in_flight = 0
    max_in_flight = 0

    def __init__(self, api_key: str = "", **kwargs) -> None:
        super().__init__(api_key, **kwargs)
        type(self).in_flight = 0
        type(self).max_in_flight = 0

    async def segment(self, image_path, text_prompt):
        type(self).in_flight += 1
        type(self).max_in_flight = max(type(self).max_in_flight,
                                       type(self).in_flight)
        try:
            await asyncio.sleep(0.05)
            return await super().segment(image_path, text_prompt)
        finally:
            type(self).in_flight -= 1


class _FailSecond(_FakeSAM3):
    async def segment(self, image_path, text_prompt):
        type(self).calls.append((image_path, text_prompt))
        if len(type(self).calls) == 2:
            raise ValueError("boom")
        return Segmentation(bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                            mask_raster=bytes(32 * 24), width=32, height=24)


def _upload(client) -> dict:
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _segment(client, video_id, prompt="sq", n=3):
    resp = client.post(f"/api/videos/{video_id}/segment",
                       json={"prompt": prompt, "numSamples": n})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_get_segment_roundtrip_and_guards(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    vid = _upload(client)["videoId"]
    assert client.get(f"/api/videos/{vid}/segment").status_code == 404
    seg = _segment(client, vid)
    fetched = client.get(f"/api/videos/{vid}/segment")
    assert fetched.status_code == 200
    assert fetched.json() == {"keyframes": seg["keyframes"],
                              "sam3Calls": seg["sam3Calls"]}
    assert client.get("/api/videos/" + "0" * 32 + "/segment").status_code == 404


def test_selected_partial_keeps_top_prompt(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _PromptSAM3)
    vid = _upload(client)["videoId"]
    seg = _segment(client, vid, "sq", 3)
    idx = [k["frameIdx"] for k in seg["keyframes"]]
    resp = client.post(f"/api/videos/{vid}/segment/selected",
                       json={"prompt": "circle", "frameIndices": [idx[1]]})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["sam3Calls"] == 1
    # Fake resets per request instance: exactly 1 call for select-1.
    assert len(_PromptSAM3.calls) == 1
    got = {k["frameIdx"]: k for k in payload["keyframes"]}
    assert got[idx[1]]["prompt"] == "circle"
    assert got[idx[1]]["bbox"]["x"] == 0.5
    assert got[idx[0]]["prompt"] == "sq"
    assert got[idx[0]]["bbox"]["x"] == 0.1
    stored = json.loads(
        (tmp_path / "masks" / vid / "keyframes.json").read_text())
    assert stored["prompt"] == "sq"
    assert stored["sam3Calls"] == 4


def test_selected_all_updates_prompt_and_rebuilds_track(client, tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _PromptSAM3)
    vid = _upload(client)["videoId"]
    seg = _segment(client, vid, "sq", 2)
    idx = [k["frameIdx"] for k in seg["keyframes"]]
    assert client.post(f"/api/videos/{vid}/track",
                       json={"prompt": "sq"}).status_code == 200
    before = client.get(f"/api/videos/{vid}/track").json()
    assert all(b["x"] == pytest.approx(0.1)
               for b in before["interpolatedBoxes"])
    resp = client.post(f"/api/videos/{vid}/segment/selected",
                       json={"prompt": "circle", "frameIndices": idx})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sam3Calls"] == 2
    stored = json.loads(
        (tmp_path / "masks" / vid / "keyframes.json").read_text())
    assert stored["prompt"] == "circle"
    assert stored["sam3Calls"] == 4
    after = client.get(f"/api/videos/{vid}/track").json()
    assert after["prompt"] == "circle"
    assert all(b["x"] == pytest.approx(0.5)
               for b in after["interpolatedBoxes"])


def test_selected_rerenders_when_output_exists(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    vid = _upload(client)["videoId"]
    seg = _segment(client, vid, "sq", 2)
    assert client.post(f"/api/videos/{vid}/track",
                       json={"prompt": "sq"}).status_code == 200
    assert client.post(f"/api/videos/{vid}/render",
                       json={"trackId": vid, "padding": 0.1}
                       ).status_code == 200
    assert (tmp_path / "outputs" / vid / "cropped.mp4").exists()
    idx = [k["frameIdx"] for k in seg["keyframes"]]
    resp = client.post(f"/api/videos/{vid}/segment/selected",
                       json={"prompt": "sq", "frameIndices": idx})
    assert resp.status_code == 200, resp.text
    assert (tmp_path / "outputs" / vid / "cropped.mp4").exists()


def test_selected_guards(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    vid = _upload(client)["videoId"]
    url = f"/api/videos/{vid}/segment/selected"
    assert client.post(url, json={"prompt": "x",
                                  "frameIndices": [0]}).status_code == 404
    _segment(client, vid, "sq", 2)
    assert client.post(url, json={"prompt": "x",
                                  "frameIndices": [999999]}).status_code == 400
    assert client.post(url, json={"prompt": "x",
                                  "frameIndices": [-1]}).status_code == 400
    assert client.post(url, json={"prompt": "x",
                                  "frameIndices": []}).status_code == 422
    assert client.post(url, json={"frameIndices": [0]}).status_code == 422
    assert client.post("/api/videos/" + "0" * 32 + "/segment/selected",
                       json={"prompt": "x",
                             "frameIndices": [0]}).status_code == 404


def test_stream_progressive_events(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    vid = _upload(client)["videoId"]
    resp = client.get(f"/api/videos/{vid}/segment/stream?prompt=sq&numSamples=3")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in resp.text.splitlines()
              if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["keyframe"] * 3 + ["done"]
    assert events[-1]["sam3Calls"] == 3
    assert len(_FakeSAM3.calls) == 3
    frames = [e["keyframe"]["frameIdx"] for e in events[:-1]]
    stored = json.loads(
        (tmp_path / "masks" / vid / "keyframes.json").read_text())
    stored_frames = [k["frameIdx"] for k in stored["keyframes"]]
    assert sorted(frames) == stored_frames == sorted(stored_frames)


def test_stream_error_yields_event_and_partial(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FailSecond)
    vid = _upload(client)["videoId"]
    resp = client.get(f"/api/videos/{vid}/segment/stream?prompt=sq&numSamples=3")
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines()
              if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["keyframe", "error"]
    assert "SAM3 failed" in events[-1]["detail"]
    stored = json.loads(
        (tmp_path / "masks" / vid / "keyframes.json").read_text())
    assert len(stored["keyframes"]) == 1
    assert stored["sam3Calls"] == 1


def test_segment_runs_concurrently_bounded(client, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _SlowSAM3)
    vid = _upload(client)["videoId"]
    resp = client.post(f"/api/videos/{vid}/segment",
                       json={"prompt": "sq", "numSamples": 6})
    assert resp.status_code == 200
    assert _SlowSAM3.max_in_flight == 4  # overlapped AND semaphore-bound
    frames = [k["frameIdx"] for k in resp.json()["keyframes"]]
    assert frames == sorted(frames)  # POST paths stay in frame order


def test_stream_guards(client):
    assert client.get("/api/videos/" + "0" * 32
                      + "/segment/stream?prompt=x").status_code == 404
    vid = _upload(client)["videoId"]
    assert client.get(
        f"/api/videos/{vid}/segment/stream").status_code == 422
