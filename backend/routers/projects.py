"""Project endpoints (Phase 8)."""

from fastapi import APIRouter, HTTPException

from backend.models.schemas import (
    Project, ProjectCreateRequest, ProjectDetail, ProjectListResponse,
    ProjectVideo)
from backend.services import project_service, video_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse,
            response_model_by_alias=True)
async def list_projects() -> ProjectListResponse:
    return ProjectListResponse(
        projects=[Project(**p) for p in project_service.list_projects()])


@router.post("", response_model=Project, response_model_by_alias=True)
async def create_project(req: ProjectCreateRequest) -> Project:
    try:
        return Project(**project_service.create_project(req.name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectDetail,
            response_model_by_alias=True)
async def get_project(project_id: str) -> ProjectDetail:
    project = project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown projectId")
    videos = []
    for vid in project["videoIds"]:
        meta = video_service.get_metadata(vid)
        if meta is None:
            continue  # upload gone; the id stays on the project record
        videos.append(ProjectVideo(video_id=vid, metadata=meta))
    return ProjectDetail(**project, videos=videos)
