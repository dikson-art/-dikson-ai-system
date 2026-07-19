from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def test_research_study_api_and_quick_compatibility(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Research API"}).json()["id"]
    client.post(
        f"/projects/{project_id}/memory",
        json={"kind": "fact", "content": "Memory uses append-only JSONL."},
    )

    quick = client.post(
        f"/projects/{project_id}/research",
        json={"question": "How is memory stored?"},
    )
    assert quick.status_code == 200
    assert quick.json()["used_model"] is False
    assert quick.json()["evidence"][0]["id"].startswith("memory:")

    created = client.post(
        f"/projects/{project_id}/research/studies",
        json={
            "question": "How is memory stored?",
            "queries": ["append-only JSONL"],
            "idempotency_key": "api-study",
        },
    )
    assert created.status_code == 201
    study_id = created.json()["study"]["id"]
    repeated = client.post(
        f"/projects/{project_id}/research/studies",
        json={"question": "Changed question", "idempotency_key": "api-study"},
    )
    assert repeated.json()["study"]["id"] == study_id
    assert (
        client.post(f"/projects/{project_id}/research/studies/{study_id}/advance").status_code
        == 409
    )

    approved = client.post(
        f"/projects/{project_id}/research/studies/{study_id}/decision",
        json={"outcome": "approved", "reviewer": "lead", "reason": "safe"},
    )
    assert approved.json()["status"] == "approved"
    activated = client.post(
        f"/projects/{project_id}/research/studies/{study_id}/activate",
        json={"actor": "lead", "reason": "execute"},
    )
    assert activated.json()["status"] == "active"
    completed = client.post(f"/projects/{project_id}/research/studies/{study_id}/advance")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["report"]["proposal_id"]
    assert len(client.get(f"/projects/{project_id}/research/studies").json()) == 1


def test_research_api_missing_and_corrupt_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path)
    assert client.get("/projects/missing/research/studies").status_code == 404
    project_id = client.post("/projects", json={"name": "Research Corrupt"}).json()["id"]
    root = tmp_path / "projects" / project_id / "research"
    root.mkdir(parents=True)
    (root / "studies.jsonl").write_text("{broken}\n", encoding="utf-8")

    response = client.get(f"/projects/{project_id}/research/studies")

    assert response.status_code == 500
    assert response.json() == {"detail": "Локальное хранилище исследований повреждено"}
    assert "line" not in response.text
