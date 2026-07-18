from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeType(StrEnum):
    PROJECT = "project"
    MEMORY = "memory"
    WIKI_PAGE = "wiki_page"
    SOURCE = "source"
    DOCUMENT = "document"
    PERSON = "person"
    ARTICLE = "article"
    TASK = "task"
    RESEARCH = "research"


class EdgeType(StrEnum):
    CONTAINS = "contains"
    RELATES_TO = "relates_to"
    REFERENCES = "references"
    DERIVED_FROM = "derived_from"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    MENTIONS = "mentions"


class GraphNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: NodeType
    label: str = Field(min_length=1, max_length=500)
    entity_id: str | None = Field(default=None, max_length=500)
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("label must not be blank")
        return normalized

    @field_validator("properties")
    @classmethod
    def properties_must_be_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("properties must be JSON serializable") from exc
        return value


class GraphNode(GraphNodeCreate):
    id: str
    project_id: str
    created_at: datetime
    projected: bool = False


class GraphEdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node_id: str = Field(min_length=1, max_length=500)
    to_node_id: str = Field(min_length=1, max_length=500)
    type: EdgeType = EdgeType.RELATES_TO
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("from_node_id", "to_node_id")
    @classmethod
    def normalize_node_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("node id must not be blank")
        return normalized

    @field_validator("properties")
    @classmethod
    def edge_properties_must_be_json_serializable(
        cls, value: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("properties must be JSON serializable") from exc
        return value


class GraphEdge(GraphEdgeCreate):
    id: str
    project_id: str
    created_at: datetime
    projected: bool = False


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphStorageError(RuntimeError):
    pass


class GraphCorruptionError(GraphStorageError):
    pass


class DuplicateEntityError(ValueError):
    pass


class JsonlGraphRepository:
    """Append-only repository for explicit graph nodes and edges."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.nodes_path = self.root / "nodes.jsonl"
        self.edges_path = self.root / "edges.jsonl"
        self.lock_timeout = lock_timeout

    def add_node(self, project_id: str, payload: GraphNodeCreate) -> GraphNode:
        with self._lock():
            nodes = self._read_rows(self.nodes_path, GraphNode)
            if payload.entity_id and any(
                node.type == payload.type and node.entity_id == payload.entity_id for node in nodes
            ):
                raise DuplicateEntityError(payload.entity_id)
            node = GraphNode(
                id=uuid4().hex,
                project_id=project_id,
                created_at=datetime.now(timezone.utc),
                **payload.model_dump(),
            )
            self._append(self.nodes_path, node.model_dump_json())
        return node

    def add_edge(
        self,
        project_id: str,
        payload: GraphEdgeCreate,
        *,
        known_node_ids: set[str],
    ) -> GraphEdge:
        if payload.from_node_id not in known_node_ids or payload.to_node_id not in known_node_ids:
            raise KeyError("edge endpoint")
        edge = GraphEdge(
            id=uuid4().hex,
            project_id=project_id,
            created_at=datetime.now(timezone.utc),
            **payload.model_dump(),
        )
        with self._lock():
            self._append(self.edges_path, edge.model_dump_json())
        return edge

    def nodes(self) -> list[GraphNode]:
        with self._lock():
            return self._read_rows(self.nodes_path, GraphNode)

    def edges(self) -> list[GraphEdge]:
        with self._lock():
            return self._read_rows(self.edges_path, GraphEdge)

    def _read_rows(self, path: Path, model: type[GraphNode] | type[GraphEdge]):
        if not path.exists():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise GraphStorageError(f"Could not read {path.name}") from exc
        result = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                result.append(model.model_validate_json(row))
            except ValueError as exc:
                raise GraphCorruptionError(
                    f"Invalid {path.name} row at line {line_number}"
                ) from exc
        return result

    def _append(self, path: Path, line: str) -> None:
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise GraphStorageError(f"Could not append {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".graph.lock"), timeout=self.lock_timeout)
