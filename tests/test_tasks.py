from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dikson_li.agents import AgentId
from dikson_li.tasks import (
    JsonlTaskQueue,
    TaskCancelCreate,
    TaskClaimCreate,
    TaskCompleteCreate,
    TaskCorruptionError,
    TaskCreate,
    TaskFailCreate,
    TaskLeaseCreate,
    TaskLeaseError,
    TaskStateError,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def enqueue(
    queue: JsonlTaskQueue,
    run_id: str,
    *,
    priority: int = 0,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
):
    return queue.enqueue(
        "project",
        AgentId.RESEARCH,
        TaskCreate(
            run_id=run_id,
            priority=priority,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        ),
        now=NOW,
    )


def test_priority_idempotency_lease_and_completion(tmp_path: Path) -> None:
    queue = JsonlTaskQueue(tmp_path)
    low = enqueue(queue, "low", priority=1, idempotency_key="same")
    repeated = enqueue(queue, "different", priority=99, idempotency_key="same")
    high = enqueue(queue, "high", priority=10)

    assert repeated.task.id == low.task.id
    claimed = queue.claim(TaskClaimCreate(worker_id="worker-1"), now=NOW)
    assert claimed is not None
    assert claimed.task.id == high.task.id
    assert claimed.status == "running"
    assert claimed.attempts == 1
    with pytest.raises(TaskLeaseError):
        queue.complete(
            high.task.id,
            TaskCompleteCreate(lease_token="wrong"),
            now=NOW + timedelta(seconds=1),
        )

    heartbeat = queue.heartbeat(
        high.task.id,
        TaskLeaseCreate(lease_token=claimed.lease_token, lease_seconds=120),
        now=NOW + timedelta(seconds=1),
    )
    completed = queue.complete(
        high.task.id,
        TaskCompleteCreate(lease_token=claimed.lease_token, result={"proposal_id": "p1"}),
        now=NOW + timedelta(seconds=2),
    )
    assert heartbeat.lease_expires_at == NOW + timedelta(seconds=121)
    assert completed.status == "succeeded"
    assert completed.result == {"proposal_id": "p1"}
    with pytest.raises(TaskStateError):
        queue.cancel(
            high.task.id,
            TaskCancelCreate(actor="user", reason="too late"),
            now=NOW + timedelta(seconds=3),
        )


def test_retry_non_retryable_failure_and_expired_lease_dead_letter(tmp_path: Path) -> None:
    queue = JsonlTaskQueue(tmp_path)
    retry_task = enqueue(queue, "retry", max_attempts=2)
    first = queue.claim(TaskClaimCreate(worker_id="worker", lease_seconds=5), now=NOW)
    retry = queue.fail(
        retry_task.task.id,
        TaskFailCreate(
            lease_token=first.lease_token,
            error="temporary",
            retry_delay_seconds=10,
        ),
        now=NOW + timedelta(seconds=1),
    )
    assert retry.status == "queued"
    assert queue.claim(TaskClaimCreate(worker_id="early"), now=NOW + timedelta(seconds=5)) is None
    second = queue.claim(
        TaskClaimCreate(worker_id="worker-2", lease_seconds=5), now=NOW + timedelta(seconds=11)
    )
    assert second.attempts == 2

    assert queue.claim(TaskClaimCreate(worker_id="reaper"), now=NOW + timedelta(seconds=17)) is None
    assert queue.get(retry_task.task.id).status == "dead_letter"
    assert [event.type for event in queue.events(retry_task.task.id)][-1] == "dead_lettered"

    failed_task = enqueue(queue, "fatal")
    fatal_claim = queue.claim(TaskClaimCreate(worker_id="worker"), now=NOW + timedelta(seconds=20))
    failed = queue.fail(
        failed_task.task.id,
        TaskFailCreate(
            lease_token=fatal_claim.lease_token,
            error="invalid input",
            retryable=False,
        ),
        now=NOW + timedelta(seconds=21),
    )
    assert failed.status == "failed"


def test_atomic_claim_cancel_and_corruption(tmp_path: Path) -> None:
    queue = JsonlTaskQueue(tmp_path)
    task = enqueue(queue, "concurrent")

    def claim(worker: str):
        return queue.claim(TaskClaimCreate(worker_id=worker), now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["one", "two"]))
    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    cancelled = queue.cancel(
        task.task.id,
        TaskCancelCreate(
            actor="operator",
            reason="stop",
            lease_token=claimed[0].lease_token,
        ),
        now=NOW + timedelta(seconds=1),
    )
    assert cancelled.status == "cancelled"

    queue.tasks_path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(TaskCorruptionError, match="line 1"):
        queue.list()
