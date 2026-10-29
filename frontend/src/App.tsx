import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  FormControl,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Dropzone from "./components/Dropzone";
import VideoPreview from "./components/VideoPreview";
import KeyframeGrid from "./components/KeyframeGrid";
import type { GridItem } from "./components/KeyframeGrid";
import Timeline from "./components/Timeline";
import type { FixUpdate } from "./components/Timeline";
import {
  buildTrack,
  createProject,
  fetchProjectDetail,
  fetchProjects,
  fetchSegment,
  fetchStatus,
  fetchTrack,
  outputUrlIfExists,
  renderVideo,
  segmentSelected,
  streamSegment,
  uploadVideo,
} from "./api/client";
import type {
  Keyframe,
  Project,
  ProjectVideo,
  TrackData,
  UploadResponse,
} from "./api/client";

function toGridItem(kf: Keyframe, videoId: string): GridItem {
  return {
    frameIdx: kf.frameIdx,
    url: `/frames/${videoId}/${String(kf.frameIdx).padStart(6, "0")}.jpg`,
    bbox: kf.bbox,
    origin: kf.origin,
  };
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProject] = useState<string | null>(null);
  const [projectVideos, setProjectVideos] = useState<ProjectVideo[]>([]);
  const [newName, setNewName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [prompt, setPrompt] = useState("dumbbell");
  const [numSamples, setNumSamples] = useState(15);
  const [segmenting, setSegmenting] = useState(false);
  const [grid, setGrid] = useState<GridItem[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [rerunning, setRerunning] = useState(false);
  const [calls, setCalls] = useState<number | null>(null);
  const [building, setBuilding] = useState(false);
  const [track, setTrack] = useState<TrackData | null>(null);
  const [trackId, setTrackId] = useState<string | null>(null);
  const [padding, setPadding] = useState(0.15);
  const [aspect, setAspect] = useState("");
  const [rendering, setRendering] = useState(false);
  const [croppedUrl, setCroppedUrl] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchProjects();
        if (cancelled) return;
        setProjects(list);
        if (list.length > 0) setCurrentProject(list[0].projectId);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "projects failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!currentProject) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await fetchProjectDetail(currentProject);
        if (!cancelled) setProjectVideos(detail.videos);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "project fetch failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentProject]);

  async function refreshVideos(projectId: string) {
    try {
      setProjectVideos((await fetchProjectDetail(projectId)).videos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "project fetch failed");
    }
  }

  function resetFlow() {
    setGrid(null);
    setSelected([]);
    setCalls(null);
    setTrack(null);
    setTrackId(null);
    setCroppedUrl(null);
  }

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    resetFlow();
    try {
      setResult(await uploadVideo(file, currentProject ?? undefined));
      if (currentProject) await refreshVideos(currentProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleSegment() {
    if (!result || !prompt.trim()) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setSegmenting(true);
    setError(null);
    setTrack(null);
    setCroppedUrl(null);
    setGrid([]);
    setSelected([]);
    setCalls(null);
    const videoId = result.videoId;
    const text = prompt.trim();
    let done = 0;
    try {
      await streamSegment(
        videoId,
        text,
        numSamples,
        (e) => {
          if (e.type === "keyframe" && e.keyframe) {
            const item = toGridItem(e.keyframe, videoId);
            setGrid((prev) =>
              [...(prev ?? []), item].sort((a, b) => a.frameIdx - b.frameIdx),
            );
          } else if (e.type === "done") {
            done = e.sam3Calls ?? 0;
          } else if (e.type === "error") {
            throw new Error(e.detail ?? "stream failed");
          }
        },
        controller.signal,
      );
      setCalls(done);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "segment failed");
    } finally {
      setSegmenting(false);
    }
  }

  function toggleSelect(frameIdx: number) {
    setSelected((prev) =>
      prev.includes(frameIdx)
        ? prev.filter((f) => f !== frameIdx)
        : [...prev, frameIdx],
    );
  }

  async function handleRerun() {
    if (!result || !prompt.trim() || selected.length === 0) return;
    setRerunning(true);
    setError(null);
    try {
      const seg = await segmentSelected(result.videoId, prompt.trim(), selected);
      setCalls((prev) => (prev ?? 0) + seg.sam3Calls);
      setGrid(seg.keyframes.map((k) => toGridItem(k, result.videoId)));
      setSelected([]);
      try {
        setTrack(await fetchTrack(result.videoId));
      } catch {
        setTrack(null);
      }
      const out = await outputUrlIfExists(result.videoId);
      setCroppedUrl(out ? `${out}?t=${Date.now()}` : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "re-run failed");
    } finally {
      setRerunning(false);
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
    if (result) {
      const item = toGridItem(update.keyframe, result.videoId);
      setGrid((prev) =>
        prev
          ? [...prev.filter((i) => i.frameIdx !== item.frameIdx), item].sort(
              (a, b) => a.frameIdx - b.frameIdx,
            )
          : [item],
      );
    }
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

  async function handleCreateProject() {
    if (!newName.trim()) return;
    setError(null);
    try {
      const created = await createProject(newName.trim());
      setProjects((prev) => [...prev, created]);
      setCurrentProject(created.projectId);
      setNewName("");
      setResult(null);
      resetFlow();
    } catch (err) {
      setError(err instanceof Error ? err.message : "create project failed");
    }
  }

  async function handleResume(video: ProjectVideo) {
    abortRef.current?.abort();
    setError(null);
    setSegmenting(false);
    resetFlow();
    try {
      const status = await fetchStatus(video.videoId);
      setResult({
        videoId: status.videoId,
        metadata: status.metadata,
        originalUrl: status.originalUrl,
      });
      try {
        const seg = await fetchSegment(video.videoId);
        setGrid(seg.keyframes.map((k) => toGridItem(k, video.videoId)));
        setCalls(seg.sam3Calls);
        if (seg.keyframes.length > 0) setPrompt(seg.keyframes[0].prompt);
      } catch {
        setGrid(null);
      }
      try {
        const t = await fetchTrack(video.videoId);
        setTrack(t);
        setTrackId(t.videoId);
        setPrompt(t.prompt);
      } catch {
        setTrack(null);
      }
      setCroppedUrl(await outputUrlIfExists(video.videoId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "resume failed");
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
        <Stack direction="row" spacing={2} sx={{ alignItems: "flex-end" }}>
          <FormControl sx={{ minWidth: 200 }}>
            <InputLabel id="project-label">Project</InputLabel>
            <Select
              labelId="project-label"
              label="Project"
              value={currentProject ?? ""}
              onChange={(e) => {
                setCurrentProject(e.target.value);
                setResult(null);
                resetFlow();
              }}
            >
              {projects.map((p) => (
                <MenuItem key={p.projectId} value={p.projectId}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="New project"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            sx={{ flexGrow: 1 }}
          />
          <Button
            variant="outlined"
            onClick={handleCreateProject}
            disabled={!newName.trim()}
          >
            Create
          </Button>
        </Stack>
        {projectVideos.length > 0 && (
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
            {projectVideos.map((v) => (
              <Chip
                key={v.videoId}
                label={v.metadata.filename}
                onClick={() => handleResume(v)}
                color={result?.videoId === v.videoId ? "primary" : "default"}
              />
            ))}
          </Stack>
        )}
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
              Segmenting {numSamples} keyframes — {grid?.length ?? 0} so far,
              one SAM3 call each.
            </Typography>
            <LinearProgress />
          </Box>
        )}
        {calls !== null && !segmenting && (
          <Typography variant="body2" color="text.secondary">
            {calls} SAM3 calls so far. Tweak the prompt and re-run any time.
          </Typography>
        )}
        {grid && grid.length > 0 && (
          <KeyframeGrid
            items={grid}
            selected={selected}
            onToggle={toggleSelect}
            onSelectAll={() => setSelected(grid.map((g) => g.frameIdx))}
            onClear={() => setSelected([])}
            disabled={segmenting || rerunning || building}
          />
        )}
        {grid && !segmenting && grid.length > 0 && (
          <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
            <Button
              variant="outlined"
              onClick={handleRerun}
              disabled={rerunning || building || selected.length === 0}
            >
              Re-run selected ({selected.length})
            </Button>
            <Typography variant="body2" color="text.secondary">
              Edit the prompt above, select cells, re-run — 1 SAM3 call per cell.
            </Typography>
          </Stack>
        )}
        {rerunning && <LinearProgress />}
        {grid && !segmenting && grid.length > 0 && (
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
