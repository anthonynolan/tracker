"""Phase 2 tests: sampling math + keyframe extraction endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.services.frame_service import _extract_frame, getSampleFrameIndices

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.video_service.DATA_DIR", tmp_path)
    monkeypatch.setattr("backend.services.frame_service.DATA_DIR", tmp_path)
    from backend.main import app

    return TestClient(app)


def test_sampling_example():
    assert getSampleFrameIndices(100, 5) == [0, 25, 50, 75, 99]


def test_sampling_edges():
    assert getSampleFrameIndices(3, 15) == [0, 1, 2]
    assert getSampleFrameIndices(10, 1) == [0]
    assert getSampleFrameIndices(10, 10) == list(range(10))
    with pytest.raises(ValueError):
        getSampleFrameIndices(0, 5)
    with pytest.raises(ValueError):
        getSampleFrameIndices(10, 0)


@pytest.mark.parametrize("total,n", [(30, 15), (413, 15), (1000, 7), (16, 15)])
def test_sampling_invariants(total, n):
    idx = getSampleFrameIndices(total, n)
    assert len(idx) == min(n, total)
    assert idx[0] == 0 and idx[-1] == total - 1
    assert all(b > a for a, b in zip(idx, idx[1:]))


def _upload(client) -> dict:
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    return resp.json()


def test_frames_extract_and_list(client, tmp_path):
    body = _upload(client)
    video_id = body["videoId"]
    total = body["metadata"]["totalFrames"]
    resp = client.get(f"/api/videos/{video_id}/frames")
    assert resp.status_code == 200
    frames = resp.json()["frames"]
    assert [f["frameIdx"] for f in frames] == getSampleFrameIndices(total, 15)
    assert all(f["url"].startswith(f"/frames/{video_id}/") for f in frames)
    on_disk = sorted((tmp_path / "frames" / video_id).glob("*.jpg"))
    assert len(on_disk) == len(frames) == 15  # exactly N JPEGs, no others


def test_frames_clamp_unknown_and_invalid(client):
    body = _upload(client)
    video_id = body["videoId"]
    total = body["metadata"]["totalFrames"]
    resp = client.get(f"/api/videos/{video_id}/frames?numSamples=50")
    assert len(resp.json()["frames"]) == total
    assert client.get("/api/videos/" + "f" * 32 + "/frames").status_code == 404
    assert client.get(f"/api/videos/{video_id}/frames?numSamples=0").status_code == 422


def test_extract_steps_back_past_eof(tmp_path):
    # Regression: ffmpeg exits 0 with no output when -ss overshoots EOF
    # (tail index from an estimated frame count). Must step back, not vanish.
    target = tmp_path / "back.jpg"
    _extract_frame(FIXTURE, target, timestamp=1.5, frame_step=1 / 30, attempts=60)
    assert target.exists() and target.stat().st_size > 0
