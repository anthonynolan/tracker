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


def insert_keyframe(boxes: list[dict], keyframes: list[dict], new: dict,
                    total_frames: int, smooth_window: int = 5
                    ) -> tuple[list[dict], list[dict]]:
    """Insert a keyframe; recompute only the affected span.

    `keyframes`: valid (`bbox` set) list; `new`: `{frameIdx, bbox}`.
    Returns (new_boxes, new_sorted_keyframes[{frameIdx,bbox}]).
    Frames outside the span [prev|0, next|end] are byte-identical; smoothing
    inside the span uses old boxes as edge context. Raises ValueError on
    duplicates, out-of-range frames, or missing boxes.
    """
    frame = new["frameIdx"]
    if new.get("bbox") is None:
        raise ValueError("cannot insert a keyframe without a box")
    if not (0 <= frame < total_frames):
        raise ValueError(f"frame {frame} out of range")
    if any(k["frameIdx"] == frame for k in keyframes):
        raise ValueError(f"frame {frame} is already a keyframe")
    if len(boxes) != total_frames:
        raise ValueError("boxes length does not match total frames")
    ordered = sorted(keyframes, key=lambda k: k["frameIdx"])
    prev = next((k for k in reversed(ordered) if k["frameIdx"] < frame), None)
    nxt = next((k for k in ordered if k["frameIdx"] > frame), None)
    lo = prev["frameIdx"] if prev else 0
    hi = nxt["frameIdx"] if nxt else total_frames - 1
    anchors = []
    if prev:
        anchors.append((prev["frameIdx"], prev["bbox"]))
    anchors.append((frame, new["bbox"]))
    if nxt:
        anchors.append((nxt["frameIdx"], nxt["bbox"]))
    fresh = list(boxes)
    for i in range(lo, hi + 1):
        if i <= anchors[0][0]:
            point = dict(anchors[0][1])
        elif i >= anchors[-1][0]:
            point = dict(anchors[-1][1])
        else:
            point = None
            for a, b in zip(anchors, anchors[1:]):
                if a[0] <= i <= b[0]:
                    ratio = (i - a[0]) / (b[0] - a[0])
                    point = {k: _lerp(a[1][k], b[1][k], ratio)
                             for k in ("x", "y", "w", "h")}
                    break
            assert point is not None  # anchors bracket every in-span frame
        fresh[i] = {k: _clamp(float(v)) for k, v in point.items()}
    if smooth_window >= 3:
        half = smooth_window // 2
        for i in range(lo, hi + 1):
            span_lo, span_hi = max(0, i - half), min(total_frames, i + half + 1)
            acc = {k: 0.0 for k in ("x", "y", "w", "h")}
            for j in range(span_lo, span_hi):
                src = fresh[j] if lo <= j <= hi else boxes[j]
                for k in acc:
                    acc[k] += src[k]
            count = span_hi - span_lo
            fresh[i] = {k: _clamp(acc[k] / count) for k in acc}
    merged = sorted([*({"frameIdx": k["frameIdx"], "bbox": k["bbox"]}
                       for k in ordered),
                     {"frameIdx": frame, "bbox": new["bbox"]}],
                    key=lambda k: k["frameIdx"])
    return fresh, merged
