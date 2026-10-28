import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Container,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Dropzone from "./components/Dropzone";
import VideoPreview from "./components/VideoPreview";
import KeyframeStrip from "./components/KeyframeStrip";
import type { StripItem } from "./components/KeyframeStrip";
import Timeline from "./components/Timeline";
import type { FixUpdate } from "./components/Timeline";
import { buildTrack, fetchFrames, fetchTrack, renderVideo, segmentVideo, uploadVideo } from "./api/client";
import type { Keyframe, TrackData, UploadResponse } from "./api/client";

function upsertStripItem(items: StripItem[] | null, kf: Keyframe, videoId: string): StripItem[] {
  const url = `/frames/${videoId}/${String(kf.frameIdx).padStart(6, "0")}.jpg`;
  const item: StripItem = { frameIdx: kf.frameIdx, url, bbox: kf.bbox };
  if (!items) return [item];
  return [...items.filter((i) => i.frameIdx !== kf.frameIdx), item].sort(
    (a, b) => a.frameIdx - b.frameIdx,
  );
}

export default function App() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [prompt, setPrompt] = useState("dumbbell");
  const [numSamples, setNumSamples] = useState(15);
  const [segmenting, setSegmenting] = useState(false);
  const [strip, setStrip] = useState<StripItem[] | null>(null);
  const [calls, setCalls] = useState<number | null>(null);
  const [building, setBuilding] = useState(false);
  const [track, setTrack] = useState<TrackData | null>(null);
  const [trackId, setTrackId] = useState<string | null>(null);
  const [padding, setPadding] = useState(0.15);
  const [aspect, setAspect] = useState("");
  const [rendering, setRendering] = useState(false);
  const [croppedUrl, setCroppedUrl] = useState<string | null>(null);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    setStrip(null);
    setCalls(null);
    setTrack(null);
    setTrackId(null);
    setCroppedUrl(null);
    try {
      setResult(await uploadVideo(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleSegment() {
    if (!result || !prompt.trim()) return;
    setSegmenting(true);
    setError(null);
    setTrack(null);
    setCroppedUrl(null);
    try {
      const seg = await segmentVideo(result.videoId, prompt.trim(), numSamples);
      const refs = await fetchFrames(result.videoId, numSamples);
      const boxes = new Map(seg.keyframes.map((k) => [k.frameIdx, k.bbox]));
      setStrip(refs.map((r) => ({
        frameIdx: r.frameIdx,
        url: r.url,
        bbox: boxes.get(r.frameIdx) ?? null,
      })));
      setCalls(seg.sam3Calls);
    } catch (err) {
      setError(err instanceof Error ? err.message : "segment failed");
    } finally {
      setSegmenting(false);
    }
  }

  async function handleBuildTrack() {
    if (!result || !prompt.trim()) return;
    setBuilding(true);
    setError(null);
    setCroppedUrl(null);
    try {
      const built = await buildTrack(result.videoId, prompt.trim());
      setTrackId(built.trackId);
      setTrack(await fetchTrack(result.videoId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "track failed");
    } finally {
      setBuilding(false);
    }
  }

  function handleFixed(update: FixUpdate) {
    if (update.track) setTrack(update.track);
    if (result) setStrip((prev) => upsertStripItem(prev, update.keyframe, result.videoId));
    if (update.outputUrl) setCroppedUrl(`${update.outputUrl}?t=${Date.now()}`);
  }

  async function handleRender() {
    if (!result || !trackId) return;
    setRendering(true);
    setError(null);
    try {
      const rendered = await renderVideo(result.videoId, trackId, padding, aspect.trim());
      setCroppedUrl(rendered.outputUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "render failed");
    } finally {
      setRendering(false);
    }
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Video Cropper
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Upload a video, describe the object, segment the keyframes, then build
            the interpolated track.
          </Typography>
        </Box>
        <Dropzone onFile={handleFile} disabled={uploading || segmenting || building} />
        {uploading && <LinearProgress />}
        {error && <Alert severity="error">{error}</Alert>}
        {result && !uploading && (
          <VideoPreview
            originalUrl={result.originalUrl}
            croppedUrl={croppedUrl}
            metadata={result.metadata}
          />
        )}
        {result && !uploading && (
          <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
            <TextField
              label="Prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={segmenting || building}
              sx={{ flexGrow: 1 }}
            />
            <TextField
              label="Keyframes"
              type="number"
              value={numSamples}
              onChange={(e) => setNumSamples(Math.max(1, Number(e.target.value) || 15))}
              disabled={segmenting || building}
              sx={{ width: 120 }}
              slotProps={{ htmlInput: { min: 1 } }}
            />
            <Button variant="contained" onClick={handleSegment} disabled={segmenting || building}>
              Segment
            </Button>
          </Stack>
        )}
        {segmenting && (
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Segmenting {numSamples} keyframes — one SAM3 call each, this takes a while.
            </Typography>
            <LinearProgress />
          </Box>
        )}
        {calls !== null && !segmenting && (
          <Typography variant="body2" color="text.secondary">
            {calls} SAM3 calls. Tweak the prompt and re-run any time.
          </Typography>
        )}
        {strip && !segmenting && <KeyframeStrip items={strip} />}
        {strip && !segmenting && (
          <Box>
            <Button variant="contained" onClick={handleBuildTrack} disabled={building}>
              Build track
            </Button>
          </Box>
        )}
        {building && <LinearProgress />}
        {track && !building && result && (
          <Timeline
            videoId={result.videoId}
            videoUrl={result.originalUrl}
            fps={result.metadata.fps}
            totalFrames={result.metadata.totalFrames}
            boxes={track.interpolatedBoxes}
            keyframes={track.keyframes.flatMap((k) =>
              k.bbox ? [{ frameIdx: k.frameIdx, bbox: k.bbox, origin: k.origin }] : [],
            )}
            onFixed={handleFixed}
          />
        )}
        {track && !building && (
          <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
            <TextField
              label="Padding"
              type="number"
              value={padding}
              onChange={(e) => setPadding(Math.max(0, Number(e.target.value) || 0))}
              disabled={rendering}
              sx={{ width: 120 }}
              slotProps={{ htmlInput: { min: 0, step: 0.05 } }}
            />
            <TextField
              label="Aspect (W:H, blank = auto)"
              value={aspect}
              onChange={(e) => setAspect(e.target.value)}
              disabled={rendering}
              sx={{ width: 220 }}
            />
            <Button variant="contained" onClick={handleRender} disabled={rendering}>
              Render crop
            </Button>
          </Stack>
        )}
        {rendering && (
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Rendering cropped video — re-encoding every frame, this takes a while.
            </Typography>
            <LinearProgress />
          </Box>
        )}
      </Stack>
    </Container>
  );
}
