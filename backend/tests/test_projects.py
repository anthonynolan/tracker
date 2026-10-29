"""Phase 8 tests: projects + upload attachment."""

from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


def _upload(client, project_id=None) -> dict:
    with open(FIXTURE, "rb") as fh:
        params = {"projectId": project_id} if project_id else None
        resp = client.post("/api/videos/upload", params=params,
                           files={"file": ("tiny.mp4", fh, "video/mp4")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_list_creates_default_once(client):
    first = client.get("/api/projects")
    assert first.status_code == 200
    projects = first.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "Default Project"
    assert projects[0]["videoIds"] == []
    second = client.get("/api/projects").json()["projects"]
    assert [p["projectId"] for p in second] == [projects[0]["projectId"]]


def test_create_and_blank_rejected(client):
    created = client.post("/api/projects", json={"name": "  FP  "})
    assert created.status_code == 200
    assert created.json()["name"] == "FP"
    assert created.json()["videoIds"] == []
    assert client.post("/api/projects", json={"name": "   "}).status_code == 400
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert len(client.get("/api/projects").json()["projects"]) == 2


def test_detail_restores_videos(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["projectId"]
    v1 = _upload(client, pid)["videoId"]
    v2 = _upload(client, pid)["videoId"]
    detail = client.get(f"/api/projects/{pid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["projectId"] == pid and body["name"] == "P"
    assert body["videoIds"] == [v1, v2]
    assert [v["videoId"] for v in body["videos"]] == [v1, v2]
    assert all(v["metadata"]["filename"] == "tiny.mp4" for v in body["videos"])


def test_unknown_and_malformed_project(client):
    assert client.get("/api/projects/" + "0" * 32).status_code == 404
    assert client.get("/api/projects/nope").status_code == 404


def test_upload_guards_project_and_defaults(client, tmp_path):
    resp = client.post("/api/videos/upload", params={"projectId": "0" * 32},
                       files={"file": ("tiny.mp4", b"data", "video/mp4")})
    assert resp.status_code == 404
    uploads = tmp_path / "uploads"
    assert not uploads.exists() or not list(uploads.iterdir())
    vid = _upload(client)["videoId"]
    default = client.get("/api/projects").json()["projects"][0]
    assert default["name"] == "Default Project"
    assert vid in default["videoIds"]
