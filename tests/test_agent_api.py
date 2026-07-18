from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_project(tmp_path, monkeypatch, name: str) -> str:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    return client.post("/projects", json={"name": name}).json()["id"]


def test_agent_registry_run_policy_and_proposal_decision_api(tmp_path, monkeypatch) -> None:
    project_id = create_project(tmp_path, monkeypatch, "Agent Framework")
    registry = client.get("/agents")
    assert registry.status_code == 200
    assert {item["id"] for item in registry.json()} == {
        "research",
        "planning",
        "memory",
        "wiki",
        "coding",
        "review",
        "documentation",
    }

    forbidden = client.post(
        f"/projects/{project_id}/agents/research/runs",
        json={"objective": "Change Wiki", "requested_tools": ["wiki_propose"]},
    )
    assert forbidden.status_code == 403
    run = client.post(
        f"/projects/{project_id}/agents/coding/runs",
        json={"objective": "Prepare a patch", "requested_tools": ["code_read"]},
    )
    assert run.status_code == 201
    proposal = client.post(
        f"/projects/{project_id}/agents/coding/runs/{run.json()['id']}/proposals",
        json={
            "type": "code_change",
            "title": "Patch proposal",
            "summary": "A reviewable patch",
            "payload": {"files": ["app/main.py"]},
        },
    )
    assert proposal.status_code == 201
    pending = client.get(f"/projects/{project_id}/agents/proposals", params={"status": "pending"})
    assert [item["proposal"]["id"] for item in pending.json()] == [proposal.json()["id"]]
    decision = client.post(
        f"/projects/{project_id}/agents/proposals/{proposal.json()['id']}/decisions",
        json={"outcome": "approved", "reviewer": "lead", "reason": "looks good"},
    )
    assert decision.status_code == 201
    duplicate = client.post(
        f"/projects/{project_id}/agents/proposals/{proposal.json()['id']}/decisions",
        json={"outcome": "rejected", "reviewer": "lead", "reason": "too late"},
    )
    assert duplicate.status_code == 409


def test_agent_memory_requires_approval_and_is_idempotent(tmp_path, monkeypatch) -> None:
    project_id = create_project(tmp_path, monkeypatch, "Agent Memory API")
    run = client.post(
        f"/projects/{project_id}/agents/documentation/runs",
        json={"objective": "Document the API"},
    ).json()
    proposal = client.post(
        f"/projects/{project_id}/agents/documentation/runs/{run['id']}/proposals",
        json={
            "type": "agent_memory",
            "title": "Remember convention",
            "summary": "Preserve the documentation convention",
            "payload": {"content": "Use Russian API descriptions", "kind": "decision"},
        },
    ).json()
    commit_url = f"/projects/{project_id}/agents/proposals/{proposal['id']}/commit-memory"
    assert client.post(commit_url).status_code == 409
    client.post(
        f"/projects/{project_id}/agents/proposals/{proposal['id']}/decisions",
        json={"outcome": "approved", "reviewer": "architect", "reason": "accepted"},
    )
    first = client.post(commit_url)
    second = client.post(commit_url)
    assert first.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    memory = client.get(f"/projects/{project_id}/agents/documentation/memory")
    assert [item["id"] for item in memory.json()] == [first.json()["id"]]


def test_agent_api_missing_project_and_corruption_are_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    assert client.get("/projects/missing/agents/runs").status_code == 404
    project_id = client.post("/projects", json={"name": "Agent Errors"}).json()["id"]
    agents_dir = tmp_path / "projects" / project_id / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "runs.jsonl").write_text("{broken}\n", encoding="utf-8")

    response = client.get(f"/projects/{project_id}/agents/runs")

    assert response.status_code == 500
    assert response.json() == {"detail": "Локальный журнал агентов повреждён"}
    assert "line" not in response.text
