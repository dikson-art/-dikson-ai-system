from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_project(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    return client.post("/projects", json={"name": "Wiki Project"}).json()["id"]


def test_wiki_crud_search_backlinks_history_and_soft_delete(tmp_path, monkeypatch) -> None:
    project_id = create_project(tmp_path, monkeypatch)
    target = client.post(
        f"/projects/{project_id}/wiki/pages",
        json={
            "title": "Архитектура памяти",
            "tags": ["architecture", "memory"],
            "source_ids": ["source-1"],
            "related_memory_ids": ["memory-1"],
            "content": "Каноническое ядро памяти.",
            "actor": "wiki-agent",
            "reason": "research",
        },
    )
    assert target.status_code == 201
    target_id = target.json()["id"]

    backlink = client.post(
        f"/projects/{project_id}/wiki/pages",
        json={
            "title": "Связанная страница",
            "related_page_ids": [target_id],
            "content": f"См. [[{target_id}]] и специальный термин.",
        },
    )
    assert backlink.status_code == 201

    fetched = client.get(f"/projects/{project_id}/wiki/pages/{target_id}")
    assert fetched.status_code == 200
    assert fetched.json()["backlinks"] == [backlink.json()["id"]]

    searched = client.get(
        f"/projects/{project_id}/wiki/pages", params={"q": "СПЕЦИАЛЬНЫЙ"}
    )
    assert [page["id"] for page in searched.json()] == [backlink.json()["id"]]
    tagged = client.get(
        f"/projects/{project_id}/wiki/pages", params={"tag": "memory"}
    )
    assert [page["id"] for page in tagged.json()] == [target_id]

    updated = client.put(
        f"/projects/{project_id}/wiki/pages/{target_id}",
        json={"content": "Проверенная версия.", "actor": "review-agent", "reason": "review"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Проверенная версия."

    history = client.get(f"/projects/{project_id}/wiki/pages/{target_id}/history")
    assert history.status_code == 200
    assert [entry["action"] for entry in history.json()] == ["create", "update"]
    assert history.json()[1]["previous"]["content"] == "Каноническое ядро памяти."

    archived = client.delete(
        f"/projects/{project_id}/wiki/pages/{target_id}",
        params={"actor": "user", "reason": "superseded"},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    active = client.get(f"/projects/{project_id}/wiki/pages")
    assert target_id not in [page["id"] for page in active.json()]
    all_pages = client.get(
        f"/projects/{project_id}/wiki/pages", params={"include_archived": True}
    )
    assert target_id in [page["id"] for page in all_pages.json()]


def test_wiki_api_errors_are_explicit_and_safe(tmp_path, monkeypatch) -> None:
    project_id = create_project(tmp_path, monkeypatch)
    first = client.post(
        f"/projects/{project_id}/wiki/pages", json={"title": "First", "slug": "same"}
    )
    assert first.status_code == 201
    duplicate = client.post(
        f"/projects/{project_id}/wiki/pages", json={"title": "Second", "slug": "same"}
    )
    assert duplicate.status_code == 409
    assert client.get(f"/projects/{project_id}/wiki/pages/missing").status_code == 404
    assert client.get("/projects/missing/wiki/pages").status_code == 404

    page_path = tmp_path / "projects" / project_id / "wiki" / "pages" / f"{first.json()['id']}.md"
    page_path.write_text("invalid front matter", encoding="utf-8")
    corrupt = client.get(f"/projects/{project_id}/wiki/pages/{first.json()['id']}")
    assert corrupt.status_code == 500
    assert corrupt.json() == {"detail": "Локальное Wiki-хранилище повреждено"}
