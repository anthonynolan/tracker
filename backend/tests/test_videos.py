"""Phase 1 API tests: health, config secrecy, upload, status, output."""

from pathlib import Path

from backend.config import get_settings

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_settings_hides_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.model_api_key.get_secret_value() == "super-secret-value"
        assert "super-secret-value" not in repr(settings)
    finally:
        get_settings.cache_clear()


def test_upload_status_output_flow(client, tmp_path):
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) >= {"videoId", "metadata", "originalUrl"}
    meta = body["metadata"]
    assert (meta["width"], meta["height"]) == (320, 240)
    assert meta["totalFrames"] > 0 and meta["duration"] > 0 and meta["fps"] > 0
    video_id = body["videoId"]
    assert (tmp_path / "uploads" / video_id / "meta.json").exists()

    status = client.get(f"/api/videos/{video_id}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "uploaded"

    assert client.get(f"/api/videos/{video_id}/output").status_code == 404
    assert client.get("/api/videos/0" * 1 + "f" * 31 + "/status").status_code == 404
    assert client.get("/api/videos/not-a-valid-id/status").status_code == 404


def test_rejects_empty_and_non_video(client):
    empty = client.post("/api/videos/upload", files={"file": ("e.mp4", b"", "video/mp4")})
    assert empty.status_code == 400
    junk = client.post("/api/videos/upload",
                       files={"file": ("x.mp4", b"not a video", "video/mp4")})
    assert junk.status_code == 400
