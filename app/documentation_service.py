from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent_service import AgentFrameworkService
from dikson_li.agents import (
    AgentId,
    AgentProposalCreate,
    AgentRunCreate,
    AgentTool,
    ProposalType,
)
from dikson_li.documentation import (
    DocumentationGenerateCreate,
    DocumentationGenerator,
    DocumentationSnapshot,
    JsonlDocumentationRepository,
    snapshot_id,
)


class DocumentationService:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        self.agents = AgentFrameworkService(data_dir, project_id)
        self.repository = JsonlDocumentationRepository(
            data_dir / "projects" / project_id / "documentation"
        )
        self.generator = DocumentationGenerator()

    def generate(
        self,
        payload: DocumentationGenerateCreate,
        openapi: dict[str, Any],
    ) -> DocumentationSnapshot:
        manifests = [item.model_dump(mode="json") for item in self.agents.agents()]
        digest, artifacts = self.generator.render(payload.title, openapi, manifests)
        key = payload.idempotency_key or digest
        identifier = snapshot_id(self.project_id, key)
        try:
            return self.repository.get(identifier)
        except KeyError:
            pass
        run = self.agents.start_run(
            AgentId.DOCUMENTATION,
            AgentRunCreate(
                objective=f"Generate documentation snapshot {identifier}",
                requested_tools={AgentTool.DOCUMENTATION_PROPOSE},
                idempotency_key=f"documentation:{identifier}:run",
            ),
        )
        proposal = self.agents.submit_proposal(
            AgentId.DOCUMENTATION,
            run.id,
            AgentProposalCreate(
                type=ProposalType.DOCUMENTATION,
                title=f"Generated documentation: {payload.title}",
                summary="Review generated API reference and agent catalog.",
                payload={
                    "snapshot_id": identifier,
                    "source_digest": digest,
                    "artifacts": [
                        {"path": item.path, "sha256": item.sha256} for item in artifacts
                    ],
                },
                idempotency_key=f"documentation:{identifier}:proposal",
            ),
        )
        return self.repository.add(
            DocumentationSnapshot(
                id=identifier,
                project_id=self.project_id,
                title=payload.title,
                source_digest=digest,
                idempotency_key=payload.idempotency_key,
                artifacts=artifacts,
                proposal_id=proposal.id,
                created_at=datetime.now(timezone.utc),
            )
        )
