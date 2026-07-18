from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from dikson_li.memory import JsonlMemoryStore


client = TestClient(app)


def create_test_project(tmp_path: Path, monkeypatch, name: str = "Memory API") -> str:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()["id"]


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["system"] == "DIKSON"


def test_project_memory_and_search(tmp_path, monkeypatch) -> None:
    project_id = create_test_project(tmp_path, monkeypatch, "Книжный разворот")
    memory = client.post(
        f"/projects/{project_id}/memory",
        json={"text": "Berry используется для контекста печатной культуры", "kind": "decision"},
    )
    assert memory.status_code == 200
    assert memory.json()["content"].startswith("Berry")

    upload = client.post(
        f"/projects/{project_id}/sources",
        files={
            "file": (
                "berry.txt",
                "Печатная культура эпохи Эдо и распространение информации.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 200
    search = client.get(f"/projects/{project_id}/search", params={"q": "печатная культура"})
    assert search.status_code == 200
    assert search.json()["results"][0]["filename"] == "berry.txt"


def test_api_write_is_readable_by_canonical_core(tmp_path, monkeypatch) -> None:
    project_id = create_test_project(tmp_path, monkeypatch)
    created = client.post(
        f"/projects/{project_id}/memory",
        json={
            "content": "API record",
            "kind": "summary",
            "tags": ["integration"],
            "source_ids": ["source-api"],
            "related_memory_ids": ["previous"],
            "metadata": {"actor": "api"},
        },
    )
    assert created.status_code == 200

    records = JsonlMemoryStore(tmp_path / "projects").list(project_id)
    assert [record.id for record in records] == [created.json()["id"]]
    assert records[0].metadata == {"actor": "api"}


def test_core_write_is_readable_and_filterable_by_api(tmp_path, monkeypatch) -> None:
    project_id = create_test_project(tmp_path, monkeypatch, "Core bridge")
    store = JsonlMemoryStore(tmp_path / "projects")
    fact = store.append(
        project_id=project_id,
        content="Core record",
        kind="fact",
        tags=["bridge"],
        source_ids=["source-core"],
    )
    store.append(project_id=project_id, content="Other", kind="task")

    filtered = client.get(
        f"/projects/{project_id}/memory",
        params={"kind": "fact", "tag": "bridge", "source_id": "source-core", "limit": 1},
    )
    assert filtered.status_code == 200
    assert [record["id"] for record in filtered.json()] == [fact.id]

    fetched = client.get(f"/projects/{project_id}/memory/{fact.id}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "Core record"


def test_memory_api_validation_and_missing_resources(tmp_path, monkeypatch) -> None:
    project_id = create_test_project(tmp_path, monkeypatch, "Validation")
    assert client.post(
        f"/projects/{project_id}/memory", json={"content": "   ", "kind": "fact"}
    ).status_code == 422
    assert client.post(
        f"/projects/{project_id}/memory", json={"content": "Unknown", "kind": "note"}
    ).status_code == 422
    assert client.get(f"/projects/{project_id}/memory/unknown").status_code == 404
    assert client.get("/projects/missing/memory").status_code == 404
    assert client.get(f"/projects/{project_id}/memory", params={"limit": 0}).status_code == 422


def test_corrupt_storage_returns_safe_500(tmp_path, monkeypatch) -> None:
    project_id = create_test_project(tmp_path, monkeypatch, "Corruption")
    path = tmp_path / "projects" / project_id / "memory.jsonl"
    path.write_text("{broken-json}\n", encoding="utf-8")

    response = client.get(f"/projects/{project_id}/memory")

    assert response.status_code == 500
    assert response.json() == {"detail": "Локальное хранилище памяти повреждено"}
    assert "line" not in response.text

    append_response = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "Must not append", "kind": "fact"},
    )
    assert append_response.status_code == 500
    assert path.read_text(encoding="utf-8") == "{broken-json}\n"
