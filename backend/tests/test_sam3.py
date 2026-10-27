"""Phase 3 tests: SAM3 response parsing (real captured sample) + segment endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.services import sam3_service
from backend.services.sam3_service import (
    BoxPixels,
    Segmentation,
    build_full_frame_mask,
    build_segmentation,
    normalize_box,
    parse_box_specs,
    parse_mask_payloads,
    save_mask_png,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"
SAM_TEXT = (Path(__file__).parent / "fixtures" / "sam_output.txt").read_text()


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


def test_parse_box_and_mask_from_real_sample():
    assert parse_box_specs(SAM_TEXT) == [
        BoxPixels(x1=229, y1=434, x2=729, y2=821, width=1080, height=1920)]
    width, height, payload = parse_mask_payloads(SAM_TEXT)[0]
    assert (width, height) == (501, 388)
    assert payload.startswith("~")


def test_normalize_and_full_frame_mask():
    box = BoxPixels(x1=229, y1=434, x2=729, y2=821, width=1080, height=1920)
    bbox = normalize_box(box)
    assert bbox == pytest.approx({"x": 0.212, "y": 0.226, "w": 0.463, "h": 0.202},
                                 abs=0.002)
    assert all(0.0 <= v <= 1.0 for v in bbox.values())
    _, _, payload = parse_mask_payloads(SAM_TEXT)[0]
    from meta_sam_parser import SegmentationMask, decode_mask_to_raster

    crop = decode_mask_to_raster(SegmentationMask(
        encoding="lossless", payload=payload, width=501, height=388))
    full = build_full_frame_mask(229, 434, 501, 388, crop, 1080, 1920)
    assert len(full) == 1080 * 1920
    assert sum(full) / len(full) == pytest.approx(0.0586, abs=0.002)


def test_build_segmentation_none_when_empty():
    assert build_segmentation("") is None
    assert build_segmentation("   ") is None
    assert build_segmentation("<0f>0") is None


def test_build_segmentation_from_real_sample():
    seg = build_segmentation(SAM_TEXT)
    assert seg is not None and (seg.width, seg.height) == (1080, 1920)
    assert len(seg.mask_raster) == 1080 * 1920


def test_save_mask_png_roundtrip(tmp_path):
    from PIL import Image

    path = tmp_path / "mask.png"
    save_mask_png(path, bytes([1, 0] * 50), 10, 10)
    with Image.open(path) as img:
        assert (img.size, img.mode) == ((10, 10), "L")


class _FakeSAM3:
    calls: list = []

    def __init__(self, api_key: str = "", **kwargs) -> None:
        assert api_key == "test-key"
        type(self).calls = []

    async def segment(self, image_path: Path, text_prompt: str) -> Segmentation:
        type(self).calls.append((image_path, text_prompt))
        return Segmentation(bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                            mask_raster=bytes(32 * 24), width=32, height=24)


def _upload(client) -> dict:
    with open(FIXTURE, "rb") as fh:
        resp = client.post("/api/videos/upload",
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    return resp.json()


def test_segment_endpoint_uses_n_calls_only(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sam3_service, "SAM3Service", _FakeSAM3)
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _FakeSAM3)
    body = _upload(client)
    video_id = body["videoId"]
    resp = client.post(f"/api/videos/{video_id}/segment",
                       json={"prompt": "square", "numSamples": 5})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["sam3Calls"] == 5
    assert len(_FakeSAM3.calls) == 5  # SAM3 ONLY on the sampled keyframes
    assert len(payload["keyframes"]) == 5
    first = payload["keyframes"][0]
    assert first["prompt"] == "square" and first["confidence"] is None
    assert all(0.0 <= v <= 1.0 for v in first["bbox"].values())
    assert len(list((tmp_path / "masks" / video_id).glob("*.png"))) == 5
    assert (tmp_path / "masks" / video_id / "keyframes.json").exists()


class _NullSAM3(_FakeSAM3):
    async def segment(self, image_path: Path, text_prompt: str):
        type(self).calls.append((image_path, text_prompt))
        return None


def test_segment_keeps_misses_explicit(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.routers.videos.SAM3Service", _NullSAM3)
    body = _upload(client)
    resp = client.post(f"/api/videos/{body['videoId']}/segment",
                       json={"prompt": "nothing-here", "numSamples": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["sam3Calls"] == 2  # calls still count
    assert all(k["bbox"] is None and k["maskPath"] is None
               for k in payload["keyframes"])
    assert list((tmp_path / "masks" / body["videoId"]).glob("*.png")) == []


def test_segment_rejects_unknown_video_and_empty_prompt(client):
    assert client.post("/api/videos/" + "f" * 32 + "/segment",
                       json={"prompt": "x"}).status_code == 404
    body = _upload(client)
    assert client.post(f"/api/videos/{body['videoId']}/segment",
                       json={"prompt": ""}).status_code == 422
