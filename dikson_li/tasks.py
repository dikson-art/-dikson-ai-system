from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dikson_li.agents import AgentId


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class TaskEventType(StrEnum):
    CLAIMED = "claimed"
    HEARTBEAT = "heartbeat"
    COMPLETED = "completed"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    available_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id", "idempotency_key")
    @classmethod
    def normalize_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier must not be blank")
        return normalized

    @field_validator("available_at")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("available_at must include a timezone")
        return value

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_json(value, "metadata")
        return value


class QueueTask(TaskCreate):
    id: str
    project_id: str
    agent_id: AgentId
    created_at: datetime


class TaskClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=5, le=3_600)
    agent_id: AgentId | None = None
    task_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("worker_id", "task_id")
    @classmethod
    def normalize_worker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class TaskLeaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=5, le=3_600)


class TaskCompleteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=200)
    result: dict[str, Any] = Field(default_factory=dict)

    @field_validator("result")
    @classmethod
    def result_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_json(value, "result")
        return value


class TaskFailCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=200)
    error: str = Field(min_length=1, max_length=10_000)
    retryable: bool = True
    retry_delay_seconds: int = Field(default=0, ge=0, le=86_400)

    @field_validator("error")
    @classmethod
    def normalize_error(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("error must not be blank")
        return normalized


class TaskCancelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    lease_token: str | None = Field(default=None, max_length=200)

    @field_validator("actor", "reason")
    @classmethod
    def normalize_cancel_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class TaskEvent(BaseModel):
    id: str
    project_id: str
    task_id: str
    type: TaskEventType
    actor: str
    created_at: datetime
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    available_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class TaskView(BaseModel):
    task: QueueTask
    status: TaskStatus
    attempts: int = 0
    available_at: datetime
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class TaskPublicView(BaseModel):
    task: QueueTask
    status: TaskStatus
    attempts: int
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class TaskClaimView(TaskPublicView):
    lease_token: str


class TaskPublicEvent(BaseModel):
    id: str
    project_id: str
    task_id: str
    type: TaskEventType
    actor: str
    created_at: datetime
    lease_expires_at: datetime | None = None
    available_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class TaskStorageError(RuntimeError):
    pass


class TaskCorruptionError(TaskStorageError):
    pass


class TaskStateError(ValueError):
    pass


class TaskLeaseError(PermissionError):
    pass


class JsonlTaskQueue:
    """Durable event-sourced queue with atomic local worker leases."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks_path = self.root / "tasks.jsonl"
        self.events_path = self.root / "events.jsonl"
        self.lock_timeout = lock_timeout

    def enqueue(
        self,
        project_id: str,
        agent_id: AgentId,
        payload: TaskCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView:
        timestamp = _utc(now)
        with self._lock():
            tasks = self._read_rows(self.tasks_path, QueueTask)
            if payload.idempotency_key:
                for task in tasks:
                    if task.idempotency_key == payload.idempotency_key:
                        return self._view(task, self._events_for(task.id))
            task = QueueTask(
                id=uuid4().hex,
                project_id=project_id,
                agent_id=agent_id,
                created_at=timestamp,
                **payload.model_dump(),
            )
            self._append(self.tasks_path, task.model_dump_json())
            return self._view(task, [])

    def list(self, *, status: TaskStatus | None = None) -> list[TaskView]:
        with self._lock():
            tasks = self._read_rows(self.tasks_path, QueueTask)
            events = self._read_rows(self.events_path, TaskEvent)
        by_task = self._group_events(events)
        views = [self._view(task, by_task.get(task.id, [])) for task in tasks]
        if status is not None:
            views = [view for view in views if view.status == status]
        return views

    def get(self, task_id: str) -> TaskView:
        with self._lock():
            task = self._find(self._read_rows(self.tasks_path, QueueTask), task_id)
            events = self._events_for(task_id)
        return self._view(task, events)

    def events(self, task_id: str) -> list[TaskEvent]:
        with self._lock():
            self._find(self._read_rows(self.tasks_path, QueueTask), task_id)
            return self._events_for(task_id)

    def claim(
        self,
        payload: TaskClaimCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView | None:
        timestamp = _utc(now)
        with self._lock():
            tasks = self._read_rows(self.tasks_path, QueueTask)
            events = self._read_rows(self.events_path, TaskEvent)
            by_task = self._group_events(events)
            for task in tasks:
                view = self._view(task, by_task.get(task.id, []))
                if (
                    view.status == TaskStatus.RUNNING
                    and view.lease_expires_at is not None
                    and view.lease_expires_at <= timestamp
                ):
                    event = self._expired_event(task, view, timestamp)
                    self._append(self.events_path, event.model_dump_json())
                    by_task.setdefault(task.id, []).append(event)
            eligible = []
            for task in tasks:
                view = self._view(task, by_task.get(task.id, []))
                if payload.task_id is not None and task.id != payload.task_id:
                    continue
                if payload.agent_id is not None and task.agent_id != payload.agent_id:
                    continue
                if view.status == TaskStatus.QUEUED and view.available_at <= timestamp:
                    eligible.append(view)
            if not eligible:
                return None
            selected = sorted(
                eligible,
                key=lambda view: (
                    -view.task.priority,
                    view.available_at,
                    view.task.created_at,
                    view.task.id,
                ),
            )[0]
            token = uuid4().hex
            event = self._event(
                selected.task,
                TaskEventType.CLAIMED,
                actor=payload.worker_id,
                timestamp=timestamp,
                lease_token=token,
                lease_expires_at=timestamp + timedelta(seconds=payload.lease_seconds),
            )
            self._append(self.events_path, event.model_dump_json())
            return self._view(selected.task, [*by_task.get(selected.task.id, []), event])

    def heartbeat(
        self,
        task_id: str,
        payload: TaskLeaseCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView:
        timestamp = _utc(now)
        with self._lock():
            task, events, view = self._locked_view(task_id)
            self._authorize_lease(view, payload.lease_token, timestamp)
            event = self._event(
                task,
                TaskEventType.HEARTBEAT,
                actor=view.lease_owner or "worker",
                timestamp=timestamp,
                lease_token=payload.lease_token,
                lease_expires_at=timestamp + timedelta(seconds=payload.lease_seconds),
            )
            self._append(self.events_path, event.model_dump_json())
        return self._view(task, [*events, event])

    def complete(
        self,
        task_id: str,
        payload: TaskCompleteCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView:
        timestamp = _utc(now)
        with self._lock():
            task, events, view = self._locked_view(task_id)
            self._authorize_lease(view, payload.lease_token, timestamp)
            event = self._event(
                task,
                TaskEventType.COMPLETED,
                actor=view.lease_owner or "worker",
                timestamp=timestamp,
                result=payload.result,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._view(task, [*events, event])

    def fail(
        self,
        task_id: str,
        payload: TaskFailCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView:
        timestamp = _utc(now)
        with self._lock():
            task, events, view = self._locked_view(task_id)
            self._authorize_lease(view, payload.lease_token, timestamp)
            if not payload.retryable:
                event_type = TaskEventType.FAILED
            elif view.attempts >= task.max_attempts:
                event_type = TaskEventType.DEAD_LETTERED
            else:
                event_type = TaskEventType.RETRY_SCHEDULED
            event = self._event(
                task,
                event_type,
                actor=view.lease_owner or "worker",
                timestamp=timestamp,
                error=payload.error,
                available_at=(
                    timestamp + timedelta(seconds=payload.retry_delay_seconds)
                    if event_type == TaskEventType.RETRY_SCHEDULED
                    else None
                ),
            )
            self._append(self.events_path, event.model_dump_json())
        return self._view(task, [*events, event])

    def cancel(
        self,
        task_id: str,
        payload: TaskCancelCreate,
        *,
        now: datetime | None = None,
    ) -> TaskView:
        timestamp = _utc(now)
        with self._lock():
            task, events, view = self._locked_view(task_id)
            if view.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.DEAD_LETTER,
                TaskStatus.CANCELLED,
            }:
                raise TaskStateError(f"cannot cancel {view.status.value} task")
            if view.status == TaskStatus.RUNNING:
                self._authorize_lease(view, payload.lease_token or "", timestamp)
            event = self._event(
                task,
                TaskEventType.CANCELLED,
                actor=payload.actor,
                timestamp=timestamp,
                error=payload.reason,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._view(task, [*events, event])

    def _locked_view(self, task_id: str) -> tuple[QueueTask, list[TaskEvent], TaskView]:
        task = self._find(self._read_rows(self.tasks_path, QueueTask), task_id)
        events = self._events_for(task_id)
        return task, events, self._view(task, events)

    def _events_for(self, task_id: str) -> list[TaskEvent]:
        return [
            event
            for event in self._read_rows(self.events_path, TaskEvent)
            if event.task_id == task_id
        ]

    @staticmethod
    def _group_events(events: list[TaskEvent]) -> dict[str, list[TaskEvent]]:
        grouped: dict[str, list[TaskEvent]] = {}
        for event in events:
            grouped.setdefault(event.task_id, []).append(event)
        return grouped

    @staticmethod
    def _view(task: QueueTask, events: list[TaskEvent]) -> TaskView:
        view = TaskView(
            task=task,
            status=TaskStatus.QUEUED,
            available_at=task.available_at or task.created_at,
        )
        for event in events:
            if event.type == TaskEventType.CLAIMED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "attempts": view.attempts + 1,
                        "lease_owner": event.actor,
                        "lease_token": event.lease_token,
                        "lease_expires_at": event.lease_expires_at,
                    }
                )
            elif event.type == TaskEventType.HEARTBEAT:
                view = view.model_copy(update={"lease_expires_at": event.lease_expires_at})
            elif event.type == TaskEventType.COMPLETED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.SUCCEEDED,
                        "result": event.result,
                        **_clear_lease(),
                    }
                )
            elif event.type == TaskEventType.RETRY_SCHEDULED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.QUEUED,
                        "available_at": event.available_at or event.created_at,
                        "last_error": event.error,
                        **_clear_lease(),
                    }
                )
            elif event.type == TaskEventType.FAILED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.FAILED,
                        "last_error": event.error,
                        **_clear_lease(),
                    }
                )
            elif event.type == TaskEventType.DEAD_LETTERED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.DEAD_LETTER,
                        "last_error": event.error,
                        **_clear_lease(),
                    }
                )
            elif event.type == TaskEventType.CANCELLED:
                view = view.model_copy(
                    update={
                        "status": TaskStatus.CANCELLED,
                        "last_error": event.error,
                        **_clear_lease(),
                    }
                )
        return view

    def _expired_event(self, task: QueueTask, view: TaskView, timestamp: datetime) -> TaskEvent:
        exhausted = view.attempts >= task.max_attempts
        return self._event(
            task,
            TaskEventType.DEAD_LETTERED if exhausted else TaskEventType.RETRY_SCHEDULED,
            actor="queue-reaper",
            timestamp=timestamp,
            error="worker lease expired",
            available_at=None if exhausted else timestamp,
        )

    @staticmethod
    def _authorize_lease(view: TaskView, token: str, timestamp: datetime) -> None:
        if view.status != TaskStatus.RUNNING:
            raise TaskStateError(f"task is {view.status.value}, not running")
        if view.lease_token != token:
            raise TaskLeaseError("lease token does not own task")
        if view.lease_expires_at is None or view.lease_expires_at <= timestamp:
            raise TaskLeaseError("worker lease expired")

    @staticmethod
    def _event(
        task: QueueTask,
        event_type: TaskEventType,
        *,
        actor: str,
        timestamp: datetime,
        lease_token: str | None = None,
        lease_expires_at: datetime | None = None,
        available_at: datetime | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> TaskEvent:
        return TaskEvent(
            id=uuid4().hex,
            project_id=task.project_id,
            task_id=task.id,
            type=event_type,
            actor=actor,
            created_at=timestamp,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            available_at=available_at,
            error=error,
            result=result or {},
        )

    def _read_rows(self, path: Path, model):
        if not path.exists():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise TaskStorageError(f"Could not read {path.name}") from exc
        records = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                records.append(model.model_validate_json(row))
            except ValueError as exc:
                raise TaskCorruptionError(f"Invalid {path.name} row at line {line_number}") from exc
        return records

    @staticmethod
    def _find(records, record_id: str):
        for record in records:
            if record.id == record_id:
                return record
        raise KeyError(record_id)

    def _append(self, path: Path, row: str) -> None:
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(row + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise TaskStorageError(f"Could not append {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".tasks.lock"), timeout=self.lock_timeout)


def _utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return timestamp.astimezone(timezone.utc)


def _clear_lease() -> dict[str, None]:
    return {"lease_owner": None, "lease_token": None, "lease_expires_at": None}


def _ensure_json(value: Any, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serializable") from exc
