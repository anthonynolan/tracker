# Video Cropper with SAM3 Auto-Tracking - Project Overview

## Goal
Web app to upload a video, enter a text prompt like "dumbbell" or "dancer", and automatically produce a cropped video that follows that object.

We minimize SAM3 cost by sampling evenly-spaced keyframes, segmenting those, and linearly interpolating between them. User can fix drift by adding keyframes.

## Tech Stack
- **Frontend:** React + Vite, MUI, HTML5 video + canvas for bbox overlay, timeline scrubber
- **Backend:** Python + FastAPI, ffmpeg for extract / re-encode; `uv` manages the Python env and deps (project-local `.venv`, `uv.lock`), no direct pip
- **Segmentation:** SAM3 with text-prompt - real API integration, key from .env
- **Storage V1:** File system (relative to repo root): data/uploads/{videoId}/, data/frames/{videoId}/, data/masks/{videoId}/, data/outputs/{videoId}/
- **Storage V2:** MongoDB (abstracted)

## Env / Secrets
- API key is in `.env` file at repo root: `MODEL_API_KEY=...`
- This key is for ALL Meta AI models (SAM3 now, text models later) - not SAM3-specific
- Backend MUST load via `python-dotenv` / `pydantic-settings`. Never log key, never expose to frontend.
- Add `.env` to `.gitignore`, create `.env.example` with `MODEL_API_KEY=your_key_here`
- Config file: `backend/config.py` -> `BaseSettings` with `model_api_key: str` loaded from MODEL_API_KEY

## Core Concept - Keyframe Sampling + Interpolation
1. Upload -> keep the mp4 for playback; extract only N evenly spaced KEYFRAMES for SAM3 (default 15, configurable)
2. User enters prompt -> Backend calls SAM3 ONLY on keyframes: `segment(image, prompt)` -> bbox + mask
3. Frontend shows sampled keyframes with bbox. User can tweak prompt and re-run (only N calls)
4. Build TRACK: linear interpolation of bbox x,y,w,h between keyframes for every intermediate frame
5. Render cropped video using interpolated crop rects
6. User plays cropped video, if drift at frame F -> click "Add keyframe here"
7. That BREAKS segment [K_i, K_{i+1}] into [K_i, F] + [F, K_{i+1}]. Run SAM3 ONLY on frame F, insert, re-interpolate those two sub-segments, re-render. 1 extra API call.

## Data Model
Video { videoId, width, height, fps, duration, totalFrames }
Keyframe { frameIdx, timestamp, bbox: {x,y,w,h} normalized 0-1, maskPath, prompt, confidence? optional (API returns no score; spike 2026-10-27) }
Track { videoId, prompt, keyframes: Keyframe[], interpolatedBoxes: BBox[] }
Job { jobId, type, status, progress, sam3Calls }

## API
POST /api/videos/upload -> { videoId, metadata }
GET /api/videos/{videoId}/frames (keyframes incl. fix frames)
POST /api/videos/{videoId}/segment { prompt, numSamples? } -> runs SAM3 on keyframes -> { keyframes }
POST /api/videos/{videoId}/track { prompt } -> builds interpolated track -> { trackId }
POST /api/videos/{videoId}/keyframes { frameIdx } -> SAM3 on single frame, insert, re-interpolate
POST /api/videos/{videoId}/render { trackId, padding, aspectRatio } -> { outputUrl }
GET /api/videos/{videoId}/status
GET /api/videos/{videoId}/output

## Phases

### Phase 1: Upload + Preview
- MUI dropzone, FastAPI upload, save with UUID, ffprobe metadata

### Phase 2: Frame Extraction + Sampling
- getSampleFrameIndices(totalFrames, numSamples) -> evenly spaced
- Save frames, GET /frames?sample=keyframe
- No SAM3 yet

### Phase 3: SAM3 Text-Prompt Segmentation - REAL SERVICE
- NO STUB. Real implementation.
- `backend/services/sam3_service.py`: class SAM3Service(api_key=config.model_api_key)
- Method segment(image_path, text_prompt) -> bbox, mask, confidence - calls SAM3 via MODEL_API_KEY
- Same key will be reused later for text models, so keep service generic: `MetaAIService` or inject key

### Phase 4: Tracker - Linear Interpolation
- track_builder.py: lerp between keyframes for all frames, smoothing
- Store track.json

### Phase 5: Render Cropped Video
- Fixed-size window (track-max box + padding + aspect, even-px) with moving smoothed center -> ffmpeg crop, re-encode with audio
- Preview original vs cropped

### Phase 6: Interactive Refinement - Break Interpolation
- UI "Fix this frame" button on current playback frame
- POST /keyframes {frameIdx}, SAM3 on that one frame, insert sorted, split segment, re-interpolate affected range only, auto re-render
- Timeline shows added keyframes

### Phase 7: Storage Abstraction
- Storage interface, filesystem impl, prep for MongoDB

## Constraints
- Work ONE phase at a time. Stop and wait for approval.
- SAM3 calls ONLY on sampled keyframes + user-added frames. Never loop over all frames.
- API key from .env in backend only. Frontend must never see it.
- All bboxes normalized 0-1.