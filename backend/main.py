"""FastAPI entrypoint (Phase 1)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import DATA_DIR
from backend.routers import videos

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


for _dirname in ("uploads", "frames", "outputs"):
    _dir = DATA_DIR / _dirname
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(f"/{_dirname}", StaticFiles(directory=_dir), name=_dirname)
