from fastapi import APIRouter, HTTPException
from filelock import Timeout

from app.config import settings
from app.storage import load_project
from app.task_service import TaskQueueService
from dikson_li.agents import AgentCorruptionError, AgentStorageError
from dikson_li.tasks import (
    TaskCancelCreate,
    TaskClaimView,
    TaskClaimCreate,
    TaskCompleteCreate,
    TaskCorruptionError,
    TaskCreate,
    TaskEvent,
    TaskFailCreate,
    TaskLeaseCreate,
    TaskLeaseError,
    TaskPublicEvent,
    TaskPublicView,
    TaskStateError,
    TaskStatus,
    TaskStorageError,
    TaskView,
)


router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


def service(project_id: str) -> TaskQueueService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    return TaskQueueService(settings.dikson_data_dir, project_id)


def queue_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальная очередь задач повреждена")


@router.post("", response_model=TaskPublicView, status_code=201)
def task_enqueue(project_id: str, payload: TaskCreate) -> TaskView:
    try:
        return service(project_id).enqueue(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Запуск агента не найден") from exc
    except (
        TaskCorruptionError,
        TaskStorageError,
        AgentCorruptionError,
        AgentStorageError,
        Timeout,
    ) as exc:
        raise queue_storage_error() from exc


@router.get("", response_model=list[TaskPublicView])
def task_list(project_id: str, status: TaskStatus | None = None) -> list[TaskView]:
    try:
        return service(project_id).list(status=status)
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.post("/claim", response_model=TaskClaimView | None)
def task_claim(project_id: str, payload: TaskClaimCreate) -> TaskView | None:
    try:
        return service(project_id).claim(payload)
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.get("/{task_id}", response_model=TaskPublicView)
def task_get(project_id: str, task_id: str) -> TaskView:
    try:
        return service(project_id).get(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.get("/{task_id}/events", response_model=list[TaskPublicEvent])
def task_events(project_id: str, task_id: str) -> list[TaskEvent]:
    try:
        return service(project_id).events(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.post("/{task_id}/heartbeat", response_model=TaskPublicView)
def task_heartbeat(project_id: str, task_id: str, payload: TaskLeaseCreate) -> TaskView:
    try:
        return service(project_id).heartbeat(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except TaskLeaseError as exc:
        raise HTTPException(status_code=409, detail="Lease задачи недействителен") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.post("/{task_id}/complete", response_model=TaskPublicView)
def task_complete(project_id: str, task_id: str, payload: TaskCompleteCreate) -> TaskView:
    try:
        return service(project_id).complete(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except TaskLeaseError as exc:
        raise HTTPException(status_code=409, detail="Lease задачи недействителен") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.post("/{task_id}/fail", response_model=TaskPublicView)
def task_fail(project_id: str, task_id: str, payload: TaskFailCreate) -> TaskView:
    try:
        return service(project_id).fail(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except TaskLeaseError as exc:
        raise HTTPException(status_code=409, detail="Lease задачи недействителен") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc


@router.post("/{task_id}/cancel", response_model=TaskPublicView)
def task_cancel(project_id: str, task_id: str, payload: TaskCancelCreate) -> TaskView:
    try:
        return service(project_id).cancel(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
    except TaskLeaseError as exc:
        raise HTTPException(status_code=409, detail="Lease задачи недействителен") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TaskCorruptionError, TaskStorageError, Timeout) as exc:
        raise queue_storage_error() from exc
