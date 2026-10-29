import { useRef, useState } from "react";
import { Box, Button, Slider, Stack, Typography } from "@mui/material";
import type { VideoMetadata } from "../api/client";

interface Props {
  originalUrl: string;
  croppedUrl: string | null;
  metadata: VideoMetadata;
}

function formatTime(t: number): string {
  if (!Number.isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function VideoPreview({ originalUrl, croppedUrl, metadata }: Props) {
  const origRef = useRef<HTMLVideoElement>(null);
  const cropRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  function seek(t: number) {
    const clamped = Math.max(0, Math.min(duration || 0, t));
    setTime(clamped);
    if (origRef.current) origRef.current.currentTime = clamped;
    if (cropRef.current) cropRef.current.currentTime = clamped;
  }

  function togglePlay() {
    const orig = origRef.current;
    const crop = cropRef.current;
    if (!orig) return;
    if (orig.paused) {
      if (crop) crop.currentTime = orig.currentTime;
      void orig.play();
      if (crop) void crop.play();
      setPlaying(true);
    } else {
      orig.pause();
      if (crop) {
        crop.pause();
        crop.currentTime = orig.currentTime;
      }
      setPlaying(false);
    }
  }

  function onOrigTime() {
    if (origRef.current) setTime(origRef.current.currentTime);
  }

  function onOrigMeta() {
    const d = origRef.current?.duration;
    if (d !== undefined && Number.isFinite(d)) setDuration(d);
  }

  const rows: Array<[string, string]> = [
    ["File", metadata.filename],
    ["Size", `${metadata.width} x ${metadata.height}`],
    ["FPS", metadata.fps.toFixed(2)],
    ["Duration", `${metadata.duration.toFixed(2)} s`],
    ["Frames", String(metadata.totalFrames)],
    ["Video ID", metadata.videoId],
  ];
  return (
    <Stack spacing={2}>
      {croppedUrl ? (
        <Stack spacing={1}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="subtitle2" gutterBottom>
                Original
              </Typography>
              <video
                ref={origRef}
                src={originalUrl}
                onTimeUpdate={onOrigTime}
                onLoadedMetadata={onOrigMeta}
                onEnded={() => setPlaying(false)}
                style={{ width: "100%", maxHeight: 480, backgroundColor: "black" }}
              />
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="subtitle2" gutterBottom>
                Cropped
              </Typography>
              <video
                ref={cropRef}
                src={croppedUrl}
                muted
                style={{ width: "100%", maxHeight: 480, backgroundColor: "black" }}
              />
              <Typography variant="caption" color="text.secondary">
                Cropped audio muted — identical to the original.
              </Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
            <Button
              variant="outlined"
              size="small"
              onClick={togglePlay}
              disabled={duration === 0}
            >
              {playing ? "Pause both" : "Play both"}
            </Button>
            <Slider
              min={0}
              max={duration}
              step={0.01}
              value={Math.min(time, duration)}
              onChange={(_, v) => seek(v as number)}
              disabled={duration === 0}
              sx={{ flexGrow: 1 }}
            />
            <Typography variant="caption" sx={{ whiteSpace: "nowrap" }}>
              {formatTime(time)} / {formatTime(duration)}
            </Typography>
          </Stack>
        </Stack>
      ) : (
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" gutterBottom>
            Original
          </Typography>
          <Box
            component="video"
            src={originalUrl}
            controls
            sx={{ width: "100%", maxHeight: 480, backgroundColor: "black" }}
          />
        </Box>
      )}
      <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "120px 1fr", rowGap: 0.5, m: 0 }}>
        {rows.map(([term, value]) => (
          <Box key={term} sx={{ display: "contents" }}>
            <Typography component="dt" variant="body2" color="text.secondary">
              {term}
            </Typography>
            <Typography component="dd" variant="body2" sx={{ m: 0, overflowWrap: "anywhere" }}>
              {value}
            </Typography>
          </Box>
        ))}
      </Box>
    </Stack>
  );
}
