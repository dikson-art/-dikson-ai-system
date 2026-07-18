from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dikson_li.memory import (
    JsonlMemoryStore,
    MemoryCorruptionError,
    MemoryCreate,
    MemoryKind,
)


def test_append_read_unicode_metadata_relations_and_order(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)
    first = store.append(
        project="dikson",
        kind="fact",
        content="  Русский факт  ",
        tags=["knowledge", "знание"],
        source_ids=["source-1"],
        related_memory_ids=["memory-0"],
        related_page_ids=["wiki-1"],
        metadata={"confidence": 0.9, "nested": {"language": "ru"}},
    )
    second = store.append(project="dikson", kind="task", content="Следующая задача")

    records = store.list("dikson")

    assert [record.id for record in records] == [first.id, second.id]
    assert records[0].content == "Русский факт"
    assert records[0].metadata == {"confidence": 0.9, "nested": {"language": "ru"}}
    assert records[0].related_memory_ids == ["memory-0"]
    assert records[0].related_page_ids == ["wiki-1"]
    assert store.get("dikson", first.id) == first


def test_filters_limits_and_project_isolation(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)
    store.append(
        project="one", kind="fact", content="A", tags=["shared"], source_ids=["s1"]
    )
    latest = store.append(
        project="one", kind="decision", content="B", tags=["shared"], source_ids=["s2"]
    )
    store.append(project="two", kind="fact", content="C", tags=["shared"], source_ids=["s1"])

    assert [record.id for record in store.list("one", limit=1)] == [latest.id]
    assert [record.kind for record in store.list("one", kind="fact")] == [MemoryKind.FACT]
    assert len(store.list("one", tag="shared")) == 2
    assert [record.id for record in store.list("one", source_id="s2")] == [latest.id]
    assert [record.content for record in store.list("two")] == ["C"]


def test_legacy_text_validation_and_unknown_kind(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)
    legacy = MemoryCreate.model_validate({"text": "Legacy memory record"})
    assert legacy.content == "Legacy memory record"
    assert legacy.kind == MemoryKind.FACT

    with pytest.raises(ValidationError, match="content"):
        store.append(project="dikson", content="   ")
    with pytest.raises(ValidationError, match="kind"):
        store.append(project="dikson", content="Unknown", kind="note")
    with pytest.raises(ValidationError, match="metadata"):
        store.append(project="dikson", content="Invalid metadata", metadata={"bad": object()})


def test_blank_rows_are_ignored_and_corruption_is_explicit(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)
    created = store.append(project="dikson", content="Valid")
    path = tmp_path / "dikson" / "memory.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n   \n", encoding="utf-8")
    assert store.list("dikson") == [created]

    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")
    with pytest.raises(MemoryCorruptionError, match="line 4"):
        store.list("dikson")


def test_parallel_appends_do_not_corrupt_jsonl(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)

    def append(index: int) -> None:
        store.append(project="parallel", content=f"record-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(40)))

    records = store.list("parallel", limit=100)
    assert len(records) == 40
    path = tmp_path / "parallel" / "memory.jsonl"
    assert len([json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]) == 40

def test_legacy_cli_journal_is_migrated_once_with_stable_ids(tmp_path: Path) -> None:
    legacy_root = tmp_path / "memory"
    legacy_root.mkdir()
    legacy_path = legacy_root / "legacy-project.jsonl"
    legacy_path.write_text(
        json.dumps(
            {
                "project": "legacy-project",
                "kind": "note",
                "content": "Старая запись",
                "created_at": "2026-01-01T00:00:00+00:00",
                "metadata": {"migrated": True},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    store = JsonlMemoryStore(tmp_path / "projects", legacy_root=legacy_root)

    first_read = store.list("legacy-project")
    second_read = store.list("legacy-project")

    assert len(first_read) == 1
    assert first_read[0].id == second_read[0].id
    assert first_read[0].kind == MemoryKind.FACT
    assert first_read[0].content == "Старая запись"
    assert first_read[0].metadata == {"migrated": True}
    assert (tmp_path / "projects" / "legacy-project" / "memory.jsonl").exists()
