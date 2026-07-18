from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
import hashlib
import math
import re
import unicodedata
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class SearchEntityType(StrEnum):
    MEMORY = "memory"
    WIKI_PAGE = "wiki_page"
    SOURCE = "source"
    GRAPH_NODE = "graph_node"


class SearchDocument(BaseModel):
    """Read-only projection of a canonical entity for vector search."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    entity_type: SearchEntityType
    entity_id: str
    title: str
    text: str
    tags: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    id: str
    entity_type: SearchEntityType
    entity_id: str
    title: str
    text: str
    score: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_id: str | None = None
    filename: str | None = None
    chunk: int | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]


class EmbeddingModel(Protocol):
    def embed(self, texts: Iterable[str]) -> list[list[float]]: ...


class LocalHashEmbeddingModel:
    """Deterministic multilingual feature hashing with no external runtime."""

    _words = re.compile(r"[^\W_]+", flags=re.UNICODE)

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions < 32:
            raise ValueError("dimensions must be at least 32")
        self.dimensions = dimensions

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokenize(text)
        features: list[tuple[str, float]] = []
        for token in tokens:
            features.append((f"w:{token}", 2.0))
            if len(token) >= 5:
                features.append((f"p:{token[:5]}", 0.6))
            padded = f"^{token}$"
            features.extend(
                (f"c:{padded[index : index + 3]}", 0.25) for index in range(max(0, len(padded) - 2))
            )
        features.extend((f"b:{left}:{right}", 1.25) for left, right in zip(tokens, tokens[1:]))
        for feature, weight in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8"), digest_size=8, usedforsecurity=False
            ).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            vector[index] += weight if (value >> 32) & 1 else -weight
        norm = math.sqrt(sum(value * value for value in vector))
        return vector if norm == 0 else [value / norm for value in vector]

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        return cls._words.findall(normalized)


class SemanticSearchEngine:
    """Ranks projected documents by vector similarity and graph context."""

    def __init__(self, embedding_model: EmbeddingModel | None = None) -> None:
        self.embedding_model = embedding_model or LocalHashEmbeddingModel()

    def search(
        self,
        query: str,
        documents: Iterable[SearchDocument],
        *,
        relations: Mapping[str, set[str]] | None = None,
        limit: int = 10,
        min_score: float = 0.05,
    ) -> list[SearchHit]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be blank")
        if limit < 1:
            raise ValueError("limit must be positive")
        corpus = list(documents)
        if not corpus:
            return []
        searchable_text = [self._searchable_text(document) for document in corpus]
        vectors = self.embedding_model.embed([normalized_query, *searchable_text])
        query_vector, document_vectors = vectors[0], vectors[1:]
        base_scores = {
            document.id: max(0.0, self._dot(query_vector, vector))
            for document, vector in zip(corpus, document_vectors)
        }
        relation_map = relations or {}
        hits = []
        query_terms = set(LocalHashEmbeddingModel._tokenize(normalized_query))
        query_prefixes = {term[:5] for term in query_terms if len(term) >= 5}
        for document in corpus:
            score = base_scores[document.id]
            neighbor_score = max(
                (
                    base_scores.get(neighbor_id, 0.0)
                    for neighbor_id in relation_map.get(document.id, set())
                ),
                default=0.0,
            )
            score += neighbor_score * 0.12
            title_terms = set(LocalHashEmbeddingModel._tokenize(document.title))
            document_terms = set(LocalHashEmbeddingModel._tokenize(self._searchable_text(document)))
            if query_terms:
                score += len(query_terms & document_terms) / len(query_terms) * 0.25
            document_prefixes = {term[:5] for term in document_terms if len(term) >= 5}
            if query_prefixes:
                score += len(query_prefixes & document_prefixes) / len(query_prefixes) * 0.15
            if query_terms and query_terms <= title_terms:
                score += 0.08
            if query_terms & {tag.casefold() for tag in document.tags}:
                score += 0.05
            score = min(1.0, score)
            if score >= min_score:
                hits.append(self._hit(document, score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.entity_type, hit.id))[:limit]

    @staticmethod
    def _searchable_text(document: SearchDocument) -> str:
        tags = " ".join(sorted(document.tags))
        return f"{document.title}\n{document.title}\n{tags}\n{document.text}"

    @staticmethod
    def _dot(left: list[float], right: list[float]) -> float:
        return sum(first * second for first, second in zip(left, right))

    @staticmethod
    def _hit(document: SearchDocument, score: float) -> SearchHit:
        metadata = dict(document.metadata)
        return SearchHit(
            id=document.id,
            entity_type=document.entity_type,
            entity_id=document.entity_id,
            title=document.title,
            text=document.text,
            score=round(score, 6),
            metadata=metadata,
            source_id=metadata.get("source_id"),
            filename=metadata.get("filename"),
            chunk=metadata.get("chunk"),
        )
