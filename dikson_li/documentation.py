from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
from typing import Any

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentationGenerateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="DIKSON AI System", min_length=1, max_length=300)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("title", "idempotency_key")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class DocumentationArtifact(BaseModel):
    path: str
    media_type: str = "text/markdown"
    content: str
    sha256: str


class DocumentationSnapshot(BaseModel):
    id: str
    project_id: str
    title: str
    source_digest: str
    idempotency_key: str | None = None
    artifacts: list[DocumentationArtifact]
    proposal_id: str
    created_at: datetime


class DocumentationStorageError(RuntimeError):
    pass


class DocumentationCorruptionError(DocumentationStorageError):
    pass


class DocumentationGenerator:
    """Pure deterministic renderer over canonical OpenAPI and agent manifests."""

    def render(
        self,
        title: str,
        openapi: dict[str, Any],
        agents: list[dict[str, Any]],
    ) -> tuple[str, list[DocumentationArtifact]]:
        source_digest = hashlib.sha256(
            _canonical_json({"openapi": openapi, "agents": agents}).encode("utf-8")
        ).hexdigest()
        artifacts = [
            self._artifact("generated/api-reference.md", self._api(title, openapi)),
            self._artifact("generated/agent-catalog.md", self._agents(title, agents)),
        ]
        return source_digest, artifacts

    @staticmethod
    def _api(title: str, schema: dict[str, Any]) -> str:
        info = schema.get("info", {})
        lines = [
            f"# {title} API Reference",
            "",
            f"Generated from OpenAPI {schema.get('openapi', 'unknown')} for API version "
            f"{info.get('version', 'unknown')}.",
            "",
        ]
        methods = {"get", "post", "put", "patch", "delete", "options", "head"}
        for path in sorted(schema.get("paths", {})):
            operations = schema["paths"][path]
            for method in sorted(methods & set(operations)):
                operation = operations[method]
                summary = operation.get("summary") or operation.get("operationId") or ""
                tags = ", ".join(operation.get("tags", [])) or "untagged"
                lines.extend(
                    [
                        f"## `{method.upper()} {path}`",
                        "",
                        summary,
                        "",
                        f"Tags: `{tags}`",
                        "",
                    ]
                )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _agents(title: str, agents: list[dict[str, Any]]) -> str:
        lines = [f"# {title} Agent Catalog", ""]
        for agent in sorted(agents, key=lambda item: item["id"]):
            lines.extend(
                [
                    f"## {agent['name']} (`{agent['id']}`)",
                    "",
                    agent["description"],
                    "",
                    "Responsibilities: "
                    + ", ".join(f"`{item}`" for item in agent["responsibilities"]),
                    "",
                    "Tools: " + ", ".join(f"`{item}`" for item in sorted(agent["tools"])),
                    "",
                    "Proposal types: "
                    + ", ".join(
                        f"`{item}`" for item in sorted(agent["proposal_types"])
                    ),
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _artifact(path: str, content: str) -> DocumentationArtifact:
        return DocumentationArtifact(
            path=path,
            content=content,
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )


class JsonlDocumentationRepository:
    def __init__(self, root: Path, *, lock_timeout: float = 10) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / "snapshots.jsonl"
        self.lock_timeout = lock_timeout

    def add(self, snapshot: DocumentationSnapshot) -> DocumentationSnapshot:
        with self._lock():
            existing = self._read()
            duplicate = next((item for item in existing if item.id == snapshot.id), None)
            if duplicate is not None:
                return duplicate
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(snapshot.model_dump_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise DocumentationStorageError("Could not append snapshot") from exc
        return snapshot

    def list(self) -> list[DocumentationSnapshot]:
        with self._lock():
            return self._read()

    def get(self, snapshot_id: str) -> DocumentationSnapshot:
        for snapshot in self.list():
            if snapshot.id == snapshot_id:
                return snapshot
        raise KeyError(snapshot_id)

    def _read(self) -> list[DocumentationSnapshot]:
        if not self.path.exists():
            return []
        try:
            rows = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise DocumentationStorageError("Could not read snapshots") from exc
        result = []
        for number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                result.append(DocumentationSnapshot.model_validate_json(row))
            except ValueError as exc:
                raise DocumentationCorruptionError(
                    f"Invalid snapshots.jsonl row at line {number}"
                ) from exc
        return result

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".documentation.lock"), timeout=self.lock_timeout)


def snapshot_id(project_id: str, key: str) -> str:
    return hashlib.sha256(f"{project_id}\0{key}".encode()).hexdigest()[:32]


def _canonical_json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
