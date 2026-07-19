from fastapi import APIRouter, HTTPException
from filelock import Timeout

from app.config import settings
from app.planning_service import PlanningService
from app.storage import load_project
from dikson_li.agents import (
    AgentCorruptionError,
    AgentPolicyError,
    AgentStorageError,
)
from dikson_li.planning import (
    PlanActionCreate,
    PlanCorruptionError,
    PlanCreate,
    PlanDecisionCreate,
    PlanStateError,
    PlanStatus,
    PlanStorageError,
    PlanView,
)
from dikson_li.tasks import TaskCorruptionError, TaskStorageError


router = APIRouter(prefix="/projects/{project_id}/plans", tags=["plans"])


def service(project_id: str) -> PlanningService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    return PlanningService(settings.dikson_data_dir, project_id)


def plan_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальное хранилище планов повреждено")


STORAGE_ERRORS = (
    PlanCorruptionError,
    PlanStorageError,
    AgentCorruptionError,
    AgentStorageError,
    TaskCorruptionError,
    TaskStorageError,
    Timeout,
)


@router.post("", response_model=PlanView, status_code=201)
def plan_create(project_id: str, payload: PlanCreate) -> PlanView:
    try:
        return service(project_id).create(payload)
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.get("", response_model=list[PlanView])
def plan_list(project_id: str, status: PlanStatus | None = None) -> list[PlanView]:
    try:
        return service(project_id).list(status)
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.get("/{plan_id}", response_model=PlanView)
def plan_get(project_id: str, plan_id: str) -> PlanView:
    try:
        return service(project_id).get(plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="План не найден") from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.post("/{plan_id}/decision", response_model=PlanView)
def plan_decide(project_id: str, plan_id: str, payload: PlanDecisionCreate) -> PlanView:
    try:
        return service(project_id).decide(plan_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="План не найден") from exc
    except PlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.post("/{plan_id}/activate", response_model=PlanView)
def plan_activate(project_id: str, plan_id: str, payload: PlanActionCreate) -> PlanView:
    try:
        return service(project_id).activate(plan_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="План не найден") from exc
    except PlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.post("/{plan_id}/dispatch", response_model=PlanView)
def plan_dispatch(project_id: str, plan_id: str) -> PlanView:
    try:
        return service(project_id).dispatch_ready(plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="План или связанная задача не найдены") from exc
    except PlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc


@router.post("/{plan_id}/cancel", response_model=PlanView)
def plan_cancel(project_id: str, plan_id: str, payload: PlanActionCreate) -> PlanView:
    try:
        return service(project_id).cancel(plan_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="План не найден") from exc
    except PlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except STORAGE_ERRORS as exc:
        raise plan_storage_error() from exc
