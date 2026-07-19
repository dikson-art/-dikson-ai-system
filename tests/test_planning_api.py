from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def plan_payload() -> dict:
    return {
        "title": "API Plan",
        "objective": "Exercise the planning API",
        "steps": [
            {
                "id": "plan",
                "title": "Plan",
                "objective": "Create a detailed plan",
                "agent_id": "planning",
                "requested_tools": ["plan_propose"],
                "acceptance_criteria": ["Plan proposal exists"],
            }
        ],
    }


def test_planning_api_approval_activation_and_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Planning API"}).json()["id"]
    created = client.post(f"/projects/{project_id}/plans", json=plan_payload())
    assert created.status_code == 201
    plan_id = created.json()["plan"]["id"]
    assert created.json()["status"] == "draft"
    assert client.post(f"/projects/{project_id}/plans/{plan_id}/dispatch").status_code == 409

    approved = client.post(
        f"/projects/{project_id}/plans/{plan_id}/decision",
        json={"outcome": "approved", "reviewer": "lead", "reason": "checked"},
    )
    assert approved.json()["status"] == "approved"
    active = client.post(
        f"/projects/{project_id}/plans/{plan_id}/activate",
        json={"actor": "lead", "reason": "execute"},
    )
    assert active.json()["steps"][0]["status"] == "ready"
    dispatched = client.post(f"/projects/{project_id}/plans/{plan_id}/dispatch")
    assert dispatched.status_code == 200
    assert dispatched.json()["steps"][0]["status"] == "queued"
    assert dispatched.json()["steps"][0]["task_id"]
    assert (
        client.get(f"/projects/{project_id}/plans", params={"status": "active"}).json()[0]["plan"][
            "id"
        ]
        == plan_id
    )


def test_planning_api_policy_validation_missing_and_corruption(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    project_id = client.post("/projects", json={"name": "Planning Errors"}).json()["id"]
    payload = plan_payload()
    payload["steps"][0]["agent_id"] = "research"
    forbidden = client.post(f"/projects/{project_id}/plans", json=payload)
    assert forbidden.status_code == 403
    assert client.get("/projects/missing/plans").status_code == 404
    assert client.get(f"/projects/{project_id}/plans/missing").status_code == 404

    plans_dir = tmp_path / "projects" / project_id / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plans.jsonl").write_text("{broken}\n", encoding="utf-8")
    corrupt = client.get(f"/projects/{project_id}/plans")
    assert corrupt.status_code == 500
    assert corrupt.json() == {"detail": "Локальное хранилище планов повреждено"}
    assert "line" not in corrupt.text
