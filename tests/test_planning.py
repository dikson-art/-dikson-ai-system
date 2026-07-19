from pathlib import Path

import pytest
from pydantic import ValidationError

from app.planning_service import PlanningService
from dikson_li.agents import AgentPolicyError, AgentRunCreate
from dikson_li.planning import (
    JsonlPlanRepository,
    PlanActionCreate,
    PlanCorruptionError,
    PlanCreate,
    PlanDecisionCreate,
    PlanStateError,
)
from dikson_li.tasks import TaskClaimCreate, TaskCompleteCreate, TaskCreate


def step(
    step_id: str,
    agent_id: str,
    tools: list[str],
    *,
    depends_on: list[str] | None = None,
) -> dict:
    return {
        "id": step_id,
        "title": step_id.title(),
        "objective": f"Execute {step_id}",
        "agent_id": agent_id,
        "requested_tools": tools,
        "depends_on": depends_on or [],
        "acceptance_criteria": [f"{step_id} output is reviewable"],
    }


def test_plan_dag_validation_and_agent_tool_policy(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        PlanCreate(
            title="Unknown",
            objective="Invalid dependency",
            steps=[step("one", "research", [], depends_on=["missing"])],
        )
    with pytest.raises(ValidationError, match="cycles"):
        PlanCreate(
            title="Cycle",
            objective="Invalid cycle",
            steps=[
                step("one", "research", [], depends_on=["two"]),
                step("two", "review", [], depends_on=["one"]),
            ],
        )

    service = PlanningService(tmp_path, "project")
    with pytest.raises(AgentPolicyError, match="wiki_propose"):
        service.create(
            PlanCreate(
                title="Forbidden",
                objective="Use a forbidden tool",
                steps=[step("research", "research", ["wiki_propose"])],
            )
        )


def test_repository_lifecycle_dispatch_audit_and_corruption(tmp_path: Path) -> None:
    repository = JsonlPlanRepository(tmp_path)
    created = repository.create(
        "project",
        PlanCreate(
            title="Lifecycle",
            objective="Verify lifecycle",
            steps=[step("one", "planning", ["plan_propose"])],
        ),
    )
    with pytest.raises(PlanStateError):
        repository.activate(created.plan.id, PlanActionCreate(actor="lead", reason="too early"))
    approved = repository.decide(
        created.plan.id,
        PlanDecisionCreate(outcome="approved", reviewer="lead", reason="valid DAG"),
    )
    assert approved.status == "approved"
    active = repository.activate(created.plan.id, PlanActionCreate(actor="lead", reason="start"))
    first = repository.record_dispatch(active.plan.id, "one", "run-1", "task-1")
    repeated = repository.record_dispatch(active.plan.id, "one", "run-2", "task-2")
    dispatches = [event for event in repeated.events if event.type == "step_dispatched"]
    assert len(dispatches) == 1
    assert dispatches[0].run_id == "run-1"
    assert first.status == "active"

    repository.plans_path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(PlanCorruptionError, match="line 1"):
        repository.list()


def test_dispatches_ready_steps_idempotently_and_completes_plan(tmp_path: Path) -> None:
    service = PlanningService(tmp_path, "project")
    created = service.create(
        PlanCreate(
            title="Research and review",
            objective="Produce verified evidence",
            steps=[
                step("review", "review", ["review_propose"], depends_on=["research"]),
                step("research", "research", ["semantic_search"]),
            ],
        )
    )
    service.decide(
        created.plan.id,
        PlanDecisionCreate(outcome="approved", reviewer="architect", reason="safe"),
    )
    service.activate(created.plan.id, PlanActionCreate(actor="architect", reason="execute"))
    first_wave = service.dispatch_ready(created.plan.id)
    statuses = {item.step.id: item.status for item in first_wave.steps}
    assert statuses == {"review": "blocked", "research": "queued"}
    assert len(service.agents.runs()) == 1
    assert len(service.tasks.list()) == 1
    repeated = service.dispatch_ready(created.plan.id)
    assert len(service.agents.runs()) == 1
    assert len(service.tasks.list()) == 1
    assert repeated.status == "active"

    research_task = service.tasks.claim(
        TaskClaimCreate(worker_id="research-worker", agent_id="research")
    )
    service.tasks.complete(
        research_task.task.id,
        TaskCompleteCreate(
            lease_token=research_task.lease_token,
            result={"proposal_id": "research-proposal"},
        ),
    )
    second_wave = service.dispatch_ready(created.plan.id)
    statuses = {item.step.id: item.status for item in second_wave.steps}
    assert statuses == {"review": "queued", "research": "succeeded"}
    assert len(service.agents.runs()) == 2
    assert len(service.tasks.list()) == 2

    review_task = service.tasks.claim(TaskClaimCreate(worker_id="review-worker", agent_id="review"))
    service.tasks.complete(
        review_task.task.id,
        TaskCompleteCreate(
            lease_token=review_task.lease_token,
            result={"proposal_id": "review-proposal"},
        ),
    )
    completed = service.get(created.plan.id)
    assert completed.status == "completed"
    assert {item.status for item in completed.steps} == {"succeeded"}
    with pytest.raises(PlanStateError, match="completed"):
        service.cancel(
            created.plan.id,
            PlanActionCreate(actor="architect", reason="too late"),
        )


def test_dispatch_recovers_run_and_task_created_before_plan_event(tmp_path: Path) -> None:
    service = PlanningService(tmp_path, "project")
    created = service.create(
        PlanCreate(
            title="Recover dispatch",
            objective="Recover a partially recorded dispatch",
            steps=[step("research", "research", ["semantic_search"])],
        )
    )
    service.decide(
        created.plan.id,
        PlanDecisionCreate(outcome="approved", reviewer="architect", reason="safe"),
    )
    service.activate(created.plan.id, PlanActionCreate(actor="architect", reason="execute"))
    key = f"plan:{created.plan.id}:step:research"
    run = service.agents.start_run(
        "research",
        AgentRunCreate(
            objective="Execute research",
            requested_tools={"semantic_search"},
            idempotency_key=key,
        ),
    )
    task = service.tasks.enqueue(TaskCreate(run_id=run.id, idempotency_key=key))

    recovered = service.dispatch_ready(created.plan.id)

    assert len(service.agents.runs()) == 1
    assert len(service.tasks.list()) == 1
    assert recovered.steps[0].run_id == run.id
    assert recovered.steps[0].task_id == task.task.id
