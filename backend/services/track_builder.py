"""Linear interpolation of keyframe boxes across all frames (Phase 4)."""

from __future__ import annotations

import bisect


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def interpolate_boxes(keyframes: list[dict], total_frames: int,
                      smooth_window: int = 5) -> list[dict]:
    """Interpolate `{x,y,w,h}` for every frame from sparse keyframes.

    `keyframes`: `[{frameIdx, bbox:{x,y,w,h} | None}]` — misses are skipped,
    last box wins on duplicate indices. Holds the edge box outside the
    keyframe range. Raises ValueError when no keyframe has a box.
    """
    if total_frames <= 0:
        raise ValueError("total_frames must be positive")
    by_idx: dict[int, dict] = {}
    for keyframe in keyframes:
        if keyframe.get("bbox") is not None:
            by_idx[keyframe["frameIdx"]] = keyframe["bbox"]
    if not by_idx:
        raise ValueError("no detections to interpolate")
    idx = sorted(by_idx)
    boxes = [by_idx[i] for i in idx]
    out = []
    for frame in range(total_frames):
        pos = bisect.bisect_right(idx, frame)
        if pos == 0:
            box = boxes[0]
        elif pos == len(idx):
            box = boxes[-1]
        else:
            start, end = idx[pos - 1], idx[pos]
            ratio = (frame - start) / (end - start)
            box = {k: _lerp(boxes[pos - 1][k], boxes[pos][k], ratio)
                   for k in ("x", "y", "w", "h")}
        out.append({k: _clamp(float(v)) for k, v in box.items()})
    if smooth_window >= 3:
        out = _smooth(out, smooth_window)
    return out


def _smooth(boxes: list[dict], window: int) -> list[dict]:
    """Moving average per component; edges use the available neighbors."""
    half = window // 2
    total = len(boxes)
    smoothed = []
    for i in range(total):
        lo, hi = max(0, i - half), min(total, i + half + 1)
        count = hi - lo
        smoothed.append({k: _clamp(sum(b[k] for b in boxes[lo:hi]) / count)
                         for k in ("x", "y", "w", "h")})
    return smoothed
