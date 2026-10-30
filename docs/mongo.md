# MongoDB Storage (Phase 11)

All persistence goes through the `Storage` interface (`backend/services/storage.py`).
`FileSystemStorage` (default) keeps `data/`; `MongoStorage` keeps documents in
MongoDB plus binaries in GridFS, with a write-through local cache so
path-based callers (ffmpeg, PIL, `FileResponse`) work unchanged.

## Layout in Mongo

Database: `MONGO_DATABASE` (`tracker` dev, `tracker_prod` prod).

- Collections (docs keyed by `_id` = the hex id): `videos` (metadata),
  `keyframes`, `tracks`, `renders`, `projects`.
- GridFS bucket `media` (`media.files` / `media.chunks`): every binary as
  `{kind}/{videoId}/{name}` (`uploads/…/original.mp4`, `frames/…/000001.jpg`,
  `masks/…/000001.png`, `outputs/…/cropped.mp4`) with `{videoId, kind}`
  metadata. Buckets/collections are created on first write — except on Atlas,
  where the database needs one explicit collection at creation time: use
  `projects` (the app's own first write anyway).
- Local cache: `data/.mongo-cache/{database}/` mirrors the filesystem layout.
  Writes go to cache + Mongo together; reads fetch on cache miss. Safe to
  delete any time (rebuilds on demand); single-writer assumed.

Media URLs are identical on both backends. Filesystem keeps `StaticFiles`;
MongoDB serves GridFS bytes through `backend/routers/media.py` with `Range`
support for `<video>` seeking.

## Connection settings

| Var | Purpose |
|---|---|
| `STORAGE_BACKEND` | `filesystem` (default) or `mongodb` |
| `MONGO_DATABASE` | database name (`tracker` / `tracker_prod`) |
| `MONGO_URL` | full URL override (local or Atlas) |
| `MONGODB_USER` / `MONGODB_PASSWORD` / `MONGODB_HOST` | Atlas parts; the URL is built as `mongodb+srv://user:pass@host/?authSource=admin&retryWrites=true&w=majority` (password URL-quoted) |

`MONGO_URL` wins when set. With no URL and no host, the driver targets
`mongodb://localhost:27017/`.

## Atlas checklist

1. Database `tracker` (+ `projects` collection to bootstrap it).
2. Database user with `readWrite` on `tracker`.
3. Network Access allows the app's IP.
4. `.env`: `MONGODB_USER`, `MONGODB_PASSWORD`, `MONGODB_HOST`
   (`<cluster>.abc123.mongodb.net`, no scheme), `MONGO_DATABASE=tracker`.

## Local mongod (dev/test)

```bash
# one-time: unpack a server tarball somewhere scratch (6.0.x for focal)
./bin/mongod --dbpath /tmp/mongo-data --port 27017 --bind_ip 127.0.0.1 \
  --nounixsocket --fork --logpath /tmp/mongod.log
```

The conformance suite (`backend/tests/test_mongo.py`) runs the same flow
tests against MongoDB and skips cleanly when no server answers on
`localhost:27017`.

## Import + cutover (dev)

```bash
# 1. Copy data/ -> Mongo (additive, rerunnable; filesystem untouched)
PYTHONPATH=. uv run python scripts/import_to_mongo.py
# single video: --video-id VID ; start clean: --drop (drops the db first)

# 2. Flip the backend (restart required)
# .env: STORAGE_BACKEND=mongodb

# 3. Verify: /health, open the app, resume a video (grid + track + output
# must match the filesystem state), upload a fresh video end to end
```

Only then repeat for prod (`MONGO_DATABASE=tracker_prod`, empty or
selectively imported), during a maintenance note.

## Rollback

Set `STORAGE_BACKEND=filesystem` and restart — no migration back. Loss
boundary: writes made after the cutover live only in Mongo. Re-import
(`--video-id` per straggler) or accept the gap.

## Troubleshooting

- **Server selection timeout on startup paths**: wrong host, IP not
  allowlisted (Atlas), or no local server. First failing request surfaces it
  (5 s timeout); the app boots regardless (lazy client).
- **Atlas auth fails**: user needs `readWrite` on the database; the built URL
  pins `authSource=admin`. Special characters in the password are quoted
  automatically — only with the parts form, not a hand-written `MONGO_URL`.
- **`mongodb+srv://` DNS errors**: SRV needs working DNS (`dnspython` ships
  with the backend). Behind a broken resolver, use a full `MONGO_URL` with
  explicit hosts instead.
- **First reads are slow**: cold cache downloading from Atlas; subsequent
  reads are local.
