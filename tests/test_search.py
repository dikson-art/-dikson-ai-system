import json
from pathlib import Path

from app.search_service import OpenAIEmbeddingModel, SemanticSearchService
from dikson_li.graph import GraphNodeCreate
from dikson_li.memory import JsonlMemoryStore
from dikson_li.search import (
    LocalHashEmbeddingModel,
    SearchDocument,
    SemanticSearchEngine,
)
from dikson_li.wiki import MarkdownWikiStore, WikiPageCreate


def test_local_vectors_are_deterministic_and_rank_relevant_content() -> None:
    model = LocalHashEmbeddingModel(dimensions=128)
    assert model.embed(["Память проекта"])[0] == model.embed(["Память проекта"])[0]

    documents = [
        SearchDocument(
            id="memory:1",
            project_id="project",
            entity_type="memory",
            entity_id="1",
            title="fact",
            text="Распределённая память хранит решения проекта",
        ),
        SearchDocument(
            id="wiki:1",
            project_id="project",
            entity_type="wiki_page",
            entity_id="1",
            title="Рецепты",
            text="Приготовление яблочного пирога",
        ),
    ]

    hits = SemanticSearchEngine(model).search("память проекта", documents)

    assert hits[0].id == "memory:1"
    assert 0 < hits[0].score <= 1


def test_openai_embedding_adapter_uses_current_batch_contract() -> None:
    class Embeddings:
        def create(self, **kwargs):
            self.arguments = kwargs
            item = type("Item", (), {"index": 0, "embedding": [0.25, 0.75]})()
            return type("Response", (), {"data": [item]})()

    embeddings = Embeddings()
    client = type("Client", (), {"embeddings": embeddings})()

    vectors = OpenAIEmbeddingModel("test-key", "text-embedding-3-small", client=client).embed(
        ["query"]
    )

    assert vectors == [[0.25, 0.75]]
    assert embeddings.arguments == {
        "input": ["query"],
        "model": "text-embedding-3-small",
        "encoding_format": "float",
    }


def test_service_projects_memory_wiki_sources_and_explicit_graph(tmp_path: Path) -> None:
    project_id = "search-project"
    project_root = tmp_path / "projects" / project_id
    (project_root / "sources").mkdir(parents=True)
    memory = JsonlMemoryStore(tmp_path / "projects").append(
        project_id=project_id,
        content="Векторный поиск по долговременной памяти",
        kind="decision",
        tags=["retrieval"],
    )
    page = MarkdownWikiStore(project_root / "wiki").create(
        project_id,
        WikiPageCreate(title="Архитектура агентов", content="Планировщик координирует агентов"),
    )
    source = {
        "id": "source-1",
        "filename": "research.txt",
        "chunks": ["Исследование косинусного сходства"],
    }
    (project_root / "sources" / "source-1.json").write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    service = SemanticSearchService(tmp_path, project_id)
    person = service.graph.add_node(
        GraphNodeCreate(type="person", label="Ада Лавлейс", properties={"role": "author"})
    )

    assert service.search("долговременная память")[0].id == f"memory:{memory.id}"
    assert service.search("координирует агентов")[0].id == f"wiki:{page.id}"
    assert service.search("косинусное сходство")[0].source_id == source["id"]
    assert service.search("Ада Лавлейс")[0].id == f"graph:{person.id}"


def test_entity_filter_and_graph_relation_boost(tmp_path: Path) -> None:
    project_id = "relations"
    project_root = tmp_path / "projects" / project_id
    (project_root / "sources").mkdir(parents=True)
    memory = JsonlMemoryStore(tmp_path / "projects").append(
        project_id=project_id, content="Редкий термин орбитал", kind="fact"
    )
    page = MarkdownWikiStore(project_root / "wiki").create(
        project_id,
        WikiPageCreate(
            title="Связанная страница",
            content="Контекст без точного слова",
            related_memory_ids=[memory.id],
        ),
    )
    service = SemanticSearchService(tmp_path, project_id)

    wiki_hits = service.search("орбитал", entity_type="wiki_page", min_score=0)

    assert wiki_hits[0].id == f"wiki:{page.id}"
    assert wiki_hits[0].score > 0
