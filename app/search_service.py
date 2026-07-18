from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from app.config import settings
from app.graph_service import KnowledgeGraphService
from dikson_li.memory import JsonlMemoryStore
from dikson_li.search import (
    SearchDocument,
    SearchEntityType,
    SearchHit,
    SemanticSearchEngine,
)
from dikson_li.wiki import MarkdownWikiStore, WikiStatus


class SearchStorageError(RuntimeError):
    pass


class SearchCorruptionError(SearchStorageError):
    pass


class SearchProviderError(RuntimeError):
    pass


class OpenAIEmbeddingModel:
    """OpenAI Embeddings API adapter for the provider-neutral core port."""

    def __init__(self, api_key: str, model: str, *, client: Any | None = None) -> None:
        self.model = model
        self.client = client or OpenAI(api_key=api_key)

    def embed(self, texts) -> list[list[float]]:
        inputs = list(texts)
        try:
            response = self.client.embeddings.create(
                input=inputs,
                model=self.model,
                encoding_format="float",
            )
        except OpenAIError as exc:
            raise SearchProviderError("OpenAI embeddings request failed") from exc
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


class SemanticSearchService:
    """Projects canonical project data into one provider-neutral search corpus."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.data_dir = data_dir
        self.project_id = project_id
        self.project_root = data_dir / "projects" / project_id
        self.memory = JsonlMemoryStore(data_dir / "projects", legacy_root=data_dir / "memory")
        self.wiki = MarkdownWikiStore(self.project_root / "wiki")
        self.graph = KnowledgeGraphService(data_dir, project_id)
        self.engine = SemanticSearchEngine(self._embedding_model())

    @staticmethod
    def _embedding_model():
        if settings.search_embedding_provider == "local":
            return None
        if not settings.openai_api_key:
            raise SearchProviderError("OPENAI_API_KEY is required for the OpenAI search provider")
        return OpenAIEmbeddingModel(settings.openai_api_key, settings.openai_embedding_model)

    def search(
        self,
        query: str,
        *,
        entity_type: SearchEntityType | None = None,
        limit: int = 10,
        min_score: float = 0.05,
        include_archived: bool = False,
    ) -> list[SearchHit]:
        documents, node_to_documents = self._documents(include_archived=include_archived)
        available_ids = {item.id for item in documents}
        relations = self._relations(node_to_documents, available_ids)
        hits = self.engine.search(
            query,
            documents,
            relations=relations,
            limit=max(1, len(documents)),
            min_score=min_score,
        )
        if entity_type is not None:
            hits = [item for item in hits if item.entity_type == entity_type]
        return hits[:limit]

    def _documents(
        self, *, include_archived: bool
    ) -> tuple[list[SearchDocument], dict[str, set[str]]]:
        documents: list[SearchDocument] = []
        node_to_documents: dict[str, set[str]] = {}
        for memory in self.memory.list(self.project_id, limit=100_000):
            document = SearchDocument(
                id=f"memory:{memory.id}",
                project_id=self.project_id,
                entity_type=SearchEntityType.MEMORY,
                entity_id=memory.id,
                title=memory.kind.value,
                text=memory.content,
                tags=memory.tags,
                metadata={"kind": memory.kind.value, "created_at": memory.created_at.isoformat()},
            )
            documents.append(document)
            node_to_documents[f"memory:{memory.id}"] = {document.id}

        status = None if include_archived else WikiStatus.ACTIVE
        for page in self.wiki.list(status=status):
            document = SearchDocument(
                id=f"wiki:{page.id}",
                project_id=self.project_id,
                entity_type=SearchEntityType.WIKI_PAGE,
                entity_id=page.id,
                title=page.title,
                text=page.content,
                tags=page.tags,
                metadata={"slug": page.slug, "status": page.status.value},
            )
            documents.append(document)
            node_to_documents[f"wiki:{page.id}"] = {document.id}

        documents.extend(self._source_documents(node_to_documents))
        projected_node_ids = set(node_to_documents) | {f"project:{self.project_id}"}
        for node in self.graph.repository.nodes():
            if node.id in projected_node_ids:
                continue
            properties = json.dumps(node.properties, ensure_ascii=False, sort_keys=True)
            document = SearchDocument(
                id=f"graph:{node.id}",
                project_id=self.project_id,
                entity_type=SearchEntityType.GRAPH_NODE,
                entity_id=node.id,
                title=node.label,
                text=properties,
                metadata={"node_type": node.type.value, "entity_id": node.entity_id},
            )
            documents.append(document)
            node_to_documents[node.id] = {document.id}
        return documents, node_to_documents

    def _source_documents(self, node_to_documents: dict[str, set[str]]) -> list[SearchDocument]:
        documents = []
        for path in sorted((self.project_root / "sources").glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                source_id = str(payload["id"])
                filename = str(payload["filename"])
                chunks = payload["chunks"]
                if not isinstance(chunks, list) or not all(
                    isinstance(chunk, str) for chunk in chunks
                ):
                    raise ValueError("chunks must be strings")
            except (KeyError, OSError, TypeError, ValueError) as exc:
                raise SearchCorruptionError(f"Invalid search source {path.name}") from exc
            source_document_ids = set()
            for index, chunk in enumerate(chunks):
                document = SearchDocument(
                    id=f"source:{source_id}:{index}",
                    project_id=self.project_id,
                    entity_type=SearchEntityType.SOURCE,
                    entity_id=source_id,
                    title=filename,
                    text=chunk,
                    metadata={
                        "source_id": source_id,
                        "filename": filename,
                        "chunk": index,
                    },
                )
                documents.append(document)
                source_document_ids.add(document.id)
            node_to_documents[f"source:{source_id}"] = source_document_ids
        return documents

    def _relations(
        self,
        node_to_documents: dict[str, set[str]],
        available_ids: set[str],
    ) -> dict[str, set[str]]:
        relations: dict[str, set[str]] = {}
        for edge in self.graph.snapshot().edges:
            left_ids = node_to_documents.get(edge.from_node_id, set()) & available_ids
            right_ids = node_to_documents.get(edge.to_node_id, set()) & available_ids
            for left_id in left_ids:
                relations.setdefault(left_id, set()).update(right_ids)
            for right_id in right_ids:
                relations.setdefault(right_id, set()).update(left_ids)
        return relations
