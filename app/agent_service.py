from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from dikson_li.agents import (
    AgentDecision,
    AgentDecisionCreate,
    AgentDefinition,
    AgentId,
    AgentProposal,
    AgentProposalCreate,
    AgentProposalView,
    AgentRegistry,
    AgentRun,
    AgentRunCreate,
    JsonlAgentRepository,
    ProposalStatus,
    ProposalType,
)
from dikson_li.memory import JsonlMemoryStore, MemoryCreate, MemoryRecord


class AgentFrameworkService:
    """Applies agent policy and binds audit records to canonical project data."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.project_id = project_id
        self.project_root = data_dir / "projects" / project_id
        self.registry = AgentRegistry()
        self.repository = JsonlAgentRepository(self.project_root / "agents")
        self.memory = JsonlMemoryStore(data_dir / "projects", legacy_root=data_dir / "memory")

    def agents(self) -> list[AgentDefinition]:
        return self.registry.list()

    def agent(self, agent_id: AgentId) -> AgentDefinition:
        return self.registry.get(agent_id)

    def start_run(self, agent_id: AgentId, payload: AgentRunCreate) -> AgentRun:
        self.registry.authorize_tools(agent_id, payload.requested_tools)
        return self.repository.add_run(self.project_id, agent_id, payload)

    def runs(self, agent_id: AgentId | None = None) -> list[AgentRun]:
        runs = self.repository.runs()
        if agent_id is not None:
            runs = [run for run in runs if run.agent_id == agent_id]
        return runs

    def submit_proposal(
        self,
        agent_id: AgentId,
        run_id: str,
        payload: AgentProposalCreate,
    ) -> AgentProposal:
        self.registry.authorize_proposal(agent_id, payload.type)
        if payload.type == ProposalType.AGENT_MEMORY:
            MemoryCreate.model_validate(payload.payload)
        return self.repository.add_proposal(self.project_id, agent_id, run_id, payload)

    def proposals(
        self,
        *,
        agent_id: AgentId | None = None,
        status: ProposalStatus | None = None,
    ) -> list[AgentProposalView]:
        decision_by_proposal = {
            decision.proposal_id: decision for decision in self.repository.decisions()
        }
        views = []
        for proposal in self.repository.proposals():
            if agent_id is not None and proposal.agent_id != agent_id:
                continue
            decision = decision_by_proposal.get(proposal.id)
            current_status = decision.outcome if decision else ProposalStatus.PENDING
            if status is not None and current_status != status:
                continue
            views.append(
                AgentProposalView(
                    proposal=proposal,
                    status=current_status,
                    decision=decision,
                )
            )
        return views

    def decide(self, proposal_id: str, payload: AgentDecisionCreate) -> AgentDecision:
        return self.repository.decide(self.project_id, proposal_id, payload)

    def proposal(self, proposal_id: str) -> AgentProposalView:
        return self._proposal_view(proposal_id)

    def commit_agent_memory(self, proposal_id: str) -> MemoryRecord:
        with FileLock(str(self.project_root / "agents" / ".memory-commit.lock")):
            existing = self._memory_for_proposal(proposal_id)
            if existing is not None:
                return existing
            view = self._proposal_view(proposal_id)
            if view.status != ProposalStatus.APPROVED:
                raise PermissionError("agent memory proposal is not approved")
            if view.proposal.type != ProposalType.AGENT_MEMORY:
                raise ValueError("proposal is not agent memory")
            definition = self.registry.get(view.proposal.agent_id)
            create = MemoryCreate.model_validate(view.proposal.payload)
            domain_tags = {tag for tag in create.tags if not tag.startswith("agent:")}
            metadata = {
                **create.metadata,
                "agent_id": view.proposal.agent_id.value,
                "agent_proposal_id": proposal_id,
                "approved_by": view.decision.reviewer if view.decision else None,
            }
            return self.memory.append(
                project_id=self.project_id,
                payload=create.model_copy(
                    update={
                        "tags": domain_tags | {definition.memory_tag},
                        "metadata": metadata,
                    }
                ),
            )

    def agent_memory(self, agent_id: AgentId) -> list[MemoryRecord]:
        memory_tag = self.registry.get(agent_id).memory_tag
        return [
            record
            for record in self.memory.list(self.project_id, limit=100_000)
            if memory_tag in record.tags and record.metadata.get("agent_id") == agent_id.value
        ]

    def _proposal_view(self, proposal_id: str) -> AgentProposalView:
        for view in self.proposals():
            if view.proposal.id == proposal_id:
                return view
        raise KeyError(proposal_id)

    def _memory_for_proposal(self, proposal_id: str) -> MemoryRecord | None:
        for record in self.memory.list(self.project_id, limit=100_000):
            if record.metadata.get("agent_proposal_id") == proposal_id:
                return record
        return None
