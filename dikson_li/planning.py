from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dikson_li.agents import AgentId, AgentTool


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanStepStatus(StrEnum):
    BLOCKED = "blocked"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class PlanEventType(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    CANCELLED = "cancelled"
    STEP_DISPATCHED = "step_dispatched"


class PlanStepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=4_000)
    agent_id: AgentId
    requested_tools: set[AgentTool] = Field(default_factory=set)
    depends_on: set[str] = Field(default_factory=set)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)

    @field_validator("title", "objective")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_criteria(cls, value: list[str]) -> list[str]:
        normalized = [criterion.strip() for criterion in value if criterion.strip()]
        if not normalized:
            raise ValueError("acceptance_criteria must not be empty")
        return normalized


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=10_000)
    steps: list[PlanStepCreate] = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "objective")
    @classmethod
    def normalize_plan_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_json(value, "metadata")
        return value

    @model_validator(mode="after")
    def validate_dag(self) -> PlanCreate:
        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("step ids must be unique")
        known = set(step_ids)
        dependencies = {step.id: set(step.depends_on) for step in self.steps}
        for step_id, values in dependencies.items():
            unknown = values - known
            if unknown:
                raise ValueError(
                    f"step {step_id} has unknown dependencies: {', '.join(sorted(unknown))}"
                )
            if step_id in values:
                raise ValueError(f"step {step_id} cannot depend on itself")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependencies must not contain cycles")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


class PlanRecord(PlanCreate):
    id: str
    project_id: str
    created_at: datetime


class PlanDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: PlanStatus
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("outcome")
    @classmethod
    def outcome_must_be_decision(cls, value: PlanStatus) -> PlanStatus:
        if value not in {PlanStatus.APPROVED, PlanStatus.REJECTED}:
            raise ValueError("outcome must be approved or rejected")
        return value

    @field_validator("reviewer", "reason")
    @classmethod
    def normalize_decision_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class PlanActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("actor", "reason")
    @classmethod
    def normalize_action_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class PlanEvent(BaseModel):
    id: str
    project_id: str
    plan_id: str
    type: PlanEventType
    actor: str
    reason: str
    created_at: datetime
    step_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None


class PlanSnapshot(BaseModel):
    plan: PlanRecord
    status: PlanStatus
    events: list[PlanEvent]


class PlanStepView(BaseModel):
    step: PlanStepCreate
    status: PlanStepStatus
    run_id: str | None = None
    task_id: str | None = None


class PlanView(BaseModel):
    plan: PlanRecord
    status: PlanStatus
    steps: list[PlanStepView]
    events: list[PlanEvent]


class PlanStorageError(RuntimeError):
    pass


class PlanCorruptionError(PlanStorageError):
    pass


class PlanStateError(ValueError):
    pass


class JsonlPlanRepository:
    """Append-only plans and lifecycle events."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.plans_path = self.root / "plans.jsonl"
        self.events_path = self.root / "events.jsonl"
        self.lock_timeout = lock_timeout

    def create(self, project_id: str, payload: PlanCreate) -> PlanSnapshot:
        plan = PlanRecord(
            id=uuid4().hex,
            project_id=project_id,
            created_at=datetime.now(timezone.utc),
            **payload.model_dump(),
        )
        with self._lock():
            self._append(self.plans_path, plan.model_dump_json())
        return PlanSnapshot(plan=plan, status=PlanStatus.DRAFT, events=[])

    def list(self) -> list[PlanSnapshot]:
        with self._lock():
            plans = self._read_rows(self.plans_path, PlanRecord)
            events = self._read_rows(self.events_path, PlanEvent)
        by_plan: dict[str, list[PlanEvent]] = {}
        for event in events:
            by_plan.setdefault(event.plan_id, []).append(event)
        return [self._snapshot(plan, by_plan.get(plan.id, [])) for plan in plans]

    def get(self, plan_id: str) -> PlanSnapshot:
        with self._lock():
            plan = self._find(self._read_rows(self.plans_path, PlanRecord), plan_id)
            events = [
                event
                for event in self._read_rows(self.events_path, PlanEvent)
                if event.plan_id == plan_id
            ]
        return self._snapshot(plan, events)

    def decide(self, plan_id: str, payload: PlanDecisionCreate) -> PlanSnapshot:
        with self._lock():
            plan, events, snapshot = self._locked_snapshot(plan_id)
            if snapshot.status != PlanStatus.DRAFT:
                raise PlanStateError(f"cannot decide {snapshot.status.value} plan")
            event = self._event(
                plan,
                PlanEventType.APPROVED
                if payload.outcome == PlanStatus.APPROVED
                else PlanEventType.REJECTED,
                actor=payload.reviewer,
                reason=payload.reason,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(plan, [*events, event])

    def activate(self, plan_id: str, payload: PlanActionCreate) -> PlanSnapshot:
        with self._lock():
            plan, events, snapshot = self._locked_snapshot(plan_id)
            if snapshot.status != PlanStatus.APPROVED:
                raise PlanStateError(f"cannot activate {snapshot.status.value} plan")
            event = self._event(
                plan,
                PlanEventType.ACTIVATED,
                actor=payload.actor,
                reason=payload.reason,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(plan, [*events, event])

    def cancel(self, plan_id: str, payload: PlanActionCreate) -> PlanSnapshot:
        with self._lock():
            plan, events, snapshot = self._locked_snapshot(plan_id)
            if snapshot.status in {
                PlanStatus.REJECTED,
                PlanStatus.CANCELLED,
                PlanStatus.COMPLETED,
            }:
                raise PlanStateError(f"cannot cancel {snapshot.status.value} plan")
            event = self._event(
                plan,
                PlanEventType.CANCELLED,
                actor=payload.actor,
                reason=payload.reason,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(plan, [*events, event])

    def record_dispatch(
        self,
        plan_id: str,
        step_id: str,
        run_id: str,
        task_id: str,
    ) -> PlanSnapshot:
        with self._lock():
            plan, events, snapshot = self._locked_snapshot(plan_id)
            if snapshot.status != PlanStatus.ACTIVE:
                raise PlanStateError(f"cannot dispatch {snapshot.status.value} plan")
            if step_id not in {step.id for step in plan.steps}:
                raise KeyError(step_id)
            if any(
                event.type == PlanEventType.STEP_DISPATCHED and event.step_id == step_id
                for event in events
            ):
                return snapshot
            event = self._event(
                plan,
                PlanEventType.STEP_DISPATCHED,
                actor="planning-system",
                reason="dependencies satisfied",
                step_id=step_id,
                run_id=run_id,
                task_id=task_id,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(plan, [*events, event])

    def _locked_snapshot(self, plan_id: str) -> tuple[PlanRecord, list[PlanEvent], PlanSnapshot]:
        plan = self._find(self._read_rows(self.plans_path, PlanRecord), plan_id)
        events = [
            event
            for event in self._read_rows(self.events_path, PlanEvent)
            if event.plan_id == plan_id
        ]
        return plan, events, self._snapshot(plan, events)

    @staticmethod
    def _snapshot(plan: PlanRecord, events: list[PlanEvent]) -> PlanSnapshot:
        status = PlanStatus.DRAFT
        for event in events:
            if event.type == PlanEventType.APPROVED:
                status = PlanStatus.APPROVED
            elif event.type == PlanEventType.REJECTED:
                status = PlanStatus.REJECTED
            elif event.type == PlanEventType.ACTIVATED:
                status = PlanStatus.ACTIVE
            elif event.type == PlanEventType.CANCELLED:
                status = PlanStatus.CANCELLED
        return PlanSnapshot(plan=plan, status=status, events=events)

    @staticmethod
    def _event(
        plan: PlanRecord,
        event_type: PlanEventType,
        *,
        actor: str,
        reason: str,
        step_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> PlanEvent:
        return PlanEvent(
            id=uuid4().hex,
            project_id=plan.project_id,
            plan_id=plan.id,
            type=event_type,
            actor=actor,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            step_id=step_id,
            run_id=run_id,
            task_id=task_id,
        )

    def _read_rows(self, path: Path, model):
        if not path.exists():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise PlanStorageError(f"Could not read {path.name}") from exc
        records = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                records.append(model.model_validate_json(row))
            except ValueError as exc:
                raise PlanCorruptionError(f"Invalid {path.name} row at line {line_number}") from exc
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
            raise PlanStorageError(f"Could not append {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".plans.lock"), timeout=self.lock_timeout)


def _ensure_json(value: Any, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serializable") from exc
