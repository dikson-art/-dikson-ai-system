from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.memory_service import MemoryService
from app.research import answer
from app.storage import create_project, extract_text, load_project, save_source, search_sources
from dikson_li.memory import (
    MemoryCorruptionError,
    MemoryCreate,
    MemoryKind,
    MemoryRecord,
    MemoryStorageError,
)

app = FastAPI(title="DIKSON AI System", version="0.2.0")


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
def sources_search(project_id: str, q: str) -> dict:
    ensure_project(project_id)
    return {"results": search_sources(project_id, q)}


@app.post("/projects/{project_id}/research")
def research(project_id: str, payload: ResearchRequest) -> dict:
    try:
        return answer(project_id, payload.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
