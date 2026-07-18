from pathlib import Path

import pytest
import yaml

from dikson_li.wiki import (
    DuplicateSlugError,
    MarkdownWikiStore,
    WikiPageCreate,
    WikiPageUpdate,
    WikiStatus,
)


def test_create_read_update_history_and_archive(tmp_path: Path) -> None:
    store = MarkdownWikiStore(tmp_path)
    created = store.create(
        "project",
        WikiPageCreate(
            title="Русская страница",
            tags={"история"},
            source_ids=["source-1"],
            related_memory_ids=["memory-1"],
            content="# Содержание\nТекст на русском.",
            actor="wiki-agent",
            reason="initial research",
        ),
    )
    loaded = store.get(created.id)
    assert loaded.content.startswith("# Содержание")
    assert loaded.related_memory_ids == ["memory-1"]

    updated = store.update(
        created.id,
        WikiPageUpdate(
            title="Обновлённая страница",
            content="Новая версия",
            actor="review-agent",
            reason="fact check",
        ),
    )
    history = store.history(created.id)
    assert updated.title == "Обновлённая страница"
    assert [entry.action for entry in history] == ["create", "update"]
    assert history[1].previous is not None
    assert history[1].previous.title == "Русская страница"
    assert history[1].actor == "review-agent"
    assert history[1].reason == "fact check"

    archived = store.archive(created.id, actor="user", reason="obsolete")
    assert archived.status == WikiStatus.ARCHIVED
    assert store.list() == []
    assert store.list(status=None)[0].id == created.id
    assert (tmp_path / "pages" / f"{created.id}.md").exists()
    assert [entry.action for entry in store.history(created.id)] == [
        "create",
        "update",
        "archive",
    ]


def test_yaml_front_matter_search_duplicates_and_backlinks(tmp_path: Path) -> None:
    store = MarkdownWikiStore(tmp_path)
    target = store.create(
        "project",
        WikiPageCreate(title="Целевая страница", slug="target", tags={"knowledge"}),
    )
    source = store.create(
        "project",
        WikiPageCreate(
            title="Источник ссылки",
            related_page_ids=[target.id],
            content=f"Ссылка [[{target.id}]] и уникальный термин.",
        ),
    )

    loaded = store.get(target.id)
    assert loaded.backlinks == [source.id]
    assert [page.id for page in store.list(tag="knowledge")] == [target.id]
    assert [page.id for page in store.list(query="УНИКАЛЬНЫЙ")] == [source.id]

    page_text = (tmp_path / "pages" / f"{target.id}.md").read_text(encoding="utf-8")
    front_matter = page_text.split("---", 2)[1]
    metadata = yaml.safe_load(front_matter)
    assert metadata["id"] == target.id
    assert metadata["project_id"] == "project"
    assert metadata["slug"] == "target"

    with pytest.raises(DuplicateSlugError):
        store.create("project", WikiPageCreate(title="Duplicate", slug="target"))
