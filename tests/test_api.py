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
        json={"text": "Berry используется для контекста печатной культуры", "kind": "decision"},
    )
    assert memory.status_code == 200

    upload = client.post(
        f"/projects/{project_id}/sources",
        files={"file": ("berry.txt", "Печатная культура эпохи Эдо и распространение информации.", "text/plain")},
    )
    assert upload.status_code == 200

    search = client.get(f"/projects/{project_id}/search", params={"q": "печатная культура"})
    assert search.status_code == 200
    assert search.json()["results"][0]["filename"] == "berry.txt"
