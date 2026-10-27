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
import { fetchFrames, segmentVideo, uploadVideo } from "./api/client";
import type { UploadResponse } from "./api/client";

export default function App() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [prompt, setPrompt] = useState("dumbbell");
  const [numSamples, setNumSamples] = useState(15);
  const [segmenting, setSegmenting] = useState(false);
  const [strip, setStrip] = useState<StripItem[] | null>(null);
  const [calls, setCalls] = useState<number | null>(null);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    setStrip(null);
    setCalls(null);
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

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Video Cropper
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Upload a video, describe the object, and segment the sampled keyframes.
          </Typography>
        </Box>
        <Dropzone onFile={handleFile} disabled={uploading || segmenting} />
        {uploading && <LinearProgress />}
        {error && <Alert severity="error">{error}</Alert>}
        {result && !uploading && (
          <VideoPreview originalUrl={result.originalUrl} metadata={result.metadata} />
        )}
        {result && !uploading && (
          <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
            <TextField
              label="Prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={segmenting}
              sx={{ flexGrow: 1 }}
            />
            <TextField
              label="Keyframes"
              type="number"
              value={numSamples}
              onChange={(e) => setNumSamples(Math.max(1, Number(e.target.value) || 15))}
              disabled={segmenting}
              sx={{ width: 120 }}
              slotProps={{ htmlInput: { min: 1 } }}
            />
            <Button variant="contained" onClick={handleSegment} disabled={segmenting}>
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
      </Stack>
    </Container>
  );
}
