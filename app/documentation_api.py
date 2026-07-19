from fastapi import APIRouter, HTTPException, Request
from filelock import Timeout

from app.config import settings
from app.documentation_service import DocumentationService
from app.storage import load_project
from dikson_li.agents import AgentCorruptionError, AgentStorageError
from dikson_li.documentation import (
    DocumentationCorruptionError,
    DocumentationGenerateCreate,
    DocumentationSnapshot,
    DocumentationStorageError,
)


router = APIRouter(tags=["documentation"])


def service(project_id: str) -> DocumentationService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return DocumentationService(settings.dikson_data_dir, project_id)


@router.post(
    "/projects/{project_id}/documentation/snapshots",
    response_model=DocumentationSnapshot,
    status_code=201,
)
def documentation_generate(
    project_id: str,
    payload: DocumentationGenerateCreate,
    request: Request,
) -> DocumentationSnapshot:
    try:
        return service(project_id).generate(payload, request.app.openapi())
    except (DocumentationCorruptionError, DocumentationStorageError, AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise HTTPException(status_code=500, detail="Documentation storage is corrupted") from exc


@router.get(
    "/projects/{project_id}/documentation/snapshots",
    response_model=list[DocumentationSnapshot],
)
def documentation_list(project_id: str) -> list[DocumentationSnapshot]:
    try:
        return service(project_id).repository.list()
    except (DocumentationCorruptionError, DocumentationStorageError, Timeout) as exc:
        raise HTTPException(status_code=500, detail="Documentation storage is corrupted") from exc


@router.get(
    "/projects/{project_id}/documentation/snapshots/{snapshot_id}",
    response_model=DocumentationSnapshot,
)
def documentation_get(project_id: str, snapshot_id: str) -> DocumentationSnapshot:
    try:
        return service(project_id).repository.get(snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Documentation snapshot not found") from exc
    except (DocumentationCorruptionError, DocumentationStorageError, Timeout) as exc:
        raise HTTPException(status_code=500, detail="Documentation storage is corrupted") from exc
