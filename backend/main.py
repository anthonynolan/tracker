"""FastAPI entrypoint (Phase 1)."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.logging_config import configure_logging
from backend.routers import videos
from backend.services.storage import FileSystemStorage, get_storage

configure_logging()
logger = logging.getLogger("tracker")

app = FastAPI(title="tracker")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(videos.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


_store = get_storage()
if not isinstance(_store, FileSystemStorage):
    raise RuntimeError(
        "static file mounts require the filesystem storage backend")
for _dirname in ("uploads", "frames", "masks", "outputs"):
    app.mount(f"/{_dirname}",
              StaticFiles(directory=_store.media_dir(_dirname)), name=_dirname)

logger.info("storage root: %s", _store.root)
