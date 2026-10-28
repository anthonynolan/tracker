import { useRef, useState } from "react";
import { Alert, Box, Button, Slider, Stack, Typography } from "@mui/material";
import type { BBox, Keyframe, TrackData } from "../api/client";
import { fetchTrack, fixKeyframe } from "../api/client";

export interface TimelineKeyframe {
  frameIdx: number;
  bbox: BBox;
  origin: string;
}

export interface FixUpdate {
  track: TrackData | null;
  keyframe: Keyframe;
  outputUrl: string | null;
}

interface Props {
  videoId: string;
  videoUrl: string;
  fps: number;
  totalFrames: number;
  boxes: BBox[];
  keyframes: TimelineKeyframe[];
  onFixed: (update: FixUpdate) => void;
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

export default function Timeline({
  videoId, videoUrl, fps, totalFrames, boxes, keyframes, onFixed,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [fixError, setFixError] = useState<string | null>(null);

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

  async function handleFix() {
    setFixing(true);
    setFixError(null);
    try {
      const res = await fixKeyframe(videoId, frame);
      const track = res.trackRebuilt ? await fetchTrack(videoId) : null;
      onFixed({ track, keyframe: res.keyframe, outputUrl: res.outputUrl });
    } catch (err) {
      setFixError(err instanceof Error ? err.message : "fix failed");
    } finally {
      setFixing(false);
    }
  }

  const box = boxes[frame];
  const keyBox = mostRecentAtOrBefore(keyframes, frame);
  const isKeyframe = keyframes.some((k) => k.frameIdx === frame);
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
      <Box sx={{ position: "relative", height: 12 }} title="Keyframe markers: hollow = sampled, filled = fix">
        {keyframes.map((k) => (
          <Box
            key={k.frameIdx}
            sx={{
              position: "absolute",
              left: `${(k.frameIdx / (totalFrames - 1)) * 100}%`,
              top: 2,
              width: 8,
              height: 8,
              borderRadius: "50%",
              transform: "translateX(-50%)",
              boxSizing: "border-box",
              ...(k.origin === "sampled"
                ? { border: "2px solid grey" }
                : { backgroundColor: "primary.main" }),
            }}
          />
        ))}
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
        <Button
          variant="contained"
          size="small"
          onClick={handleFix}
          disabled={fixing || isKeyframe}
          title={isKeyframe ? "This frame is already a keyframe" : "Segment this frame and splice it in"}
        >
          Fix this frame
        </Button>
      </Stack>
      {fixing && (
        <Typography variant="body2" color="text.secondary">
          Segmenting frame {frame} — one SAM3 call, plus a re-render when an output exists.
        </Typography>
      )}
      {fixError && <Alert severity="error">{fixError}</Alert>}
      <Stack direction="row" spacing={2}>
        <Swatch color="lime" label="Interpolated" />
        <Swatch color="red" label="Latest keyframe" />
      </Stack>
    </Stack>
  );
}
