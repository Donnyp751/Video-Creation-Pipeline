import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(workspace, monkeypatch):
    monkeypatch.setenv("KIDSVIDEO_HOME", str(workspace.root))
    monkeypatch.setenv("KIDSVIDEO_MOCK_PROVIDERS", "1")
    from app.api.main import app

    with TestClient(app) as c:
        yield c


def wait_for(client, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)
        if job["status"] in ("COMPLETE", "FAILED"):
            return job
        time.sleep(0.1)
    raise TimeoutError(job_id)


def test_project_lifecycle(client):
    r = client.post("/api/projects", json={"id": "colors", "title": "Màu Gì Đây?",
                                           "topic": "colors", "duration": 20})
    assert r.status_code == 200
    assert client.post("/api/projects", json={"id": "colors"}).status_code == 409
    assert [p["id"] for p in client.get("/api/projects").json()] == ["colors"]

    job = wait_for(client, client.post("/api/projects/colors/stages/lyrics").json()["job_id"])
    assert job["status"] == "COMPLETE", job

    plan = client.get("/api/projects/colors/plan").json()
    assert plan["review"]["pass"] is True
    status = client.get("/api/projects/colors").json()
    assert status["gates"]["lyrics"]["approved"] is False

    # Music refuses to run before approval; the job records why.
    job = wait_for(client, client.post("/api/projects/colors/stages/music").json()["job_id"])
    assert job["status"] == "FAILED" and "not approved" in job["error"]

    assert client.post("/api/projects/colors/approve/lyrics").status_code == 200
    assert client.get("/api/projects/colors").json()["gates"]["lyrics"]["approved"]

    # Invalid human edits are rejected.
    bad = plan["plan"] | {"scenes": []}
    assert client.put("/api/projects/colors/plan", json=bad).status_code == 422


def test_scene_prompt_override_and_files(client):
    client.post("/api/projects", json={"id": "p1", "topic": "fruit", "duration": 20})
    wait_for(client, client.post("/api/projects/p1/stages/lyrics").json()["job_id"])
    r = client.put("/api/projects/p1/scenes/1/image/prompt", json={"text": "custom prompt"})
    assert r.status_code == 200
    scene = client.get("/api/projects/p1/scenes/1").json()
    assert scene["prompts"]["image"]["override"] == "custom prompt"
    assert client.get("/files/p1/project.yaml").status_code == 200
    assert client.get("/files/p1/%2e%2e/%2e%2e/config/pipeline.yaml").status_code in (403, 404)
    assert client.get("/").status_code == 200
