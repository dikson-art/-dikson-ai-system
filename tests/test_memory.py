from dikson_li.memory import JsonlMemoryStore


def test_append_and_list(tmp_path) -> None:
    store = JsonlMemoryStore(tmp_path)
    created = store.append(project="Dikson-Li", kind="decision", content="Use append-only memory")

    records = store.list("Dikson-Li")

    assert created.content == "Use append-only memory"
    assert len(records) == 1
    assert records[0].kind == "decision"
    assert records[0].to_dict()["project"] == "Dikson-Li"
