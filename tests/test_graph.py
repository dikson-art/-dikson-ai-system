from pathlib import Path

import pytest

from app.graph_service import KnowledgeGraphService
from dikson_li.graph import (
    DuplicateEntityError,
    GraphCorruptionError,
    GraphEdgeCreate,
    GraphNodeCreate,
    JsonlGraphRepository,
)
from dikson_li.memory import JsonlMemoryStore
from dikson_li.wiki import MarkdownWikiStore, WikiPageCreate


def test_explicit_nodes_edges_and_duplicate_entity(tmp_path: Path) -> None:
    repository = JsonlGraphRepository(tmp_path)
    person = repository.add_node(
        "project",
        GraphNodeCreate(
            type="person",
            label="Иван Петров",
            entity_id="person-1",
            properties={"role": "author"},
        ),
    )
    article = repository.add_node(
        "project",
        GraphNodeCreate(type="article", label="Исследование", entity_id="article-1"),
    )
    edge = repository.add_edge(
        "project",
        GraphEdgeCreate(
            from_node_id=person.id,
            to_node_id=article.id,
            type="references",
        ),
        known_node_ids={person.id, article.id},
    )

    assert repository.nodes() == [person, article]
    assert repository.edges() == [edge]
    with pytest.raises(DuplicateEntityError):
        repository.add_node(
            "project",
            GraphNodeCreate(type="person", label="Дубликат", entity_id="person-1"),
        )


def test_projection_connects_memory_wiki_sources_and_neighbors(tmp_path: Path) -> None:
    project_id = "graph-project"
    memory_store = JsonlMemoryStore(tmp_path / "projects")
    memory = memory_store.append(
        project_id=project_id,
        content="Факт графа",
        kind="fact",
        source_ids=["source-1"],
    )
    wiki_store = MarkdownWikiStore(tmp_path / "projects" / project_id / "wiki")
    page = wiki_store.create(
        project_id,
        WikiPageCreate(
            title="Страница графа",
            related_memory_ids=[memory.id],
            source_ids=["source-1"],
        ),
    )
    service = KnowledgeGraphService(tmp_path, project_id)

    snapshot = service.snapshot()
    node_ids = {node.id for node in snapshot.nodes}
    assert {
        f"project:{project_id}",
        f"memory:{memory.id}",
        f"wiki:{page.id}",
        "source:source-1",
    } <= node_ids
    assert any(
        edge.from_node_id == f"wiki:{page.id}"
        and edge.to_node_id == f"memory:{memory.id}"
        for edge in snapshot.edges
    )
    neighbors = service.neighbors(f"memory:{memory.id}")
    assert f"wiki:{page.id}" in {node.id for node in neighbors.nodes}


def test_corrupt_graph_row_is_explicit(tmp_path: Path) -> None:
    repository = JsonlGraphRepository(tmp_path)
    repository.nodes_path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(GraphCorruptionError, match="line 1"):
        repository.nodes()
