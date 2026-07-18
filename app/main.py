from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from filelock import Timeout
from pydantic import BaseModel, Field

from app.agent_api import router as agent_router
from app.config import settings
from app.graph_service import KnowledgeGraphService
from app.memory_service import MemoryService
from app.research import answer
from app.search_service import (
    SearchCorruptionError,
    SearchProviderError,
    SearchStorageError,
    SemanticSearchService,
)
from app.storage import create_project, extract_text, load_project, save_source
from app.wiki_service import WikiService
from dikson_li.memory import (
    MemoryCorruptionError,
    MemoryCreate,
    MemoryKind,
    MemoryRecord,
    MemoryStorageError,
)
from dikson_li.search import SearchEntityType, SearchResponse
from dikson_li.graph import (
    DuplicateEntityError,
    EdgeType,
    GraphCorruptionError,
    GraphEdge,
    GraphEdgeCreate,
    GraphNode,
    GraphNodeCreate,
    GraphSnapshot,
    GraphStorageError,
    NodeType,
)
from dikson_li.wiki import (
    DuplicateSlugError,
    WikiCorruptionError,
    WikiHistoryEntry,
    WikiPage,
    WikiPageCreate,
    WikiPageUpdate,
    WikiStatus,
    WikiStorageError,
)

app = FastAPI(title="DIKSON AI System", version="0.6.0")
app.include_router(agent_router)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2)
    description: str = ""


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2)


def memory_service() -> MemoryService:
    return MemoryService(settings.dikson_data_dir)


def ensure_project(project_id: str) -> None:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc


def storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальное хранилище памяти повреждено")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "DIKSON"}


@app.post("/projects")
def projects_create(payload: ProjectCreate) -> dict:
    return create_project(payload.name, payload.description)


@app.get("/projects/{project_id}")
def projects_get(project_id: str) -> dict:
    ensure_project(project_id)
    return load_project(project_id)


@app.post(
    "/projects/{project_id}/memory",
    response_model=MemoryRecord,
    summary="Добавить запись в append-only память проекта",
)
def memory_add(project_id: str, payload: MemoryCreate) -> MemoryRecord:
    ensure_project(project_id)
    try:
        return memory_service().create(project_id, payload)
    except (MemoryCorruptionError, MemoryStorageError) as exc:
        raise storage_error() from exc


@app.get(
    "/projects/{project_id}/memory",
    response_model=list[MemoryRecord],
    summary="Получить последние записи памяти проекта",
)
def memory_list(
    project_id: str,
    kind: MemoryKind | None = None,
    tag: str | None = None,
    source_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[MemoryRecord]:
    ensure_project(project_id)
    try:
        return memory_service().list(
            project_id,
            kind=kind,
            tag=tag,
            source_id=source_id,
            limit=limit,
        )
    except (MemoryCorruptionError, MemoryStorageError) as exc:
        raise storage_error() from exc


@app.get(
    "/projects/{project_id}/memory/{memory_id}",
    response_model=MemoryRecord,
    summary="Получить запись памяти по идентификатору",
)
def memory_get(project_id: str, memory_id: str) -> MemoryRecord:
    ensure_project(project_id)
    try:
        return memory_service().get(project_id, memory_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Запись памяти не найдена") from exc
    except (MemoryCorruptionError, MemoryStorageError) as exc:
        raise storage_error() from exc


@app.post("/projects/{project_id}/sources")
async def sources_upload(project_id: str, file: UploadFile = File(...)) -> dict:
    try:
        load_project(project_id)
        content = await file.read()
        text = extract_text(file.filename or "source.txt", content)
        return save_source(project_id, file.filename or "source.txt", text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/search")
def semantic_search(
    project_id: str,
    q: Annotated[str, Query(min_length=1, max_length=1_000)],
    entity_type: SearchEntityType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    min_score: Annotated[float, Query(ge=0, le=1)] = 0.05,
    include_archived: bool = False,
) -> SearchResponse:
    ensure_project(project_id)
    try:
        results = SemanticSearchService(settings.dikson_data_dir, project_id).search(
            q,
            entity_type=entity_type,
            limit=limit,
            min_score=min_score,
            include_archived=include_archived,
        )
        return SearchResponse(results=results)
    except (
        SearchCorruptionError,
        SearchStorageError,
        MemoryCorruptionError,
        MemoryStorageError,
        WikiCorruptionError,
        WikiStorageError,
        GraphCorruptionError,
        GraphStorageError,
        Timeout,
    ) as exc:
        raise HTTPException(
            status_code=500, detail="Локальный поисковый индекс повреждён"
        ) from exc
    except SearchProviderError as exc:
        raise HTTPException(
            status_code=503, detail="Провайдер семантического поиска недоступен"
        ) from exc


@app.post("/projects/{project_id}/research")
def research(project_id: str, payload: ResearchRequest) -> dict:
    try:
        return answer(project_id, payload.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc

def wiki_store(project_id: str):
    ensure_project(project_id)
    return WikiService(settings.dikson_data_dir, project_id).store


def wiki_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальное Wiki-хранилище повреждено")


@app.post(
    "/projects/{project_id}/wiki/pages",
    response_model=WikiPage,
    status_code=201,
    summary="Создать Wiki-страницу",
)
def wiki_page_create(project_id: str, payload: WikiPageCreate) -> WikiPage:
    try:
        return wiki_store(project_id).create(project_id, payload)
    except DuplicateSlugError as exc:
        raise HTTPException(status_code=409, detail="Wiki slug уже существует") from exc
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


@app.get(
    "/projects/{project_id}/wiki/pages",
    response_model=list[WikiPage],
    summary="Найти Wiki-страницы",
)
def wiki_pages_list(
    project_id: str,
    tag: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
) -> list[WikiPage]:
    try:
        status = None if include_archived else WikiStatus.ACTIVE
        return wiki_store(project_id).list(status=status, tag=tag, query=q)
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


@app.get(
    "/projects/{project_id}/wiki/pages/{page_id}",
    response_model=WikiPage,
    summary="Получить Wiki-страницу и backlinks",
)
def wiki_page_get(project_id: str, page_id: str) -> WikiPage:
    try:
        return wiki_store(project_id).get(page_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wiki-страница не найдена") from exc
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


@app.put(
    "/projects/{project_id}/wiki/pages/{page_id}",
    response_model=WikiPage,
    summary="Обновить Wiki-страницу с сохранением истории",
)
def wiki_page_update(project_id: str, page_id: str, payload: WikiPageUpdate) -> WikiPage:
    try:
        return wiki_store(project_id).update(page_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wiki-страница не найдена") from exc
    except DuplicateSlugError as exc:
        raise HTTPException(status_code=409, detail="Wiki slug уже существует") from exc
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


@app.delete(
    "/projects/{project_id}/wiki/pages/{page_id}",
    response_model=WikiPage,
    summary="Архивировать Wiki-страницу без физического удаления",
)
def wiki_page_archive(
    project_id: str,
    page_id: str,
    actor: str = "user",
    reason: str = "archive",
) -> WikiPage:
    try:
        return wiki_store(project_id).archive(page_id, actor=actor, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wiki-страница не найдена") from exc
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


@app.get(
    "/projects/{project_id}/wiki/pages/{page_id}/history",
    response_model=list[WikiHistoryEntry],
    summary="Получить историю Wiki-страницы",
)
def wiki_page_history(project_id: str, page_id: str) -> list[WikiHistoryEntry]:
    try:
        return wiki_store(project_id).history(page_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Wiki-страница не найдена") from exc
    except (WikiCorruptionError, WikiStorageError, Timeout) as exc:
        raise wiki_storage_error() from exc


def graph_service(project_id: str) -> KnowledgeGraphService:
    ensure_project(project_id)
    return KnowledgeGraphService(settings.dikson_data_dir, project_id)


def graph_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальное Graph-хранилище повреждено")


@app.get(
    "/projects/{project_id}/graph",
    response_model=GraphSnapshot,
    summary="Получить Knowledge Graph проекта",
)
def graph_snapshot(
    project_id: str,
    node_type: NodeType | None = None,
    edge_type: EdgeType | None = None,
    q: str | None = None,
) -> GraphSnapshot:
    try:
        return graph_service(project_id).snapshot(
            node_type=node_type, edge_type=edge_type, query=q
        )
    except (GraphCorruptionError, GraphStorageError, Timeout) as exc:
        raise graph_storage_error() from exc


@app.post(
    "/projects/{project_id}/graph/nodes",
    response_model=GraphNode,
    status_code=201,
    summary="Добавить внешнюю сущность в Knowledge Graph",
)
def graph_node_create(project_id: str, payload: GraphNodeCreate) -> GraphNode:
    try:
        return graph_service(project_id).add_node(payload)
    except DuplicateEntityError as exc:
        raise HTTPException(status_code=409, detail="Graph entity уже существует") from exc
    except (GraphCorruptionError, GraphStorageError, Timeout) as exc:
        raise graph_storage_error() from exc


@app.post(
    "/projects/{project_id}/graph/edges",
    response_model=GraphEdge,
    status_code=201,
    summary="Добавить связь в Knowledge Graph",
)
def graph_edge_create(project_id: str, payload: GraphEdgeCreate) -> GraphEdge:
    try:
        return graph_service(project_id).add_edge(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Graph node не найден") from exc
    except (GraphCorruptionError, GraphStorageError, Timeout) as exc:
        raise graph_storage_error() from exc


@app.get(
    "/projects/{project_id}/graph/nodes/{node_id}/neighbors",
    response_model=GraphSnapshot,
    summary="Получить соседей узла Knowledge Graph",
)
def graph_neighbors(project_id: str, node_id: str) -> GraphSnapshot:
    try:
        return graph_service(project_id).neighbors(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Graph node не найден") from exc
    except (GraphCorruptionError, GraphStorageError, Timeout) as exc:
        raise graph_storage_error() from exc
