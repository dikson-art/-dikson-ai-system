import json
import sys

from fastapi.testclient import TestClient

from app.main import app
from dikson_li.cli import main
from dikson_li.memory import JsonlMemoryStore


def test_cli_api_and_core_share_one_store(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIKSON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.config.settings.dikson_data_dir", tmp_path)
    client = TestClient(app)
    project_id = client.post("/projects", json={"name": "CLI Project"}).json()["id"]

    monkeypatch.setattr(
        sys,
        "argv",
        ["dikson-li", "remember", project_id, "Запись через CLI", "--kind", "decision"],
    )
    assert main() == 0
    created = json.loads(capsys.readouterr().out)

    api_records = client.get(f"/projects/{project_id}/memory")
    assert api_records.status_code == 200
    assert [record["id"] for record in api_records.json()] == [created["id"]]

    store = JsonlMemoryStore(tmp_path / "projects")
    core_record = store.append(project_id=project_id, content="Core to CLI", kind="summary")
    monkeypatch.setattr(sys, "argv", ["dikson-li", "recall", project_id, "--limit", "10"])
    assert main() == 0
    recalled = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in recalled] == [created["id"], core_record.id]
