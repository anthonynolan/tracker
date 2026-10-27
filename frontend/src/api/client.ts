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
