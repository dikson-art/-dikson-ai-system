from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_graph_api_projection_explicit_entities_filters_and_neighbors(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Graph Project"}).json()["id"]
    uploaded = client.post(
        f"/projects/{project_id}/sources",
        files={"file": ("graph.txt", "Graph document", "text/plain")},
    ).json()
    memory = client.post(
        f"/projects/{project_id}/memory",
        json={"content": "Graph memory", "kind": "fact", "source_ids": ["source-1"]},
    ).json()
    page = client.post(
        f"/projects/{project_id}/wiki/pages",
        json={"title": "Graph Wiki", "related_memory_ids": [memory["id"]]},
    ).json()
    person = client.post(
        f"/projects/{project_id}/graph/nodes",
        json={"type": "person", "label": "Анна", "entity_id": "person-anna"},
    )
    assert person.status_code == 201
    edge = client.post(
        f"/projects/{project_id}/graph/edges",
        json={
            "from_node_id": person.json()["id"],
            "to_node_id": f"wiki:{page['id']}",
            "type": "mentions",
        },
    )
    assert edge.status_code == 201

    snapshot = client.get(f"/projects/{project_id}/graph")
    assert snapshot.status_code == 200
    assert f"memory:{memory['id']}" in {node["id"] for node in snapshot.json()["nodes"]}
    document = next(
        node for node in snapshot.json()["nodes"] if node["id"] == f"source:{uploaded['id']}"
    )
    assert document["type"] == "document"
    assert document["label"] == "graph.txt"
    filtered = client.get(
        f"/projects/{project_id}/graph", params={"node_type": "person", "q": "АННА"}
    )
    assert [node["id"] for node in filtered.json()["nodes"]] == [person.json()["id"]]

    neighbors = client.get(
        f"/projects/{project_id}/graph/nodes/{person.json()['id']}/neighbors"
    )
    assert neighbors.status_code == 200
    assert f"wiki:{page['id']}" in {node["id"] for node in neighbors.json()["nodes"]}


def test_graph_api_errors_are_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Graph Errors"}).json()["id"]
    payload = {"type": "article", "label": "Article", "entity_id": "article-1"}
    assert client.post(f"/projects/{project_id}/graph/nodes", json=payload).status_code == 201
    assert client.post(f"/projects/{project_id}/graph/nodes", json=payload).status_code == 409
    missing_edge = client.post(
        f"/projects/{project_id}/graph/edges",
        json={"from_node_id": "missing", "to_node_id": "also-missing"},
    )
    assert missing_edge.status_code == 404
    assert client.get("/projects/missing/graph").status_code == 404

    nodes_path = tmp_path / "projects" / project_id / "graph" / "nodes.jsonl"
    nodes_path.write_text("{broken}\n", encoding="utf-8")
    corrupt = client.get(f"/projects/{project_id}/graph")
    assert corrupt.status_code == 500
    assert corrupt.json() == {"detail": "Локальное Graph-хранилище повреждено"}
