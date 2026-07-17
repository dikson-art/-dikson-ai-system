from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    project: str
    kind: str
    content: str
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonlMemoryStore:
    """Append-only local memory store with simple project filtering."""

    def __init__(self, root: str | Path = "data/memory") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, *, project: str, kind: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        normalized_project = project.strip()
        normalized_kind = kind.strip()
        normalized_content = content.strip()
        if not normalized_project:
            raise ValueError("project must not be empty")
        if not normalized_kind:
            raise ValueError("kind must not be empty")
        if not normalized_content:
            raise ValueError("content must not be empty")

        record = MemoryRecord(
            project=normalized_project,
            kind=normalized_kind,
            content=normalized_content,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        path = self.root / f"{self._safe_name(normalized_project)}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def list(self, project: str, *, limit: int = 50) -> list[MemoryRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        path = self.root / f"{self._safe_name(project)}.jsonl"
        if not path.exists():
            return []
        rows = path.read_text(encoding="utf-8").splitlines()
        return [MemoryRecord(**json.loads(row)) for row in rows[-limit:]]

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value.strip()).strip("-")
        if not safe:
            raise ValueError("project name does not contain usable characters")
        return safe.lower()
