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
}

export interface FrameRef {
  frameIdx: number;
  url: string;
}

export interface SegmentResponse {
  keyframes: Keyframe[];
  sam3Calls: number;
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
