from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.research import answer
from app.storage import create_project, extract_text, load_project, save_project, save_source, search_sources

app = FastAPI(title="DIKSON AI System", version="0.1.0")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2)
    description: str = ""


class MemoryEntry(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "confirmed"


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "DIKSON"}


@app.post("/projects")
def projects_create(payload: ProjectCreate) -> dict:
    return create_project(payload.name, payload.description)


@app.get("/projects/{project_id}")
def projects_get(project_id: str) -> dict:
    try:
        return load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc


@app.post("/projects/{project_id}/memory")
def memory_add(project_id: str, payload: MemoryEntry) -> dict:
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    entry = {"kind": payload.kind, "text": payload.text}
    project["memory"].append(entry)
    save_project(project)
    return entry


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
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    return {"results": search_sources(project_id, q)}


@app.post("/projects/{project_id}/research")
def research(project_id: str, payload: ResearchRequest) -> dict:
    try:
        return answer(project_id, payload.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
