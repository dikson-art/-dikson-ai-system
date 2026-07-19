from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def test_documentation_snapshot_api_creates_pending_proposal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Documentation"}).json()["id"]
    url = f"/projects/{project_id}/documentation/snapshots"

    first = client.post(url, json={"title": "DIKSON", "idempotency_key": "release"})
    second = client.post(url, json={"title": "Changed", "idempotency_key": "release"})

    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    snapshot = first.json()
    assert {item["path"] for item in snapshot["artifacts"]} == {
        "generated/api-reference.md",
        "generated/agent-catalog.md",
    }
    assert "GET /health" in snapshot["artifacts"][0]["content"]
    proposals = client.get(
        f"/projects/{project_id}/agents/proposals",
        params={"agent_id": "documentation", "status": "pending"},
    ).json()
    assert [item["proposal"]["id"] for item in proposals] == [snapshot["proposal_id"]]
    assert len(client.get(url).json()) == 1
    assert client.get(f"{url}/{snapshot['id']}").json() == snapshot


def test_documentation_api_missing_and_corrupt_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path)
    assert client.get("/projects/missing/documentation/snapshots").status_code == 404
    project_id = client.post("/projects", json={"name": "Broken Docs"}).json()["id"]
    root = tmp_path / "projects" / project_id / "documentation"
    root.mkdir(parents=True)
    (root / "snapshots.jsonl").write_text("{broken}\n", encoding="utf-8")
    response = client.get(f"/projects/{project_id}/documentation/snapshots")
    assert response.status_code == 500
    assert response.json() == {"detail": "Documentation storage is corrupted"}
