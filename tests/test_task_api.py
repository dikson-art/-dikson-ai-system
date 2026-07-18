from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_project_and_run(tmp_path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Task Queue"}).json()["id"]
    run = client.post(
        f"/projects/{project_id}/agents/planning/runs",
        json={"objective": "Build a plan", "requested_tools": ["plan_propose"]},
    ).json()
    return project_id, run["id"]


def test_task_api_lifecycle_and_idempotency(tmp_path, monkeypatch) -> None:
    project_id, run_id = create_project_and_run(tmp_path, monkeypatch)
    payload = {
        "run_id": run_id,
        "priority": 5,
        "max_attempts": 2,
        "idempotency_key": "planning-1",
    }
    created = client.post(f"/projects/{project_id}/tasks", json=payload)
    repeated = client.post(f"/projects/{project_id}/tasks", json=payload)
    assert created.status_code == 201
    assert "lease_token" not in created.json()
    assert repeated.json()["task"]["id"] == created.json()["task"]["id"]

    claimed = client.post(
        f"/projects/{project_id}/tasks/claim",
        json={"worker_id": "planner-worker", "agent_id": "planning"},
    )
    assert claimed.status_code == 200
    task_id = claimed.json()["task"]["id"]
    token = claimed.json()["lease_token"]
    invalid = client.post(
        f"/projects/{project_id}/tasks/{task_id}/complete",
        json={"lease_token": "wrong", "result": {}},
    )
    assert invalid.status_code == 409
    completed = client.post(
        f"/projects/{project_id}/tasks/{task_id}/complete",
        json={"lease_token": token, "result": {"proposal_id": "proposal-1"}},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert (
        client.get(f"/projects/{project_id}/tasks", params={"status": "succeeded"}).json()[0][
            "task"
        ]["id"]
        == task_id
    )
    events = client.get(f"/projects/{project_id}/tasks/{task_id}/events")
    assert [event["type"] for event in events.json()] == ["claimed", "completed"]
    assert all("lease_token" not in event for event in events.json())


def test_task_api_missing_resources_validation_and_corruption(tmp_path, monkeypatch) -> None:
    project_id, _ = create_project_and_run(tmp_path, monkeypatch)
    missing_run = client.post(f"/projects/{project_id}/tasks", json={"run_id": "missing"})
    assert missing_run.status_code == 404
    assert client.get("/projects/missing/tasks").status_code == 404
    assert (
        client.post(
            f"/projects/{project_id}/tasks/claim",
            json={"worker_id": "worker", "lease_seconds": 1},
        ).status_code
        == 422
    )

    tasks_dir = tmp_path / "projects" / project_id / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "tasks.jsonl").write_text("{broken}\n", encoding="utf-8")
    corrupt = client.get(f"/projects/{project_id}/tasks")
    assert corrupt.status_code == 500
    assert corrupt.json() == {"detail": "Локальная очередь задач повреждена"}
    assert "line" not in corrupt.text
