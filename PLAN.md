# Video Cropper with SAM3 Auto-Tracking — Implementation Plan

> Grill status: **Final** — accepted 2026-10-27. See Grill Log.

Source of truth: `PROJECT.md`.

## Goal

Web app to upload a video, enter a text prompt like "dumbbell" or "dancer", and automatically
produce a cropped video that follows that object.

Cost control: sample N evenly-spaced keyframes, run SAM3 only on those (+ user-added fix frames),
linearly interpolate bboxes for intermediate frames.

## Tech Stack

- **Frontend:** React + Vite, MUI, HTML5 video + canvas bbox overlay, timeline scrubber
- **Backend:** Python + FastAPI, ffmpeg for extract / re-encode; `uv` manages the Python env and deps (project-local `.venv`, `uv.lock`), no direct pip
- **Segmentation:** SAM3 text-prompt, real API integration, key from `.env`
- **Storage V1:** Filesystem: `data/uploads/{videoId}/`, `data/frames/{videoId}/`,
  `data/masks/{videoId}/`, `data/outputs/{videoId}/`
- **Storage V2:** MongoDB (abstracted in Phase 7)

## Env / Secrets

- Key in repo-root `.env`: `MODEL_API_KEY=...` (for ALL Meta AI models, not SAM3-specific).
- Backend loads via `pydantic-settings` / `python-dotenv`. Never log key, never expose to frontend.
- `.env` in `.gitignore`. `.env.example` contains `MODEL_API_KEY=your_key_here`.
- Config: `backend/config.py` -> `BaseSettings` with `model_api_key: str` from `MODEL_API_KEY`.

## Core Concept — Keyframe Sampling + Interpolation

1. Upload -> keep the mp4 for playback; extract only N evenly spaced KEYFRAMES for SAM3 (default 15).
2. Prompt -> backend calls SAM3 ONLY on keyframes: `segment(image, prompt)` -> bbox + mask.
3. Frontend shows keyframes with bbox. User can tweak prompt and re-run (only N calls).
4. Build TRACK: linear interpolation of bbox x,y,w,h between keyframes for every frame.
5. Render cropped video using interpolated crop rects.
6. Drift at frame F -> "Add keyframe here" breaks `[K_i, K_{i+1}]` into `[K_i, F] + [F, K_{i+1}]`.
   Run SAM3 ONLY on F, re-interpolate those two sub-segments, re-render. 1 extra call.

## Data Model

- Video `{ videoId, width, height, fps, duration, totalFrames }`
- Keyframe `{ frameIdx, timestamp, bbox: {x,y,w,h} normalized 0-1, maskPath, prompt, confidence? }`
  (`confidence` optional — API returns no score; spike 2026-10-27, accepted.)
- Track `{ videoId, prompt, keyframes: Keyframe[], interpolatedBoxes: BBox[] }`
- Job `{ jobId, type, status, progress, sam3Calls }`
- Project `{ projectId, name, createdAt, videoIds[] }`

## API

- `POST /api/videos/upload` -> `{ videoId, metadata }`
- `GET /api/videos/{videoId}/frames` -> keyframes (incl. user-added fix frames)
- `POST /api/videos/{videoId}/segment { prompt, numSamples? }` -> `{ keyframes }`
- `POST /api/videos/{videoId}/track { prompt }` -> `{ trackId }`
- `GET /api/videos/{videoId}/track` -> `{ videoId, prompt, keyframes, interpolatedBoxes }`
- `POST /api/videos/{videoId}/keyframes { frameIdx }` -> SAM3 single frame, insert, re-interpolate
- `POST /api/videos/{videoId}/render { trackId, padding, aspectRatio }` -> `{ outputUrl }`
- `GET /api/videos/{videoId}/status`
- `GET /api/videos/{videoId}/output`
- `POST /api/videos/{videoId}/segment/selected {prompt, frameIndices[]}` -> re-segment subset
- `GET /api/videos/{videoId}/segment/stream` (SSE, no-batch progressive path)
- `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{projectId}`

## Repo Layout (target)

```text
tracker/
  PROJECT.md
  PLAN.md
  README.md
  docs/screenshots/*.png
  .env / .env.example
  pyproject.toml
  backend/
    config.py
    main.py
    routers/videos.py
    routers/projects.py
    services/video_service.py
    services/frame_service.py
    services/sam3_service.py
    services/track_builder.py
    services/render_service.py
    services/storage.py
    services/project_service.py
    models/schemas.py
  frontend/
    package.json, vite.config.ts
    src/App.tsx, api/client.ts
    src/components/Dropzone.tsx, VideoPreview.tsx, KeyframeGrid.tsx, Timeline.tsx
  data/
    uploads/{videoId}/original.mp4 + meta.json
    frames/{videoId}/{frameIdx:06d}.jpg
    masks/{videoId}/{frameIdx:06d}.png
    outputs/{videoId}/cropped.mp4 + track.json
    projects/{projectId}.json
```

## Current State (2026-10-28)

- Phases 0–7 complete: upload/preview, keyframe sampling, real SAM3
  segmentation, lerp tracking, fixed-window render, fix-frame refinement,
  storage abstraction. 52/52 backend tests pass; frontend builds clean.
- Backend: FastAPI (`backend/`); all persistence behind the `Storage`
  interface (`FileSystemStorage` default, `MongoStorage` stub behind
  `STORAGE_BACKEND`). Frontend: Vite + React + MUI (`frontend/`).
- `data/` holds uploads/frames/masks/outputs per video; on-disk layout
  unchanged since Phase 1. No system ffmpeg/ffprobe — bundled binary via
  `imageio-ffmpeg` with ffprobe-when-available fallback.
- Next: Phase 8 (review grid + selective re-run + projects), then Phase 9
  (README + screenshots).

---

## ~~Phase 0 — Foundation (with Phase 1)~~

Tasks:
- [x] Add backend deps via `uv add fastapi uvicorn python-multipart
      pydantic-settings python-dotenv httpx pillow numpy meta-sam-parser`
      (writes `pyproject.toml` + `uv.lock`). Env is project-local `.venv`
      managed by uv; no direct pip. (+ `imageio-ffmpeg` for the ffmpeg fallback, `pytest` dev.)
- [x] `backend/config.py`: `BaseSettings` with `model_api_key: str = Field(alias=MODEL_API_KEY)`.
      (Implemented as `SecretStr` — same env binding, redacts on repr. Deviation.)
- [x] `.gitignore`: add `.env`, `data/uploads/`, `data/frames/`, `data/masks/`,
      `data/outputs/`, `node_modules/`, `dist/`, `.venv/`.
- [x] `.env.example`: `MODEL_API_KEY=your_key_here`.
- [x] Install system `ffmpeg`/`ffprobe`. (Deviation: no sudo/root in sandbox —
      using the `imageio-ffmpeg` bundled binary with ffprobe-when-available.
      See `video_service.probe_metadata`.)

Files to touch: `pyproject.toml`, `uv.lock`, `backend/config.py`, `.gitignore`, `.env.example`.

Verify: `GET /health` OK, config loads without logging key.

## ~~Phase 1 — Upload + Preview~~

Tasks:
- [x] `backend/main.py`: FastAPI app + CORS + static mounts + `/health`.
- [x] `backend/models/schemas.py`: `Video` metadata schemas.
- [x] `backend/services/video_service.py`: save upload by UUID, ffprobe
      `{width,height,fps,duration,totalFrames}`, write `meta.json`.
      (ffprobe JSON when present, else `ffmpeg -i` parse with frame estimate.)
- [x] `backend/routers/videos.py`: `POST /api/videos/upload`,
      `GET /api/videos/{videoId}/status`, `GET /api/videos/{videoId}/output`.
      (Upload also returns `originalUrl` — additive, needed for playback.)
- [x] `frontend/`: Vite + React + MUI scaffold, `Dropzone.tsx` upload,
      `VideoPreview.tsx` original playback + metadata, `api/client.ts`.

Files to touch: `backend/main.py`, `backend/routers/videos.py`,
`backend/services/video_service.py`, `backend/models/schemas.py`,
`frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/**`.

Verify: upload `data/dumbbell_revolution.mp4` -> `meta.json` correct, frontend plays it.

## ~~Phase 2 — Frame Extraction + Sampling~~

Tasks:
- [x] `backend/services/frame_service.py`: `getSampleFrameIndices(totalFrames, numSamples=15)`
      evenly spaced, inclusive of first/last, clamp when `totalFrames < N`. No SAM3.
- [x] Extract ONLY the sampled keyframes via ffmpeg to `data/frames/{videoId}/`
      (fix frames added on demand in Phase 6 land in the same dir). No all-frame
      extraction — preview/scrub plays the mp4; overlay draws on canvas.
      (Extract-on-first-read via `GET /frames?numSamples=`; idempotent skip of
      existing files; steps back past EOF when the estimated frame count
      overshoots — ffmpeg exits 0 with no output there.)
- [x] `GET /api/videos/{videoId}/frames` -> keyframe URLs/indices (incl. fix frames).

Files to touch: `backend/services/frame_service.py`, `backend/routers/videos.py`.

Verify: unit test e.g. 100 frames / 5 -> `[0,25,50,75,99]`; exactly N JPEGs on disk, no others.

## ~~Phase 3 — SAM3 Text-Prompt Segmentation (REAL, no stub)~~

Tasks:
- [x] `backend/services/sam3_service.py`: `class SAM3Service(api_key=...)`
      (or generic `MetaAIService`), `segment(image_path, text_prompt)`
      -> `{bbox 0-1, mask, confidence}`, save mask to `data/masks/{videoId}/`.
      (Returns None on no-detection; frames run sequentially in V1.)
- [x] `POST /api/videos/{videoId}/segment {prompt, numSamples?}`: SAM3 ONLY on N keyframes,
      return `{keyframes}`, track `sam3Calls`. (Misses kept explicit as
      `bbox/maskPath: null`; `keyframes.json` persisted per video; SAM3 errors
      surface as 502 without killing the run on misses.)
- [x] Frontend prompt box + `KeyframeStrip.tsx` with canvas bbox overlay. Re-run allowed.
      (Overlay is a positioned div, not canvas — same visual result, less code.)

Integration (settled from user-provided example, 2026-10-27):
- Base `https://api.meta.ai/v1`; auth `Authorization: Bearer $MODEL_API_KEY`
  (backend only, from `config.model_api_key`; never log key or file bytes).
- `segment(image_path, text_prompt)` = (1) `POST /files` multipart
  `purpose=user_data` + JPEG bytes -> parse `id` as `file_id`, fail loudly if
  missing/invalid; (2) `POST /responses` JSON `{model: "sam-3.1", input:
  [{type: message, role: user, content: [{type: input_text, text: prompt},
  {type: input_image, file_id}]}], stream: true, metadata: {mask_encoding:
  "lossless"}}`, `Accept: text/event-stream`; (3) parse SSE events -> bbox +
  mask (RESPONSE settled by spike 2026-10-27, prompt "dumbbell" — see below).
- Response grammar (spike-verified): final text in `response.output_text.done`
  (accumulate `response.output_text.delta` when streaming incrementally) =
  `<0f>N<|box;x1;y1;x2;y2;w;h|><|mask;x;y;data=...>`. Box pixels are in
  uploaded-image space; `w`/`h` echo image dims (verified 1080x1920; drawn box
  tightly encloses the dumbbell). Normalize: `x=x1/w, y=y1/h, w=(x2-x1)/w,
  h=(y2-y1)/h`; clamp 0-1. Multi-detection shape TBD — spike returned one pair.
  No confidence score exists in the response → `confidence` optional (`None`).
- Mask `data=` = `{h},{w},~<base85>` ("lossless"; spike-verified). `h,w` are the
  box-crop raster dims (box-inclusive: `w=x2-x1+1, h=y2-y1+1`). Decode with Meta's
  `meta-sam-parser` (0.1.0 verified): `decode_mask_to_raster(SegmentationMask(
  encoding="lossless", payload=<after "h,w,">, width=w, height=h))` → bytes of
  0/1, len `w*h` (8-bit coverage thresholded at ≥129). Place the crop at box
  origin `(x1,y1)` in a full-frame raster, save PNG to
  `data/masks/{videoId}/{frameIdx:06d}.png` (overlay verified pixel-tight on the
  spike frame). Encoding notes (from package source): base-85 over ASCII
  0x21–0x7E excluding `" \ , ; < > |`; `~` = lossless magic, `!` = one_bit magic
  (unsupported path — fail loudly). Add `meta-sam-parser` via `uv add` (Phase 0).
- `sam3Calls` counts `segment()` invocations (1 per keyframe / fix frame).
- Upload returns `{id: file_id, ..., status: "uploaded"}` (spike-verified);
  fail loudly if `id` missing. HTTP (httpx): raise on non-2xx; retry 429/5xx
  with backoff, no retry on other 4xx. File lifecycle after inference TBD.
- Non-streaming (`stream: false`) option TBD — implement streaming per example
  unless docs confirm otherwise.

Files to touch: `backend/services/sam3_service.py`, `backend/routers/videos.py`,
`frontend/src/components/KeyframeStrip.tsx`.

Verify: prompt "dumbbell" -> N calls, bboxes 0-1 parsed e2e from live SSE,
masks saved (decode via meta-sam-parser, spike-verified). Key never reaches frontend.

## ~~Phase 4 — Tracker (Linear Interpolation)~~

Tasks:
- [x] `backend/services/track_builder.py`: `lerp` x,y,w,h between keyframes for all frames,
      clamp 0-1, optional moving-average smoothing (window 3-5).
      (Default on, window 5; misses skipped, edge boxes held, dup indices deduped.)
- [x] `POST /api/videos/{videoId}/track {prompt}` -> write `track.json`
      `{videoId,prompt,keyframes,interpolatedBoxes}`.
      (`trackId` = `videoId` in V1; prompt must match segmented prompt (400);
      `track.json` keeps valid keyframes only. Added `GET /track` — the UI and
      later phases must read back what POST wrote.)
- [x] Frontend timeline draws interpolated box on scrub.
      (`Timeline.tsx`: slider + play/pause over the mp4 with overlay box.)
      Follow-up (2026-10-27): fixed portrait letterboxing (overlay now measures
      the shrink-wrapped video content, not the element); added red latest-keyframe
      box beside the green interpolated box plus a legend.

Files to touch: `backend/services/track_builder.py`, `backend/models/schemas.py`,
`backend/routers/videos.py`, `frontend/src/components/Timeline.tsx`.

Verify: two-keyframe midpoint correct; `len(interpolatedBoxes) == totalFrames`.

## ~~Phase 5 — Render Cropped Video~~

Tasks:
- [x] `backend/services/render_service.py`: FIXED-SIZE window — size = max over
      interpolated boxes + padding, aspectRatio-enforced, even-px for h264
      (computed once per track); per-frame position = smoothed box center,
      clamped to frame.
- [x] `POST /api/videos/{videoId}/render {trackId,padding,aspectRatio}`: single ffmpeg
      pass, per-frame crop x/y with constant w/h, re-encode with audio ->
      `data/outputs/{videoId}/cropped.mp4`.
      (Implemented as decode→numpy-crop→encode pipes + audio mux: per-frame
      windows aren't expressible in one crop filter. Renders in display space
      measured from keyframe JPEGs; `GET /output` now serves the file;
      `trackId` must equal `videoId` in V1.)
- [x] Frontend side-by-side original vs cropped.
      (Render button + padding/aspect inputs; `VideoPreview` splits when cropped.)

Files to touch: `backend/services/render_service.py`, `backend/routers/videos.py`,
`frontend/src/components/VideoPreview.tsx`.

Verify: output exists, constant dims across frames, has audio, follows smoothed center.

## ~~Phase 6 — Interactive Refinement (Break Interpolation)~~

Tasks:
- [x] `POST /api/videos/{videoId}/keyframes {frameIdx}`: SAM3 single frame, insert sorted,
      split `[K_i,K_{i+1}]` -> `[K_i,F]+[F,K_{i+1}]`, re-interpolate affected range only,
      update `track.json`, auto re-render.
      (Span = [prev|0, next|end]; smoothing uses old boxes as edge context so the
      rest stays byte-identical. Misses insert explicit nulls without touching the
      track. Re-render reuses stored `render.json` params, else padding 0.1/auto.
      Fix always uses the segmented prompt — prompt changes are Phase 8.)
- [x] Timeline shows original (hollow) + added (filled) keyframes; "Fix this frame" button.
      (Markers from `Keyframe.origin`; fix refreshes track + strip, cache-busts render.)
- [x] Guards: reject duplicates / out-of-range. (409 dup, 400 range, 422 negative.)

Files to touch: `backend/routers/videos.py`, `backend/services/track_builder.py`,
`frontend/src/components/Timeline.tsx`.

Verify: `sam3Calls +1`, only sub-segments changed.

## ~~Phase 7 — Storage Abstraction~~

Tasks:
- [x] `backend/services/storage.py`: `Storage` Protocol + `FileSystemStorage`,
      prep `MongoStorage` behind env flag.
- [x] Route all `save_video/meta/frame/mask/track/output` through interface.
      Keep `uploads/`, `frames/`, `masks/`, `outputs/` paths.

Files to touch: `backend/services/storage.py`, all services/routers using filesystem.

Verify: Phase 1-6 flows pass unchanged with abstraction.

Done 2026-10-28: 52/52 tests (46 existing unchanged + 6 storage);
live real-data smoke (status/frames/track/output) green; on-disk layout
byte-identical; `MongoStorage` raises `NotImplementedError` per op until
implemented; `STORAGE_BACKEND=mongodb` fails fast at startup on static mounts.

---

## Phase 8 — Review Grid + Selective Re-run + Projects

Tasks:
- [ ] `frontend/src/components/KeyframeGrid.tsx`: responsive grid replacing the
      `KeyframeStrip` band. Each cell shows its keyframe + bbox overlay (or an
      explicit "no detection" state) with single / multi / select-all.
      Strip component removed once the grid lands.
- [ ] SAM3 batch research (no code until answered): can one `/responses` call
      take multiple images (multiple `input_image` parts,
      `video_segmentation_format`, or another endpoint)? Record the finding here.
      If batch works, segment keyframes in batches; if not, take the progressive
      path below.
- [ ] Progressive results (no-batch path): stream per-image results to the grid
      as each `segment()` completes instead of waiting for all N. Transport: SSE
      `GET /api/videos/{videoId}/segment/stream` (recommended) or polling —
      decided at implementation.
- [ ] `POST /api/videos/{videoId}/segment/selected {prompt, frameIndices[]}`:
      re-segment ONLY the selected keyframes with a (possibly modified) prompt,
      update `keyframes.json` for those frames, return `{keyframes, sam3Calls}`.
      Powers the fix-one-then-rerun-all loop: retry a miss solo, then re-run
      the batch with the winning prompt.
- [ ] Projects: `backend/services/project_service.py` + `routers/projects.py`.
      A default project is auto-created on first app use; `GET /api/projects`
      lists, `GET /api/projects/{projectId}` restores videos + keyframes +
      prompt state. Persisted through the Phase 7 `Storage` interface
      (`data/projects/{projectId}.json` under filesystem storage).
- [ ] Frontend project switcher: default project opens automatically; user can
      create/switch projects and resume work.
- [ ] Synced playback for original vs rendered: one common play button drives
      both videos on the same frame (side-by-side comparison); pause and seek
      stay in lockstep.

Files to touch: `backend/routers/videos.py`, `backend/routers/projects.py`,
`backend/services/project_service.py`, `backend/services/storage.py`,
`frontend/src/components/KeyframeGrid.tsx`, `frontend/src/App.tsx`,
`frontend/src/api/client.ts`.

Verify: grid shows N cells with misses marked; select-1 re-run costs 1 SAM3 call;
select-all re-run costs N; progressive cells populate before the run finishes
(no-batch path); batch finding recorded; fresh start yields a default project;
reopening a project restores its state.

---

## Phase 9 — README + Screenshots

Tasks:
- [ ] Write `README.md`: what the app does, features per phase, prerequisites
      (`uv`, Python 3.12, Node, system or bundled ffmpeg), env setup
      (`.env` from `.env.example`), quickstart (backend + frontend commands),
      usage walkthrough (upload → prompt → segment → track → render → refine),
      project layout, troubleshooting.
- [ ] Capture screenshots from the RUNNING app (no mockups): upload/dropzone,
      segmentation grid with overlays, track timeline, render side-by-side,
      refinement. Store under `docs/screenshots/`, reference from `README.md`.
- [ ] Re-verify every README command copy-paste fresh (clean-checkout mindset:
      `uv sync`, backend start, `npm install`, frontend start, full flow).

Files to touch: `README.md`, `docs/screenshots/*.png`.

Verify: README quickstart works verbatim on a fresh clone (minus the `.env` key);
screenshots match the current UI; no stale screens from older phases.

---

## Constraints

- Work ONE phase at a time. Stop and wait for approval.
- SAM3 calls ONLY on sampled keyframes + user-added frames. Never loop over all frames.
- API key from `.env` in backend only. Frontend must never see it.
- All bboxes normalized 0-1.

---

## Grill Log (Final — accepted 2026-10-27)

Interview started 2026-10-27. Target document: this file (`PLAN.md`); `PROJECT.md`
synced only if a decision changes the source of truth.

### Settled decisions

1. Scope = paper review only (2026-10-27, user chose option 1). Deliverable is a
   corrected `PLAN.md` (+ `PROJECT.md` sync where the source of truth changes).
   No code, spikes, installs, or new documents.
2. SAM3 reference = user-provided curl example (received 2026-10-27): base
   `https://api.meta.ai/v1`, Bearer `MODEL_API_KEY`, `POST /files`
   (`purpose=user_data`) → `file_id`, then `POST /responses` with
   `model: "sam-3.1"`, message content `[input_text prompt, input_image file_id]`,
   `stream: true`, `metadata.mask_encoding: "lossless"`, SSE response.
   Request side settled; response event → bbox/mask/confidence mapping still open.
3. Package manager = uv (2026-10-27, owner: "use uv for this project rather
   than direct pip install"). All Python env/deps via uv (project-local `.venv`,
   `uv add`/`uv sync`, committed `uv.lock`); no direct pip installs. Applies to
   backend, spike, and future dev envs. Docs updated: PROJECT.md tech stack,
   PLAN.md tech stack + Phase 0 + A1.
4. Spike = run end-to-end with real frame (2026-10-27, user chose option 1).
   Amendment A1 accepted. uv-installed extractor, project-local `.venv`,
   artifacts in `/tmp/spike/`, 1–2 live keyed calls, findings → Phase 3.
5. Spike results (2026-10-27, 1 upload + 1 inference on frame @1s, prompt
   "dumbbell", spend within A1): box grammar `<|box;x1;y1;x2;y2;w;h|>` in
   uploaded-image pixels, w/h echo image dims, drawn box verified tight around
   the dumbbell; no confidence score anywhere in the response; mask `data=`
   encoding undocumented (dims prefix + ~36KB high-entropy chars, not base64).
6. Mask decode = experiments (2026-10-27, user chose option 2). Offline blob
   analysis first, then synthetic known-geometry probe; up to 2 more live
   segment() calls (each = upload + inference). Success = decoded mask
   visualized against the frame.
7. Mask decode settled (2026-10-27, 0 extra live calls): Meta's `meta-sam-parser`
   (0.1.0) decodes `lossless` payloads; overlay verified pixel-tight on the spike
   frame. `data=` = `{h},{w},~<base85>`; crop placed at box origin `(x1,y1)`.
8. Storage paths = relative `data/...` (2026-10-27, user chose option 1).
   Fixed the one `PROJECT.md` line; `PLAN.md` already uniform. Configurability
   deferred to Phase 7 storage abstraction.
9. Frames = keyframes only (2026-10-27, user chose option 1). No all-frame
   extraction; mp4 serves playback, canvas draws overlay. `?sample=all` dropped
   from the API; `GET /frames` lists keyframes incl. fix frames.
10. Render = fixed-size window, moving center (2026-10-27, user chose option 1).
    Size from track-max box + padding + aspect (even-px, once per track); position
    follows smoothed centers clamped to frame. Constant output dims.
11. Segment count param = `numSamples` (2026-10-27, user chose option 1).
    Fixed both API-list lines (`PROJECT.md`, `PLAN.md`) to `{ prompt, numSamples? }`.
12. Current State corrected (2026-10-27, mechanical, no decision needed):
    `.gitignore` already ignores `.env`; `.env.example` drift noted; `.venv`
    (spike) and no-system-ffmpeg noted.

### Open questions

1. (Settled 2026-10-27 by spike for box grammar + coords; confidence → Q7, mask
   decode → Q8) SAM3 response shape. Env (verified 2026-10-27): api.meta.ai reachable (401
   without key on both routes); no ffmpeg/PIL/cv2; PyPI reachable but slow
   (~4-7s TLS handshake via localhost proxy; earlier 000 was a 10s client
   timeout, not a block); mp4 frame extraction viable via a uv-installed
   extractor; convert cannot read mp4 (no ffmpeg delegate).
2. (Settled 2026-10-27, option 1) Storage paths: relative `data/...` everywhere.
3. (Settled 2026-10-27, option 1) Frame extraction: keyframes only, mp4 for playback.
4. (Settled 2026-10-27, option 1) Render: fixed-size window, moving smoothed center.
5. (Settled 2026-10-27, option 1) Segment count param: `numSamples` everywhere.
6. (Settled 2026-10-27 as mechanical correction, decision 12) Current State
   synced to verified reality.
7. (Accepted 2026-10-27 — no veto) `confidence`: no score exists in the
   response → optional, `None` when absent.
8. (Settled 2026-10-27; 0 of the ≤2 authorized live calls used) Mask `data=`
   decode: `meta-sam-parser` `decode_mask_to_raster`, verified by overlay.

### Scope contract (accepted 2026-10-27)

- Boundary (in): edits to `PLAN.md` (grill log + plan corrections); minimal sync
  edits to `PROJECT.md` where a decision changes the source of truth.
- Boundary (out): all runtime code (`backend/`, `frontend/`), tests, spikes,
  config/secret changes, new documents, installs.
- Done means: every open grill question settled or explicitly deferred with an
  owner; corrections applied to the plan; user explicitly accepts this scope
  text and the final doc state (Draft → Final only on that acceptance).
- Staged approval: accepting this grill record approves the plan review only —
  never any implementation phase. Each phase still returns for its own approval
  per project constraints.
- Execution words ("go", "do it all") authorize only the accepted boundary;
  wider work needs new explicit approval, recorded here, or a follow-up with
  its own interview. (No owning issue exists in this repo; this log is the
  coordination surface and will quote the acceptance.)
- Amendment A1 (proposed 2026-10-27, revised after PyPI diagnosis, accepted
  2026-10-27 when owner chose option 1 "I run end-to-end with a real frame"):
  allow one throwaway response-shape spike — uv-installed frame
  extractor (project-local `.venv`) + curl/python3-stdlib, artifacts under `/tmp`,
  1–2 live `MODEL_API_KEY` calls + ≤2 more segment() calls for mask-decode
  experiments (option 2, 2026-10-27), findings recorded in Phase 3, nothing
  committed. Triggered by owner's "can you do a spike to determine response
  details".
- Acceptance (quoted, 2026-10-27, chat): owner replied "ACCEPT" to the settled
  contract + scope text above. No veto on Q7. Grill Log is Final. (No owning
  issue exists; this log is the coordination surface.)
