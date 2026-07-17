from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field, field_validator

from app.storage import project_dir


class MemoryKind(StrEnum):
    FACT = "fact"
    DECISION = "decision"
    TASK = "task"
    HYPOTHESIS = "hypothesis"
    SOURCE = "source"
    SUMMARY = "summary"


class MemoryCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=20_000,
        validation_alias=AliasChoices("content", "text"),
    )
    kind: MemoryKind = MemoryKind.FACT
    tags: set[str] = Field(default_factory=set)
    source_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        return normalized


class MemoryRecord(MemoryCreate):
    id: str
    project_id: str
    created_at: datetime


class JsonlProjectMemory:
    """Append-only memory journal scoped to one project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.path = project_dir(project_id) / "memory.jsonl"

    def append(self, payload: MemoryCreate) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid4().hex,
            project_id=self.project_id,
            created_at=datetime.now(timezone.utc),
            **payload.model_dump(),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        return record

    def list(
        self,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        if not self.path.exists():
            return []

        rows = self.path.read_text(encoding="utf-8").splitlines()
        records = [MemoryRecord.model_validate_json(row) for row in rows if row]
        if kind is not None:
            records = [record for record in records if record.kind == kind]
        if tag is not None:
            records = [record for record in records if tag in record.tags]
        return records[-limit:]

    def get(self, memory_id: str) -> MemoryRecord:
        if self.path.exists():
            for row in self.path.read_text(encoding="utf-8").splitlines():
                record = MemoryRecord.model_validate_json(row)
                if record.id == memory_id:
                    return record
        raise KeyError(memory_id)
