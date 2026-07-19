from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def setup_repository(path: Path) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    target = path / "api.txt"
    target.write_text("before\n", encoding="utf-8")
    git(path, "add", "api.txt")
    git(path, "commit", "-m", "Initial")
    target.write_text("after\n", encoding="utf-8")
    patch = git(path, "diff", "--", "api.txt") + "\n"
    target.write_text("before\n", encoding="utf-8")
    return patch


def test_git_api_requires_approved_coding_proposal(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    repositories_dir = tmp_path / "repositories"
    monkeypatch.setattr(settings, "dikson_data_dir", data_dir)
    monkeypatch.setattr(settings, "git_repositories_dir", repositories_dir)
    project_id = client.post("/projects", json={"name": "Git API"}).json()["id"]
    repository = repositories_dir / project_id
    patch = setup_repository(repository)
    head = git(repository, "rev-parse", "HEAD")

    status = client.get(f"/projects/{project_id}/git/status")
    assert status.status_code == 200
    assert status.json()["clean"] is True
    run = client.post(
        f"/projects/{project_id}/agents/coding/runs",
        json={"objective": "Prepare patch", "requested_tools": ["code_propose"]},
    ).json()
    proposal = client.post(
        f"/projects/{project_id}/agents/coding/runs/{run['id']}/proposals",
        json={
            "type": "code_change",
            "title": "Change API file",
            "summary": "Reviewed unified patch",
            "payload": {
                "branch": "agent/api-change",
                "commit_message": "Apply API change",
                "patch": patch,
                "expected_head": head,
            },
        },
    ).json()
    execute_url = f"/projects/{project_id}/git/proposals/{proposal['id']}/execute"
    assert client.post(execute_url, json={"actor": "operator"}).status_code == 409
    client.post(
        f"/projects/{project_id}/agents/proposals/{proposal['id']}/decisions",
        json={"outcome": "approved", "reviewer": "lead", "reason": "safe"},
    )

    executed = client.post(execute_url, json={"actor": "operator"})

    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    assert executed.json()["reviewer"] == "lead"
    assert client.post(execute_url, json={"actor": "operator"}).json() == executed.json()
    assert len(client.get(f"/projects/{project_id}/git/executions").json()) == 1
    assert git(repository, "show", "agent/api-change:api.txt") == "after"


def test_git_api_handles_missing_project_repository_and_bad_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "git_repositories_dir", tmp_path / "repositories")
    assert client.get("/projects/missing/git/status").status_code == 404
    project_id = client.post("/projects", json={"name": "Missing Repo"}).json()["id"]
    response = client.get(f"/projects/{project_id}/git/status")
    assert response.status_code == 409
    assert response.json() == {"detail": "configured repository does not exist"}
