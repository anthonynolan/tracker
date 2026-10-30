"""One-shot import: filesystem data/ layout -> MongoDB (Phase 11).

Additive (rerunnable): reads data/, writes Mongo; the filesystem tree is
untouched. Connection comes from settings (MONGO_URL or MONGODB_* parts).

Usage:
    PYTHONPATH=. uv run python scripts/import_to_mongo.py [--database NAME]
        [--video-id VID] [--root data] [--drop]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import get_settings  # noqa: E402
from backend.services.storage import (  # noqa: E402
    FileSystemStorage, MongoStorage, build_mongo_url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=None,
                        help="default: settings MONGO_DATABASE")
    parser.add_argument("--video-id", default=None,
                        help="import one video (skips projects)")
    parser.add_argument("--root", default="data",
                        help="filesystem data dir (default: data)")
    parser.add_argument("--drop", action="store_true",
                        help="drop the database first")
    args = parser.parse_args()

    settings = get_settings()
    database = args.database or settings.mongo_database
    root = Path(args.root)
    root = root if root.is_absolute() else Path.cwd() / root
    fs = FileSystemStorage(root)
    mongo = MongoStorage(url=build_mongo_url(settings), database=database)
    if args.drop:
        mongo.drop_database()
        print(f"dropped {database}")

    uploads = fs.root / "uploads"
    if args.video_id:
        vids = [args.video_id]
    elif uploads.exists():
        vids = sorted(p.name for p in uploads.iterdir() if p.is_dir())
    else:
        vids = []

    counts = {"videos": 0, "frames": 0, "masks": 0, "outputs": 0,
              "projects": 0}
    for vid in vids:
        meta = fs.read_metadata(vid)
        orig = fs.original_path(vid)
        if meta is None or orig is None:
            print(f"skip {vid}: incomplete upload")
            continue
        mongo.create_video(vid, orig.name, orig.read_bytes())
        mongo.write_metadata(vid, meta)
        counts["videos"] += 1
        for idx in fs.list_frames(vid):
            name = f"{idx:06d}.jpg"
            mongo.stage_media("frames", vid, name,
                              (fs.root / "frames" / vid / name).read_bytes())
            counts["frames"] += 1
        masks_dir = fs.root / "masks" / vid
        if masks_dir.exists():
            for png in sorted(masks_dir.glob("*.png")):
                mongo.stage_media("masks", vid, png.name, png.read_bytes())
                counts["masks"] += 1
        keyframes = fs.read_keyframes(vid)
        if keyframes is not None:
            mongo.write_keyframes(vid, keyframes)
        track = fs.read_track(vid)
        if track is not None:
            mongo.write_track(vid, track)
        params = fs.read_render_params(vid)
        if params is not None:
            mongo.write_render_params(vid, params)
        cropped = fs.root / "outputs" / vid / "cropped.mp4"
        if cropped.exists():
            mongo.stage_media("outputs", vid, "cropped.mp4",
                              cropped.read_bytes())
            counts["outputs"] += 1
    if args.video_id is None:
        for proj in fs.list_projects():
            mongo.write_project(proj["projectId"], proj)
            counts["projects"] += 1
    summary = ", ".join(f"{v} {k}" for k, v in counts.items())
    print(f"imported into {database}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
