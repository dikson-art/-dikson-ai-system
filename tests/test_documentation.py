from pathlib import Path

import pytest

from dikson_li.documentation import (
    DocumentationArtifact,
    DocumentationCorruptionError,
    DocumentationGenerator,
    DocumentationSnapshot,
    JsonlDocumentationRepository,
)


def test_generator_is_deterministic_and_sorted() -> None:
    schema = {
        "openapi": "3.1.0",
        "info": {"version": "1.0"},
        "paths": {
            "/z": {"post": {"summary": "Create Z", "tags": ["z"]}},
            "/a": {"get": {"summary": "Read A", "tags": ["a"]}},
        },
    }
    agents = [
        {
            "id": "wiki",
            "name": "Wiki Agent",
            "description": "Docs",
            "responsibilities": ["pages"],
            "tools": ["wiki_read"],
            "proposal_types": ["wiki_change"],
        }
    ]
    generator = DocumentationGenerator()

    first = generator.render("System", schema, agents)
    second = generator.render("System", schema, agents)

    assert first == second
    assert first[1][0].content.index("GET /a") < first[1][0].content.index("POST /z")
    assert first[1][1].sha256


def test_repository_is_idempotent_and_detects_corruption(tmp_path: Path) -> None:
    repository = JsonlDocumentationRepository(tmp_path)
    snapshot = DocumentationSnapshot(
        id="snapshot",
        project_id="project",
        title="Docs",
        source_digest="a" * 64,
        artifacts=[
            DocumentationArtifact(path="generated/a.md", content="# A\n", sha256="b" * 64)
        ],
        proposal_id="proposal",
        created_at="2026-01-01T00:00:00Z",
    )
    assert repository.add(snapshot) == snapshot
    assert repository.add(snapshot) == snapshot
    assert repository.list() == [snapshot]
    repository.path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(DocumentationCorruptionError, match="line 1"):
        repository.list()
