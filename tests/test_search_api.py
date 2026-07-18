import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_unified_search_api_and_source_compatibility(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Semantic Search"}).json()["id"]
    memory = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "Архитектурное решение о векторном индексе", "kind": "decision"},
    ).json()
    client.post(
        f"/projects/{project_id}/wiki/pages",
        json={"title": "Совсем другая Wiki", "content": "Материал о планировании"},
    )
    uploaded = client.post(
        f"/projects/{project_id}/sources",
        files={"file": ("vectors.txt", "Косинусное сходство векторов", "text/plain")},
    ).json()

    response = client.get(
        f"/projects/{project_id}/search",
        params={"q": "векторный индекс", "entity_type": "memory"},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["entity_id"] == memory["id"]
    source_response = client.get(
        f"/projects/{project_id}/search",
        params={"q": "косинусное сходство", "entity_type": "source"},
    )
    source_hit = source_response.json()["results"][0]
    assert source_hit["source_id"] == uploaded["id"]
    assert source_hit["filename"] == "vectors.txt"
    assert source_hit["chunk"] == 0


def test_search_validation_missing_project_and_corrupt_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Search Errors"}).json()["id"]
    assert client.get(f"/projects/{project_id}/search", params={"q": ""}).status_code == 422
    assert (
        client.get(f"/projects/{project_id}/search", params={"q": "valid", "limit": 0}).status_code
        == 422
    )
    assert client.get("/projects/missing/search", params={"q": "valid"}).status_code == 404

    source_dir = tmp_path / "projects" / project_id / "sources"
    (source_dir / "broken.json").write_text(json.dumps({"id": "broken"}), encoding="utf-8")
    corrupt = client.get(f"/projects/{project_id}/search", params={"q": "valid"})
    assert corrupt.status_code == 500
    assert corrupt.json() == {"detail": "Локальный поисковый индекс повреждён"}


def test_openai_search_provider_requires_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    monkeypatch.setattr("app.config.settings.search_embedding_provider", "openai")
    monkeypatch.setattr("app.config.settings.openai_api_key", None)
    project_id = client.post("/projects", json={"name": "Provider Error"}).json()["id"]

    response = client.get(f"/projects/{project_id}/search", params={"q": "knowledge"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Провайдер семантического поиска недоступен"
    }
