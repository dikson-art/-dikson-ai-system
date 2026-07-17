from pathlib import Path

import pytest

from dikson_li.memory import JsonlMemoryStore


def test_append_and_list(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)
    created = store.append(project="Dikson Li", kind="decision", content="Use local JSONL memory")

    records = store.list("Dikson Li")

    assert records == [created]
    assert records[0].metadata == {}


def test_rejects_empty_content(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path)

    with pytest.raises(ValueError, match="content"):
        store.append(project="dikson", kind="note", content="  ")
