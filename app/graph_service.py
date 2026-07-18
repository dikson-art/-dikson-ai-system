from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dikson_li.graph import (
    EdgeType,
    GraphCorruptionError,
    GraphEdge,
    GraphEdgeCreate,
    GraphNode,
    GraphNodeCreate,
    GraphSnapshot,
    JsonlGraphRepository,
    NodeType,
)
from dikson_li.memory import JsonlMemoryStore
from dikson_li.wiki import MarkdownWikiStore


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class KnowledgeGraphService:
    """Builds a graph projection without copying Memory or Wiki content to storage."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        project_root = data_dir / "projects" / project_id
        self.project_root = project_root
        self.memory = JsonlMemoryStore(
            data_dir / "projects", legacy_root=data_dir / "memory"
        )
        self.wiki = MarkdownWikiStore(project_root / "wiki")
        self.repository = JsonlGraphRepository(project_root / "graph")

    def snapshot(
        self,
        *,
        node_type: NodeType | None = None,
        edge_type: EdgeType | None = None,
        query: str | None = None,
    ) -> GraphSnapshot:
        nodes, edges = self._projection()
        nodes.extend(self.repository.nodes())
        known_node_ids = {node.id for node in nodes}
        edges.extend(
            edge
            for edge in self.repository.edges()
            if edge.from_node_id in known_node_ids and edge.to_node_id in known_node_ids
        )
        if node_type is not None:
            selected_ids = {node.id for node in nodes if node.type == node_type}
            nodes = [node for node in nodes if node.id in selected_ids]
            edges = [
                edge
                for edge in edges
                if edge.from_node_id in selected_ids or edge.to_node_id in selected_ids
            ]
        if query:
            needle = query.casefold()
            selected_ids = {node.id for node in nodes if needle in node.label.casefold()}
            nodes = [node for node in nodes if node.id in selected_ids]
            edges = [
                edge
                for edge in edges
                if edge.from_node_id in selected_ids or edge.to_node_id in selected_ids
            ]
        if edge_type is not None:
            edges = [edge for edge in edges if edge.type == edge_type]
        return GraphSnapshot(nodes=nodes, edges=edges)

    def add_node(self, payload: GraphNodeCreate) -> GraphNode:
        return self.repository.add_node(self.project_id, payload)

    def add_edge(self, payload: GraphEdgeCreate) -> GraphEdge:
        known_ids = {node.id for node in self.snapshot().nodes}
        return self.repository.add_edge(
            self.project_id, payload, known_node_ids=known_ids
        )

    def neighbors(self, node_id: str) -> GraphSnapshot:
        snapshot = self.snapshot()
        node_by_id = {node.id: node for node in snapshot.nodes}
        if node_id not in node_by_id:
            raise KeyError(node_id)
        edges = [
            edge
            for edge in snapshot.edges
            if edge.from_node_id == node_id or edge.to_node_id == node_id
        ]
        neighbor_ids = {node_id}
        for edge in edges:
            neighbor_ids.add(edge.from_node_id)
            neighbor_ids.add(edge.to_node_id)
        return GraphSnapshot(
            nodes=[node_by_id[value] for value in sorted(neighbor_ids)],
            edges=edges,
        )

    def _projection(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes = [
            GraphNode(
                id=f"project:{self.project_id}",
                project_id=self.project_id,
                type=NodeType.PROJECT,
                label=self.project_id,
                entity_id=self.project_id,
                created_at=EPOCH,
                projected=True,
            )
        ]
        edges: list[GraphEdge] = []
        source_ids: set[str] = set()

        memories = self.memory.list(self.project_id, limit=100_000)
        for memory in memories:
            node_id = f"memory:{memory.id}"
            node_type = NodeType.TASK if memory.kind.value == "task" else NodeType.MEMORY
            nodes.append(
                GraphNode(
                    id=node_id,
                    project_id=self.project_id,
                    type=node_type,
                    label=memory.content,
                    entity_id=memory.id,
                    properties={"kind": memory.kind.value, "tags": sorted(memory.tags)},
                    created_at=memory.created_at,
                    projected=True,
                )
            )
            edges.append(self._edge(f"project:{self.project_id}", node_id, EdgeType.CONTAINS))
            for related_id in memory.related_memory_ids:
                edges.append(
                    self._edge(node_id, f"memory:{related_id}", EdgeType.RELATES_TO)
                )
            for page_id in memory.related_page_ids:
                edges.append(self._edge(node_id, f"wiki:{page_id}", EdgeType.REFERENCES))
            for source_id in memory.source_ids:
                source_ids.add(source_id)
                edges.append(
                    self._edge(node_id, f"source:{source_id}", EdgeType.DERIVED_FROM)
                )

        pages = self.wiki.list(status=None)
        for page in pages:
            node_id = f"wiki:{page.id}"
            nodes.append(
                GraphNode(
                    id=node_id,
                    project_id=self.project_id,
                    type=NodeType.WIKI_PAGE,
                    label=page.title,
                    entity_id=page.id,
                    properties={"slug": page.slug, "status": page.status.value},
                    created_at=page.created_at,
                    projected=True,
                )
            )
            edges.append(self._edge(f"project:{self.project_id}", node_id, EdgeType.CONTAINS))
            for related_id in page.related_page_ids:
                edges.append(self._edge(node_id, f"wiki:{related_id}", EdgeType.RELATES_TO))
            for memory_id in page.related_memory_ids:
                edges.append(self._edge(node_id, f"memory:{memory_id}", EdgeType.REFERENCES))
            for source_id in page.source_ids:
                source_ids.add(source_id)
                edges.append(
                    self._edge(node_id, f"source:{source_id}", EdgeType.DERIVED_FROM)
                )

        source_records = self._source_records()
        source_ids.update(source_records)
        for source_id in sorted(source_ids):
            record = source_records.get(source_id)
            nodes.append(
                GraphNode(
                    id=f"source:{source_id}",
                    project_id=self.project_id,
                    type=NodeType.DOCUMENT if record else NodeType.SOURCE,
                    label=record["filename"] if record else source_id,
                    entity_id=source_id,
                    properties={"filename": record["filename"]} if record else {},
                    created_at=EPOCH,
                    projected=True,
                )
            )
            edges.append(
                self._edge(
                    f"project:{self.project_id}",
                    f"source:{source_id}",
                    EdgeType.CONTAINS,
                )
            )
        existing_ids = {node.id for node in nodes}
        edges = [
            edge
            for edge in edges
            if edge.from_node_id in existing_ids and edge.to_node_id in existing_ids
        ]
        return nodes, self._deduplicate_edges(edges)

    def _source_records(self) -> dict[str, dict]:
        records = {}
        for path in (self.project_root / "sources").glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records[payload["id"]] = payload
            except (KeyError, OSError, ValueError) as exc:
                raise GraphCorruptionError(f"Invalid source projection {path.name}") from exc
        return records

    def _edge(self, from_id: str, to_id: str, edge_type: EdgeType) -> GraphEdge:
        identity = f"{self.project_id}:{from_id}:{edge_type.value}:{to_id}"
        return GraphEdge(
            id=uuid5(NAMESPACE_URL, identity).hex,
            project_id=self.project_id,
            from_node_id=from_id,
            to_node_id=to_id,
            type=edge_type,
            created_at=EPOCH,
            projected=True,
        )

    @staticmethod
    def _deduplicate_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
        return list({edge.id: edge for edge in edges}.values())
