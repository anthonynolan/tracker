"""FastAPI entrypoint (Phase 1)."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import DATA_DIR
from backend.logging_config import configure_logging
from backend.routers import videos

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


for _dirname in ("uploads", "frames", "masks", "outputs"):
    _dir = DATA_DIR / _dirname
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(f"/{_dirname}", StaticFiles(directory=_dir), name=_dirname)

logger.info("data dir: %s", DATA_DIR)
