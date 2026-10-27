"""SAM3 text-prompt segmentation via api.meta.ai (Phase 3). Real service, no stub."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from meta_sam_parser import SegmentationMask, decode_mask_to_raster
from PIL import Image

BOX_RE = re.compile(r"<\|box;(.*?)\|>")
MASK_RE = re.compile(r"<\|mask;(.*?)\|>")

# Retry 429/5xx only; other 4xx fail fast. Spike-verified against sam-3.1.
_RETRY_ATTEMPTS = 3


@dataclass(frozen=True)
class BoxPixels:
    x1: int
    y1: int
    x2: int
    y2: int
    width: int
    height: int


@dataclass
class Segmentation:
    bbox: dict  # normalized {x, y, w, h}
    mask_raster: bytes  # full-frame 0/1 bytes, len width*height
    width: int
    height: int
    confidence: None = None  # API returns no score


def parse_box_specs(text: str) -> list[BoxPixels]:
    boxes = []
    for match in BOX_RE.finditer(text):
        parts = dict(kv.split("=", 1) for kv in match.group(1).split(";"))
        boxes.append(BoxPixels(*(int(parts[k]) for k in ("x1", "y1", "x2", "y2", "w", "h"))))
    return boxes


def parse_mask_payloads(text: str) -> list[tuple[int, int, str]]:
    """Return [(width, height, payload)] for each `<|mask|x;y;data=h,w,~...|>`.

    Safe to split on `;data=`: the payload alphabet excludes `;`.
    """
    out = []
    for match in MASK_RE.finditer(text):
        data = match.group(1).split(";data=", 1)[1]
        height, width, payload = data.split(",", 2)
        out.append((int(width), int(height), payload))
    return out


def normalize_box(box: BoxPixels) -> dict:
    def clamp(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    return {
        "x": clamp(box.x1 / box.width),
        "y": clamp(box.y1 / box.height),
        "w": clamp((box.x2 - box.x1) / box.width),
        "h": clamp((box.y2 - box.y1) / box.height),
    }


def build_full_frame_mask(origin_x: int, origin_y: int, mask_w: int, mask_h: int,
                          crop: bytes, frame_w: int, frame_h: int) -> bytes:
    """Place a box-crop mask into a full-frame raster (clipped to bounds)."""
    if len(crop) != mask_w * mask_h:
        raise ValueError("mask crop size does not match its dimensions")
    raster = bytearray(frame_w * frame_h)
    rows = min(mask_h, frame_h - origin_y)
    cols = min(mask_w, frame_w - origin_x)
    for row in range(max(rows, 0)):
        src = row * mask_w
        dst = (origin_y + row) * frame_w + origin_x
        raster[dst:dst + cols] = crop[src:src + cols]
    return bytes(raster)


def save_mask_png(path: Path, raster: bytes, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("L", (width, height),
                    bytes(255 if v else 0 for v in raster)).save(path)


async def _with_retry(call):
    delay = 1.0
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return await call()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status != 429 and status < 500:
                raise
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)


def build_segmentation(text: str) -> Segmentation | None:
    """Build a Segmentation from completed output text.

    Returns None when the model found nothing (empty text or no box+mask pair).
    Raises ValueError on malformed detections (e.g. undecodable mask).
    """
    if not text or not text.strip():
        return None
    boxes = parse_box_specs(text)
    masks = parse_mask_payloads(text)
    if not boxes or not masks:
        return None
    # V1: first detection wins (multi-detection shape unobserved; see plan).
    box = boxes[0]
    mask_w, mask_h, payload = masks[0]
    if not payload.startswith("~"):
        raise ValueError("unsupported mask encoding (expected lossless)")
    crop = decode_mask_to_raster(SegmentationMask(
        encoding="lossless", payload=payload, width=mask_w, height=mask_h))
    full = build_full_frame_mask(box.x1, box.y1, mask_w, mask_h,
                                 crop, box.width, box.height)
    return Segmentation(bbox=normalize_box(box), mask_raster=full,
                        width=box.width, height=box.height)


class SAM3Service:
    """Text-prompt segmentation. One `segment()` = one upload + one inference."""

    def __init__(self, api_key: str, base_url: str = "https://api.meta.ai/v1",
                 model: str = "sam-3.1", timeout: float = 300.0) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = timeout

    async def segment(self, image_path: Path,
                      text_prompt: str) -> Segmentation | None:
        """Segment one image. Returns None when the model finds nothing."""
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(base_url=self._base_url,
                                     timeout=self._timeout) as client:
            file_id = await self._upload(client, headers, image_path)
            text = await self._infer(client, headers, file_id, text_prompt)
        return build_segmentation(text)

    async def _upload(self, client: httpx.AsyncClient, headers: dict,
                      image_path: Path) -> str:
        data = image_path.read_bytes()

        async def call() -> str:
            resp = await client.post(
                "/files", headers=headers,
                files={"file": (image_path.name, data, "image/jpeg")},
                data={"purpose": "user_data"})
            resp.raise_for_status()
            file_id = resp.json().get("id")
            if not isinstance(file_id, str) or not file_id:
                raise ValueError("upload response had no file id")
            return file_id

        return await _with_retry(call)

    async def _infer(self, client: httpx.AsyncClient, headers: dict,
                     file_id: str, text_prompt: str) -> str:
        body = {
            "model": self._model,
            "input": [{
                "type": "message", "role": "user",
                "content": [
                    {"type": "input_text", "text": text_prompt},
                    {"type": "input_image", "file_id": file_id},
                ],
            }],
            "stream": True,
            "metadata": {"mask_encoding": "lossless"},
        }

        async def call() -> str:
            stream_headers = {**headers, "Content-Type": "application/json",
                              "Accept": "text/event-stream"}
            async with client.stream("POST", "/responses", headers=stream_headers,
                                     content=json.dumps(body)) as resp:
                resp.raise_for_status()
                final = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data: ") or line[6:] == "[DONE]":
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "response.failed":
                        message = ((event.get("response") or {}).get("error") or {}).get(
                            "message", "response failed")
                        raise ValueError(f"SAM3 inference failed: {message}")
                    if event.get("type") == "response.output_text.done":
                        final = event.get("text")
                if final is None:
                    raise ValueError("stream had no output_text.done")
                return final

        return await _with_retry(call)
