import { useRef, useState } from "react";
import { Box, Button, Slider, Stack, Typography } from "@mui/material";
import type { BBox } from "../api/client";

export interface TimelineKeyframe {
  frameIdx: number;
  bbox: BBox;
}

interface Props {
  videoUrl: string;
  fps: number;
  totalFrames: number;
  boxes: BBox[];
  keyframes: TimelineKeyframe[];
}

function mostRecentAtOrBefore(keyframes: TimelineKeyframe[], frame: number): BBox | null {
  let best: BBox | null = null;
  for (const kf of keyframes) {
    if (kf.frameIdx <= frame) best = kf.bbox;
    else break;
  }
  return best;
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
      <Box sx={{ width: 14, height: 14, border: `2px solid ${color}`, boxSizing: "border-box" }} />
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Stack>
  );
}

export default function Timeline({ videoUrl, fps, totalFrames, boxes, keyframes }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);

  function scrub(next: number) {
    const clamped = Math.max(0, Math.min(totalFrames - 1, next));
    setFrame(clamped);
    if (videoRef.current) videoRef.current.currentTime = clamped / fps;
  }

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
      setPlaying(true);
    } else {
      video.pause();
      setPlaying(false);
    }
  }

  function onTimeUpdate() {
    const video = videoRef.current;
    if (!video) return;
    setFrame(Math.min(totalFrames - 1, Math.floor(video.currentTime * fps)));
  }

  const box = boxes[frame];
  const keyBox = mostRecentAtOrBefore(keyframes, frame);
  return (
    <Stack spacing={1}>
      {/* Shrink-wrapped: overlay % must measure the video content, not a
          letterboxed element (portrait video in a wide box reads too wide). */}
      <Box sx={{ position: "relative", alignSelf: "center", maxWidth: "100%", backgroundColor: "black" }}>
        <video
          ref={videoRef}
          src={videoUrl}
          muted
          preload="auto"
          onTimeUpdate={onTimeUpdate}
          onEnded={() => setPlaying(false)}
          style={{ display: "block", maxWidth: "100%", maxHeight: 480, width: "auto", height: "auto" }}
        />
        {keyBox && (
          <Box
            sx={{
              position: "absolute",
              left: `${keyBox.x * 100}%`,
              top: `${keyBox.y * 100}%`,
              width: `${keyBox.w * 100}%`,
              height: `${keyBox.h * 100}%`,
              border: "2px solid red",
              boxSizing: "border-box",
            }}
          />
        )}
        {box && (
          <Box
            sx={{
              position: "absolute",
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.w * 100}%`,
              height: `${box.h * 100}%`,
              border: "2px solid lime",
              boxSizing: "border-box",
            }}
          />
        )}
      </Box>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Button variant="outlined" size="small" onClick={togglePlay}>
          {playing ? "Pause" : "Play"}
        </Button>
        <Slider
          min={0}
          max={totalFrames - 1}
          value={frame}
          onChange={(_, v) => scrub(v as number)}
          sx={{ flexGrow: 1 }}
        />
        <Typography variant="caption" sx={{ whiteSpace: "nowrap" }}>
          frame {frame}/{totalFrames - 1}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={2}>
        <Swatch color="lime" label="Interpolated" />
        <Swatch color="red" label="Latest keyframe" />
      </Stack>
    </Stack>
  );
}
