from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from app.agent_service import AgentFrameworkService
from app.task_service import TaskQueueService
from dikson_li.agents import AgentRegistry, AgentRunCreate
from dikson_li.planning import (
    JsonlPlanRepository,
    PlanActionCreate,
    PlanCreate,
    PlanDecisionCreate,
    PlanEventType,
    PlanSnapshot,
    PlanStateError,
    PlanStatus,
    PlanStepStatus,
    PlanStepView,
    PlanView,
)
from dikson_li.tasks import TaskCreate, TaskStatus


TASK_TO_STEP_STATUS = {
    TaskStatus.QUEUED: PlanStepStatus.QUEUED,
    TaskStatus.RUNNING: PlanStepStatus.RUNNING,
    TaskStatus.SUCCEEDED: PlanStepStatus.SUCCEEDED,
    TaskStatus.FAILED: PlanStepStatus.FAILED,
    TaskStatus.DEAD_LETTER: PlanStepStatus.DEAD_LETTER,
    TaskStatus.CANCELLED: PlanStepStatus.CANCELLED,
}


class PlanningService:
    """Validates plan policy and dispatches ready DAG steps idempotently."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        self.registry = AgentRegistry()
        self.repository = JsonlPlanRepository(data_dir / "projects" / project_id / "plans")
        self.agents = AgentFrameworkService(data_dir, project_id)
        self.tasks = TaskQueueService(data_dir, project_id)
        self.orchestration_lock = FileLock(
            str(data_dir / "projects" / project_id / "plans" / ".orchestration.lock")
        )

    def create(self, payload: PlanCreate) -> PlanView:
        for step in payload.steps:
            self.registry.authorize_tools(step.agent_id, step.requested_tools)
        return self._view(self.repository.create(self.project_id, payload))

    def list(self, status: PlanStatus | None = None) -> list[PlanView]:
        plans = [self._view(snapshot) for snapshot in self.repository.list()]
        if status is not None:
            plans = [plan for plan in plans if plan.status == status]
        return plans

    def get(self, plan_id: str) -> PlanView:
        return self._view(self.repository.get(plan_id))

    def decide(self, plan_id: str, payload: PlanDecisionCreate) -> PlanView:
        return self._view(self.repository.decide(plan_id, payload))

    def activate(self, plan_id: str, payload: PlanActionCreate) -> PlanView:
        return self._view(self.repository.activate(plan_id, payload))

    def cancel(self, plan_id: str, payload: PlanActionCreate) -> PlanView:
        with self.orchestration_lock:
            current = self.get(plan_id)
            if current.status == PlanStatus.COMPLETED:
                raise PlanStateError("cannot cancel completed plan")
            return self._view(self.repository.cancel(plan_id, payload))

    def dispatch_ready(self, plan_id: str) -> PlanView:
        with self.orchestration_lock:
            snapshot = self.repository.get(plan_id)
            if snapshot.status != PlanStatus.ACTIVE:
                raise PlanStateError(f"cannot dispatch {snapshot.status.value} plan")
            current = self._view(snapshot)
            for step_view in current.steps:
                if step_view.status != PlanStepStatus.READY:
                    continue
                step = step_view.step
                key = f"plan:{snapshot.plan.id}:step:{step.id}"
                run = self.agents.start_run(
                    step.agent_id,
                    AgentRunCreate(
                        objective=step.objective,
                        requested_tools=step.requested_tools,
                        context={
                            "plan_id": snapshot.plan.id,
                            "plan_step_id": step.id,
                            "acceptance_criteria": step.acceptance_criteria,
                        },
                        idempotency_key=key,
                    ),
                )
                task = self.tasks.enqueue(
                    TaskCreate(
                        run_id=run.id,
                        priority=step.priority,
                        max_attempts=step.max_attempts,
                        idempotency_key=key,
                        metadata={"plan_id": snapshot.plan.id, "plan_step_id": step.id},
                    )
                )
                self.repository.record_dispatch(snapshot.plan.id, step.id, run.id, task.task.id)
            return self.get(plan_id)

    def _view(self, snapshot: PlanSnapshot) -> PlanView:
        dispatch_by_step = {
            event.step_id: event
            for event in snapshot.events
            if event.type == PlanEventType.STEP_DISPATCHED and event.step_id
        }
        status_by_step: dict[str, PlanStepStatus] = {}
        for step in snapshot.plan.steps:
            dispatch = dispatch_by_step.get(step.id)
            if dispatch is not None and dispatch.task_id is not None:
                task = self.tasks.get(dispatch.task_id)
                status_by_step[step.id] = TASK_TO_STEP_STATUS[task.status]

        step_views: list[PlanStepView] = []
        for step in snapshot.plan.steps:
            dispatch = dispatch_by_step.get(step.id)
            if dispatch is not None and dispatch.task_id is not None:
                step_status = status_by_step[step.id]
                view = PlanStepView(
                    step=step,
                    status=step_status,
                    run_id=dispatch.run_id,
                    task_id=dispatch.task_id,
                )
            else:
                dependencies_succeeded = all(
                    status_by_step.get(dependency) == PlanStepStatus.SUCCEEDED
                    for dependency in step.depends_on
                )
                step_status = (
                    PlanStepStatus.READY
                    if snapshot.status == PlanStatus.ACTIVE and dependencies_succeeded
                    else PlanStepStatus.BLOCKED
                )
                view = PlanStepView(step=step, status=step_status)
            step_views.append(view)
            status_by_step[step.id] = step_status

        status = snapshot.status
        statuses = {step.status for step in step_views}
        if status == PlanStatus.ACTIVE and statuses == {PlanStepStatus.SUCCEEDED}:
            status = PlanStatus.COMPLETED
        elif status == PlanStatus.ACTIVE and statuses & {
            PlanStepStatus.FAILED,
            PlanStepStatus.DEAD_LETTER,
            PlanStepStatus.CANCELLED,
        }:
            status = PlanStatus.BLOCKED
        return PlanView(
            plan=snapshot.plan,
            status=status,
            steps=step_views,
            events=snapshot.events,
        )
