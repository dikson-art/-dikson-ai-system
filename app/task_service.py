from __future__ import annotations

from pathlib import Path

from app.agent_service import AgentFrameworkService
from dikson_li.agents import AgentRun
from dikson_li.tasks import (
    JsonlTaskQueue,
    TaskCancelCreate,
    TaskClaimCreate,
    TaskCompleteCreate,
    TaskCreate,
    TaskEvent,
    TaskFailCreate,
    TaskLeaseCreate,
    TaskStatus,
    TaskView,
)


class TaskQueueService:
    """Binds durable queue tasks to policy-validated Agent Framework runs."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        self.agents = AgentFrameworkService(data_dir, project_id)
        self.queue = JsonlTaskQueue(data_dir / "projects" / project_id / "tasks")

    def enqueue(self, payload: TaskCreate) -> TaskView:
        run = self._run(payload.run_id)
        return self.queue.enqueue(self.project_id, run.agent_id, payload)

    def list(self, *, status: TaskStatus | None = None) -> list[TaskView]:
        return self.queue.list(status=status)

    def get(self, task_id: str) -> TaskView:
        return self.queue.get(task_id)

    def events(self, task_id: str) -> list[TaskEvent]:
        return self.queue.events(task_id)

    def claim(self, payload: TaskClaimCreate) -> TaskView | None:
        return self.queue.claim(payload)

    def heartbeat(self, task_id: str, payload: TaskLeaseCreate) -> TaskView:
        return self.queue.heartbeat(task_id, payload)

    def complete(self, task_id: str, payload: TaskCompleteCreate) -> TaskView:
        return self.queue.complete(task_id, payload)

    def fail(self, task_id: str, payload: TaskFailCreate) -> TaskView:
        return self.queue.fail(task_id, payload)

    def cancel(self, task_id: str, payload: TaskCancelCreate) -> TaskView:
        return self.queue.cancel(task_id, payload)

    def _run(self, run_id: str) -> AgentRun:
        for run in self.agents.runs():
            if run.id == run_id:
                return run
        raise KeyError(run_id)
