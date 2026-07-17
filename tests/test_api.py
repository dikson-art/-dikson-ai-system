from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["system"] == "DIKSON"


def test_project_memory_and_search(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project = client.post(
        "/projects",
        json={"name": "Книжный разворот", "description": "Тестовый научный проект"},
    )
    assert project.status_code == 200
    project_id = project.json()["id"]

    memory = client.post(
        f"/projects/{project_id}/memory",
        json={
            "content": "Berry используется для контекста печатной культуры",
            "kind": "decision",
            "tags": ["research", "berry"],
        },
    )
    assert memory.status_code == 201
    assert memory.json()["project_id"] == project_id

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


def test_memory_list_filters_and_gets_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Memory API"}).json()["id"]

    fact = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "The API uses JSONL", "kind": "fact", "tags": ["architecture"]},
    )
    assert fact.status_code == 201
    client.post(
        f"/projects/{project_id}/memory",
        json={"content": "Add relations next", "kind": "task", "tags": ["roadmap"]},
    )

    filtered = client.get(
        f"/projects/{project_id}/memory", params={"kind": "fact", "tag": "architecture"}
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [fact.json()["id"]]

    fetched = client.get(f"/projects/{project_id}/memory/{fact.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "The API uses JSONL"


def test_memory_api_validates_kind_and_missing_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Validation"}).json()["id"]

    invalid = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "Unsupported", "kind": "note"},
    )
    assert invalid.status_code == 422

    missing = client.get(f"/projects/{project_id}/memory/unknown")
    assert missing.status_code == 404

def test_memory_api_accepts_legacy_text_and_relations(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Compatibility"}).json()["id"]

    first = client.post(
        f"/projects/{project_id}/memory",
        json={"text": "  Legacy fact  "},
    )
    assert first.status_code == 201
    assert first.json()["content"] == "Legacy fact"
    assert first.json()["kind"] == "fact"

    related = client.post(
        f"/projects/{project_id}/memory",
        json={
            "content": "Related summary",
            "kind": "summary",
            "related_memory_ids": [first.json()["id"]],
        },
    )
    assert related.status_code == 201
    assert related.json()["related_memory_ids"] == [first.json()["id"]]

    blank = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "   ", "kind": "fact"},
    )
    assert blank.status_code == 422
