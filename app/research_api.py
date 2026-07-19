from fastapi import APIRouter, HTTPException
from filelock import Timeout
from pydantic import BaseModel, Field

from app.config import settings
from app.research_service import (
    ResearchEngineService,
    ResearchProviderError,
    ResearchStudyView,
)
from app.search_service import SearchCorruptionError, SearchProviderError, SearchStorageError
from app.storage import load_project
from dikson_li.agents import AgentCorruptionError, AgentPolicyError, AgentStorageError
from dikson_li.graph import GraphCorruptionError, GraphStorageError
from dikson_li.memory import MemoryCorruptionError, MemoryStorageError
from dikson_li.planning import (
    PlanActionCreate,
    PlanCorruptionError,
    PlanDecisionCreate,
    PlanStateError,
    PlanStorageError,
)
from dikson_li.research import (
    ResearchCorruptionError,
    ResearchStateError,
    ResearchStorageError,
    ResearchStudyCreate,
)
from dikson_li.tasks import TaskCorruptionError, TaskStorageError
from dikson_li.wiki import WikiCorruptionError, WikiStorageError


router = APIRouter(prefix="/projects/{project_id}/research", tags=["research"])


class QuickResearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=10_000)


STORAGE_ERRORS = (
    ResearchCorruptionError,
    ResearchStorageError,
    PlanCorruptionError,
    PlanStorageError,
    AgentCorruptionError,
    AgentStorageError,
    TaskCorruptionError,
    TaskStorageError,
    SearchCorruptionError,
    SearchStorageError,
    MemoryCorruptionError,
    MemoryStorageError,
    WikiCorruptionError,
    WikiStorageError,
    GraphCorruptionError,
    GraphStorageError,
    Timeout,
)


def service(project_id: str) -> ResearchEngineService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    return ResearchEngineService(settings.dikson_data_dir, project_id)


def storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальное хранилище исследований повреждено")


@router.post("")
def research_quick(project_id: str, payload: QuickResearchRequest) -> dict:
    try:
        return service(project_id).quick_answer(payload.question)
    except (ResearchProviderError, SearchProviderError) as exc:
        raise HTTPException(status_code=503, detail="Провайдер исследования недоступен") from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.post("/studies", response_model=ResearchStudyView, status_code=201)
def research_study_create(project_id: str, payload: ResearchStudyCreate) -> ResearchStudyView:
    try:
        return service(project_id).create(payload)
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.get("/studies", response_model=list[ResearchStudyView])
def research_study_list(project_id: str) -> list[ResearchStudyView]:
    try:
        return service(project_id).list()
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.get("/studies/{study_id}", response_model=ResearchStudyView)
def research_study_get(project_id: str, study_id: str) -> ResearchStudyView:
    try:
        return service(project_id).get(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Исследование не найдено") from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.post("/studies/{study_id}/decision", response_model=ResearchStudyView)
def research_study_decide(
    project_id: str,
    study_id: str,
    payload: PlanDecisionCreate,
) -> ResearchStudyView:
    try:
        return service(project_id).decide(study_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Исследование не найдено") from exc
    except (PlanStateError, ResearchStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.post("/studies/{study_id}/activate", response_model=ResearchStudyView)
def research_study_activate(
    project_id: str,
    study_id: str,
    payload: PlanActionCreate,
) -> ResearchStudyView:
    try:
        return service(project_id).activate(study_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Исследование не найдено") from exc
    except (PlanStateError, ResearchStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc


@router.post("/studies/{study_id}/advance", response_model=ResearchStudyView)
def research_study_advance(project_id: str, study_id: str) -> ResearchStudyView:
    try:
        return service(project_id).advance(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Исследование не найдено") from exc
    except (PlanStateError, ResearchStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ResearchProviderError, SearchProviderError) as exc:
        raise HTTPException(status_code=503, detail="Провайдер исследования недоступен") from exc
    except STORAGE_ERRORS as exc:
        raise storage_error() from exc
