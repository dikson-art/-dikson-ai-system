from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml


class WikiStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WikiPageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    slug: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str = Field(default="article", min_length=1, max_length=100)
    status: WikiStatus = WikiStatus.ACTIVE
    tags: set[str] = Field(default_factory=set)
    source_ids: list[str] = Field(default_factory=list)
    related_page_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    content: str = Field(default="", max_length=200_000)
    actor: str = Field(default="user", min_length=1, max_length=200)
    reason: str = Field(default="create", min_length=1, max_length=500)

    @field_validator("title", "kind", "actor", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> set[str]:
        if value is None:
            return set()
        return {str(tag).strip() for tag in value if str(tag).strip()}


class WikiPageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    slug: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, min_length=1, max_length=100)
    tags: set[str] | None = None
    source_ids: list[str] | None = None
    related_page_ids: list[str] | None = None
    related_memory_ids: list[str] | None = None
    content: str | None = Field(default=None, max_length=200_000)
    actor: str = Field(default="user", min_length=1, max_length=200)
    reason: str = Field(default="update", min_length=1, max_length=500)


    @field_validator("title", "kind", "actor", "reason")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_optional_tags(cls, value: Any) -> set[str] | None:
        if value is None:
            return None
        return {str(tag).strip() for tag in value if str(tag).strip()}

class WikiPage(BaseModel):
    id: str
    title: str
    slug: str
    project_id: str
    kind: str
    status: WikiStatus
    tags: set[str]
    source_ids: list[str]
    related_page_ids: list[str]
    related_memory_ids: list[str]
    created_at: datetime
    updated_at: datetime
    content: str
    backlinks: list[str] = Field(default_factory=list)


class WikiHistoryEntry(BaseModel):
    operation_id: str
    page_id: str
    action: str
    actor: str
    reason: str
    recorded_at: datetime
    previous: WikiPage | None


class WikiStorageError(RuntimeError):
    pass


class WikiCorruptionError(WikiStorageError):
    pass


class DuplicateSlugError(ValueError):
    pass


class MarkdownWikiStore:
    """Markdown + YAML front matter Wiki with snapshots and computed backlinks."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.pages_dir = self.root / "pages"
        self.history_dir = self.root / "history"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = lock_timeout

    def create(self, project_id: str, payload: WikiPageCreate) -> WikiPage:
        now = datetime.now(timezone.utc)
        slug = self.slugify(payload.slug or payload.title)
        with self._lock():
            self._ensure_unique_slug(slug)
            page = WikiPage(
                id=uuid4().hex,
                project_id=project_id,
                title=payload.title,
                slug=slug,
                kind=payload.kind,
                status=payload.status,
                tags=payload.tags,
                source_ids=payload.source_ids,
                related_page_ids=payload.related_page_ids,
                related_memory_ids=payload.related_memory_ids,
                created_at=now,
                updated_at=now,
                content=payload.content,
            )
            self._write_page(page)
            self._write_history(page.id, "create", payload.actor, payload.reason, None)
        return page

    def list(
        self,
        *,
        status: WikiStatus | None = WikiStatus.ACTIVE,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[WikiPage]:
        with self._lock():
            pages = self._all_pages()
        if status is not None:
            pages = [page for page in pages if page.status == status]
        if tag is not None:
            pages = [page for page in pages if tag in page.tags]
        if query:
            needle = query.casefold()
            pages = [
                page
                for page in pages
                if needle in page.title.casefold() or needle in page.content.casefold()
            ]
        return [self._with_backlinks(page, pages=None) for page in pages]

    def get(self, page_id: str) -> WikiPage:
        with self._lock():
            page = self._read_page(page_id)
            return self._with_backlinks(page)

    def update(self, page_id: str, payload: WikiPageUpdate) -> WikiPage:
        with self._lock():
            previous = self._read_page(page_id)
            values = payload.model_dump(exclude={"actor", "reason"}, exclude_none=True)
            if "slug" in values:
                values["slug"] = self.slugify(values["slug"])
                self._ensure_unique_slug(values["slug"], exclude_page_id=page_id)
            updated = previous.model_copy(
                update={**values, "updated_at": datetime.now(timezone.utc), "backlinks": []}
            )
            self._write_history(page_id, "update", payload.actor, payload.reason, previous)
            self._write_page(updated)
        return self._with_backlinks(updated)

    def archive(self, page_id: str, *, actor: str, reason: str) -> WikiPage:
        with self._lock():
            previous = self._read_page(page_id)
            if previous.status == WikiStatus.ARCHIVED:
                return self._with_backlinks(previous)
            archived = previous.model_copy(
                update={
                    "status": WikiStatus.ARCHIVED,
                    "updated_at": datetime.now(timezone.utc),
                    "backlinks": [],
                }
            )
            self._write_history(page_id, "archive", actor, reason, previous)
            self._write_page(archived)
        return self._with_backlinks(archived)

    def history(self, page_id: str) -> list[WikiHistoryEntry]:
        with self._lock():
            self._read_page(page_id)
            directory = self.history_dir / page_id
            entries = []
            for path in sorted(directory.glob("*.json")):
                try:
                    entries.append(
                        WikiHistoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
                    )
                except ValueError as exc:
                    raise WikiCorruptionError(f"Invalid history entry for page {page_id}") from exc
        return entries

    def _all_pages(self) -> list[WikiPage]:
        return sorted(
            (self._parse_page(path) for path in self.pages_dir.glob("*.md")),
            key=lambda page: page.created_at,
        )

    def _read_page(self, page_id: str) -> WikiPage:
        path = self.pages_dir / f"{page_id}.md"
        if not path.exists():
            raise KeyError(page_id)
        return self._parse_page(path)

    def _parse_page(self, path: Path) -> WikiPage:
        try:
            text = path.read_text(encoding="utf-8")
            match = re.fullmatch(r"---\n(.*?)\n---\n?(.*)", text, flags=re.DOTALL)
            if match is None:
                raise ValueError("missing front matter")
            metadata = yaml.safe_load(match.group(1))
            if not isinstance(metadata, dict):
                raise ValueError("front matter must be a mapping")
            return WikiPage.model_validate({**metadata, "content": match.group(2), "backlinks": []})
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise WikiCorruptionError(f"Invalid Wiki page {path.name}") from exc

    def _write_page(self, page: WikiPage) -> None:
        path = self.pages_dir / f"{page.id}.md"
        payload = page.model_dump(mode="json", exclude={"content", "backlinks"})
        front_matter = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        self._atomic_write(path, f"---\n{front_matter}\n---\n{page.content}")

    def _write_history(
        self,
        page_id: str,
        action: str,
        actor: str,
        reason: str,
        previous: WikiPage | None,
    ) -> None:
        operation_id = uuid4().hex
        entry = WikiHistoryEntry(
            operation_id=operation_id,
            page_id=page_id,
            action=action,
            actor=actor,
            reason=reason,
            recorded_at=datetime.now(timezone.utc),
            previous=previous,
        )
        directory = self.history_dir / page_id
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = entry.recorded_at.strftime("%Y%m%dT%H%M%S%fZ")
        self._atomic_write(
            directory / f"{timestamp}-{operation_id}.json",
            entry.model_dump_json(indent=2),
        )

    def _with_backlinks(self, page: WikiPage, pages: list[WikiPage] | None = None) -> WikiPage:
        candidates = pages if pages is not None else self._all_pages()
        marker = f"[[{page.id}]]"
        backlinks = sorted(
            candidate.id
            for candidate in candidates
            if candidate.id != page.id
            and (page.id in candidate.related_page_ids or marker in candidate.content)
        )
        return page.model_copy(update={"backlinks": backlinks})

    def _ensure_unique_slug(self, slug: str, *, exclude_page_id: str | None = None) -> None:
        for page in self._all_pages():
            if page.id != exclude_page_id and page.slug == slug:
                raise DuplicateSlugError(slug)

    def _atomic_write(self, path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise WikiStorageError(f"Could not write {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".wiki.lock"), timeout=self.lock_timeout)

    @staticmethod
    def slugify(value: str) -> str:
        normalized = value.strip().casefold()
        slug = re.sub(r"[^a-z0-9а-яё_-]+", "-", normalized).strip("-")
        if not slug:
            raise ValueError("slug does not contain usable characters")
        return slug
