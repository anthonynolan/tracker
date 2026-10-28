export interface VideoMetadata {
  videoId: string;
  width: number;
  height: number;
  fps: number;
  duration: number;
  totalFrames: number;
  filename: string;
}

export interface UploadResponse {
  videoId: string;
  metadata: VideoMetadata;
  originalUrl: string;
}

export interface StatusResponse {
  videoId: string;
  status: string;
  metadata: VideoMetadata;
}

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Keyframe {
  frameIdx: number;
  timestamp: number;
  bbox: BBox | null;
  maskPath: string | null;
  prompt: string;
  confidence: number | null;
  origin: string;
}

export interface FixKeyframeResponse {
  keyframe: Keyframe;
  sam3Calls: number;
  trackRebuilt: boolean;
  rerendered: boolean;
  outputUrl: string | null;
}

export interface FrameRef {
  frameIdx: number;
  url: string;
}

export interface SegmentResponse {
  keyframes: Keyframe[];
  sam3Calls: number;
}

export interface TrackResponse {
  trackId: string;
  videoId: string;
  prompt: string;
  numFrames: number;
  keyframeCount: number;
}

export interface TrackData {
  videoId: string;
  prompt: string;
  keyframes: Keyframe[];
  interpolatedBoxes: BBox[];
}

export interface RenderResponse {
  outputUrl: string;
  width: number;
  height: number;
  numFrames: number;
}

async function failMessage(resp: Response, fallback: string): Promise<string> {
  const body = await resp.json().catch(() => null);
  const detail = body?.Detail ?? body?.detail ?? body?.message;
  return typeof detail === "string" ? detail : `${fallback}: ${resp.status}`;
}

export async function uploadVideo(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/videos/upload", { method: "POST", body: form });
  if (!resp.ok) throw new Error(await failMessage(resp, "upload failed"));
  return resp.json() as Promise<UploadResponse>;
}

export async function fetchStatus(videoId: string): Promise<StatusResponse> {
  const resp = await fetch(`/api/videos/${videoId}/status`);
  if (!resp.ok) throw new Error(await failMessage(resp, "status failed"));
  return resp.json() as Promise<StatusResponse>;
}

export async function fetchFrames(videoId: string, numSamples = 15): Promise<FrameRef[]> {
  const resp = await fetch(`/api/videos/${videoId}/frames?numSamples=${numSamples}`);
  if (!resp.ok) throw new Error(await failMessage(resp, "frames failed"));
  const body = await resp.json();
  return body.frames as FrameRef[];
}

export async function segmentVideo(
  videoId: string, prompt: string, numSamples = 15,
): Promise<SegmentResponse> {
  const resp = await fetch(`/api/videos/${videoId}/segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, numSamples }),
  });
  if (!resp.ok) throw new Error(await failMessage(resp, "segment failed"));
  return resp.json() as Promise<SegmentResponse>;
}

export async function buildTrack(videoId: string, prompt: string): Promise<TrackResponse> {
  const resp = await fetch(`/api/videos/${videoId}/track`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!resp.ok) throw new Error(await failMessage(resp, "track failed"));
  return resp.json() as Promise<TrackResponse>;
}

export async function fetchTrack(videoId: string): Promise<TrackData> {
  const resp = await fetch(`/api/videos/${videoId}/track`);
  if (!resp.ok) throw new Error(await failMessage(resp, "track fetch failed"));
  return resp.json() as Promise<TrackData>;
}

export async function fixKeyframe(videoId: string, frameIdx: number): Promise<FixKeyframeResponse> {
  const resp = await fetch(`/api/videos/${videoId}/keyframes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ frameIdx }),
  });
  if (!resp.ok) throw new Error(await failMessage(resp, "fix failed"));
  return resp.json() as Promise<FixKeyframeResponse>;
}

export async function renderVideo(
  videoId: string, trackId: string, padding: number, aspectRatio?: string,
): Promise<RenderResponse> {
  const resp = await fetch(`/api/videos/${videoId}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trackId, padding, aspectRatio: aspectRatio || null }),
  });
  if (!resp.ok) throw new Error(await failMessage(resp, "render failed"));
  return resp.json() as Promise<RenderResponse>;
}
