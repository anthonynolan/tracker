"""Project grouping (Phase 8): videos belong to projects; default auto-created."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services import storage

DEFAULT_PROJECT_NAME = "Default Project"


def _new_project(name: str) -> dict:
    return {"projectId": uuid.uuid4().hex, "name": name,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "videoIds": []}


def list_projects() -> list[dict]:
    """All projects, creating the default on first use."""
    store = storage.get_storage()
    projects = store.list_projects()
    if not projects:
        default = _new_project(DEFAULT_PROJECT_NAME)
        store.write_project(default["projectId"], default)
        return [default]
    return projects


def create_project(name: str) -> dict:
    if not name.strip():
        raise ValueError("project name must not be blank")
    list_projects()  # ensure the default exists first
    store = storage.get_storage()
    project = _new_project(name.strip())
    store.write_project(project["projectId"], project)
    return project


def get_project(project_id: str) -> dict | None:
    return storage.get_storage().read_project(project_id)


def default_project() -> dict:
    """Earliest-created project (the auto-created default), making it if none."""
    projects = storage.get_storage().list_projects()
    if projects:
        return projects[0]
    return list_projects()[0]


def attach_video(project_id: str, video_id: str) -> dict | None:
    """Add a video to a project; `None` when the project is unknown."""
    store = storage.get_storage()
    project = store.read_project(project_id)
    if project is None:
        return None
    if video_id not in project["videoIds"]:
        project["videoIds"] = [*project["videoIds"], video_id]
        store.write_project(project_id, project)
    return project
