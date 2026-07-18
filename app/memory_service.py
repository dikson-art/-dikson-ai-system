from pathlib import Path

from dikson_li.memory import JsonlMemoryStore, MemoryCreate, MemoryKind, MemoryRecord


class MemoryService:
    """Application service that binds the canonical core to the project data root."""

    def __init__(self, data_dir: Path) -> None:
        self.store = JsonlMemoryStore(
            data_dir / "projects", legacy_root=data_dir / "memory"
        )

    def create(self, project_id: str, payload: MemoryCreate) -> MemoryRecord:
        return self.store.append(project_id=project_id, payload=payload)

    def list(
        self,
        project_id: str,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        return self.store.list(
            project_id=project_id,
            kind=kind,
            tag=tag,
            source_id=source_id,
            limit=limit,
        )

    def get(self, project_id: str, memory_id: str) -> MemoryRecord:
        return self.store.get(project_id, memory_id)
