from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock, Timeout
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class MemoryKind(StrEnum):
    FACT = "fact"
    DECISION = "decision"
    TASK = "task"
    HYPOTHESIS = "hypothesis"
    SOURCE = "source"
    SUMMARY = "summary"


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        min_length=1,
        max_length=20_000,
        validation_alias=AliasChoices("content", "text"),
    )
    kind: MemoryKind = MemoryKind.FACT
    tags: set[str] = Field(default_factory=set)
    source_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    related_page_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        return normalized

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> Any:
        if value is None:
            return set()
        return {str(tag).strip() for tag in value if str(tag).strip()}

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON serializable") from exc
        return value


class MemoryRecord(MemoryCreate):
    id: str
    project_id: str
    created_at: datetime

    @property
    def project(self) -> str:
        """Compatibility alias for the original CLI/core model."""
        return self.project_id

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class MemoryStorageError(RuntimeError):
    """Base error for local memory persistence failures."""


class MemoryCorruptionError(MemoryStorageError):
    """Raised when a non-empty JSONL row cannot be validated."""


class JsonlMemoryStore:
    """Canonical append-only JSONL memory store shared by API and CLI."""

    def __init__(
        self,
        root: str | Path = "data/projects",
        *,
        legacy_root: str | Path | None = None,
        lock_timeout: float = 10,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.legacy_root = Path(legacy_root) if legacy_root is not None else None
        self.lock_timeout = lock_timeout

    def append(
        self,
        *,
        project: str | None = None,
        project_id: str | None = None,
        payload: MemoryCreate | None = None,
        kind: MemoryKind | str = MemoryKind.FACT,
        content: str | None = None,
        text: str | None = None,
        tags: set[str] | list[str] | None = None,
        source_ids: list[str] | None = None,
        related_memory_ids: list[str] | None = None,
        related_page_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        normalized_project = self._project_id(project_id or project or "")
        create = payload or MemoryCreate.model_validate(
            {
                "content": content if content is not None else text,
                "kind": kind,
                "tags": tags or [],
                "source_ids": source_ids or [],
                "related_memory_ids": related_memory_ids or [],
                "related_page_ids": related_page_ids or [],
                "metadata": metadata or {},
            }
        )
        record = MemoryRecord(
            id=uuid4().hex,
            project_id=normalized_project,
            created_at=datetime.now(timezone.utc),
            **create.model_dump(),
        )
        path = self._path(normalized_project)
        if path.exists():
            self._read(normalized_project)
        line = record.model_dump_json() + "\n"
        try:
            with self._lock(path):
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
        except (OSError, Timeout) as exc:
            raise MemoryStorageError(f"Could not append memory for {normalized_project}") from exc
        return record

    def list(
        self,
        project: str | None = None,
        *,
        project_id: str | None = None,
        kind: MemoryKind | str | None = None,
        tag: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        normalized_project = self._project_id(project_id or project or "")
        records = self._read(normalized_project)
        if kind is not None:
            expected_kind = MemoryKind(kind)
            records = [record for record in records if record.kind == expected_kind]
        if tag is not None:
            records = [record for record in records if tag in record.tags]
        if source_id is not None:
            records = [record for record in records if source_id in record.source_ids]
        return records[-limit:]

    def get(self, project_id: str, memory_id: str) -> MemoryRecord:
        for record in self._read(self._project_id(project_id)):
            if record.id == memory_id:
                return record
        raise KeyError(memory_id)

    def _read(self, project_id: str) -> list[MemoryRecord]:
        path = self._path(project_id, create=False)
        if not path.exists() and self.legacy_root is not None:
            self._migrate_legacy(project_id, path)
        if not path.exists():
            return []
        try:
            with self._lock(path):
                rows = path.read_text(encoding="utf-8").splitlines()
        except (OSError, Timeout) as exc:
            raise MemoryStorageError(f"Could not read memory for {project_id}") from exc

        records: list[MemoryRecord] = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                record = MemoryRecord.model_validate_json(row)
            except ValueError as exc:
                raise MemoryCorruptionError(
                    f"Invalid memory record at line {line_number} for project {project_id}"
                ) from exc
            if record.project_id != project_id:
                raise MemoryCorruptionError(
                    f"Project mismatch at line {line_number} for project {project_id}"
                )
            records.append(record)
        return records

    def _migrate_legacy(self, project_id: str, target: Path) -> None:
        if self.legacy_root is None:
            return
        legacy = self.legacy_root / f"{self._safe_name(project_id)}.jsonl"
        if not legacy.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock(target):
                if target.exists():
                    return
                migrated: list[str] = []
                for line_number, row in enumerate(
                    legacy.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if not row.strip():
                        continue
                    try:
                        payload = json.loads(row)
                        legacy_kind = payload.get("kind", "fact")
                        if legacy_kind == "note":
                            legacy_kind = "fact"
                        record = MemoryRecord(
                            id=uuid5(
                                NAMESPACE_URL,
                                f"dikson-memory:{project_id}:{line_number}:{row}",
                            ).hex,
                            project_id=project_id,
                            kind=legacy_kind,
                            content=payload["content"],
                            created_at=payload["created_at"],
                            metadata=payload.get("metadata", {}),
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise MemoryCorruptionError(
                            f"Invalid legacy memory at line {line_number} for project {project_id}"
                        ) from exc
                    migrated.append(record.model_dump_json())
                with target.open("x", encoding="utf-8", newline="\n") as handle:
                    if migrated:
                        handle.write("\n".join(migrated) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        except MemoryCorruptionError:
            raise
        except (OSError, Timeout) as exc:
            raise MemoryStorageError(f"Could not migrate memory for {project_id}") from exc
    def _path(self, project_id: str, *, create: bool = True) -> Path:
        directory = self.root / self._safe_name(project_id)
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory / "memory.jsonl"

    def _lock(self, path: Path) -> FileLock:
        return FileLock(str(path) + ".lock", timeout=self.lock_timeout)

    @staticmethod
    def _project_id(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("project_id must not be empty")
        return normalized

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
        safe = safe.strip("-").lower()
        if not safe:
            raise ValueError("project_id does not contain usable characters")
        return safe
