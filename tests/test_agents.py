from pathlib import Path

import pytest

from app.agent_service import AgentFrameworkService
from dikson_li.agents import (
    AgentCorruptionError,
    AgentDecisionCreate,
    AgentId,
    AgentPolicyError,
    AgentProposalCreate,
    AgentRegistry,
    AgentRunCreate,
    AgentTool,
    DuplicateDecisionError,
    JsonlAgentRepository,
    ProposalType,
)
from dikson_li.memory import JsonlMemoryStore


def test_builtin_registry_has_seven_isolated_roles_and_policies() -> None:
    registry = AgentRegistry()
    definitions = registry.list()

    assert [definition.id for definition in definitions] == list(AgentId)
    assert len({definition.memory_tag for definition in definitions}) == 7
    assert all(AgentTool.AGENT_MEMORY_PROPOSE in item.tools for item in definitions)
    assert all(ProposalType.AGENT_MEMORY in item.proposal_types for item in definitions)

    registry.authorize_tools(AgentId.RESEARCH, {AgentTool.SEMANTIC_SEARCH})
    with pytest.raises(AgentPolicyError, match="wiki_propose"):
        registry.authorize_tools(AgentId.RESEARCH, {AgentTool.WIKI_PROPOSE})
    with pytest.raises(AgentPolicyError, match="code_change"):
        registry.authorize_proposal(AgentId.RESEARCH, ProposalType.CODE_CHANGE)


def test_repository_is_append_only_and_reports_corruption(tmp_path: Path) -> None:
    repository = JsonlAgentRepository(tmp_path)
    run = repository.add_run(
        "project",
        AgentId.REVIEW,
        AgentRunCreate(objective="Review the change", requested_tools={"code_read"}),
    )
    repeated_run = repository.add_run(
        "project",
        AgentId.REVIEW,
        AgentRunCreate(
            objective="Review the change",
            requested_tools={"code_read"},
            idempotency_key="review-1",
        ),
    )
    same_run = repository.add_run(
        "project",
        AgentId.REVIEW,
        AgentRunCreate(
            objective="A repeated request",
            idempotency_key="review-1",
        ),
    )
    assert same_run.id == repeated_run.id
    proposal = repository.add_proposal(
        "project",
        AgentId.REVIEW,
        run.id,
        AgentProposalCreate(type="review", title="Review result", summary="No blocking findings"),
    )
    decision = repository.decide(
        "project",
        proposal.id,
        AgentDecisionCreate(outcome="approved", reviewer="lead", reason="verified"),
    )

    assert repository.runs() == [run, repeated_run]
    assert repository.proposals() == [proposal]
    assert repository.decisions() == [decision]
    with pytest.raises(DuplicateDecisionError):
        repository.decide(
            "project",
            proposal.id,
            AgentDecisionCreate(outcome="rejected", reviewer="lead", reason="retry"),
        )

    repository.runs_path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(AgentCorruptionError, match="line 1"):
        repository.runs()


def test_approved_agent_memory_uses_canonical_memory_core(tmp_path: Path) -> None:
    project_id = "agent-memory"
    service = AgentFrameworkService(tmp_path, project_id)
    run = service.start_run(
        AgentId.RESEARCH,
        AgentRunCreate(
            objective="Investigate retrieval",
            requested_tools={AgentTool.SEMANTIC_SEARCH},
        ),
    )
    proposal = service.submit_proposal(
        AgentId.RESEARCH,
        run.id,
        AgentProposalCreate(
            type=ProposalType.AGENT_MEMORY,
            title="Remember evidence",
            summary="Store an approved research observation",
            payload={
                "content": "Cosine ranking is deterministic in local mode",
                "kind": "fact",
                "tags": ["retrieval", "agent:memory"],
            },
        ),
    )

    with pytest.raises(PermissionError):
        service.commit_agent_memory(proposal.id)
    service.decide(
        proposal.id,
        AgentDecisionCreate(outcome="approved", reviewer="architect", reason="confirmed"),
    )
    committed = service.commit_agent_memory(proposal.id)
    repeated = service.commit_agent_memory(proposal.id)

    assert repeated.id == committed.id
    assert "agent:research" in committed.tags
    assert "agent:memory" not in committed.tags
    assert committed.metadata["agent_proposal_id"] == proposal.id
    assert committed.metadata["approved_by"] == "architect"
    canonical_store = JsonlMemoryStore(tmp_path / "projects")
    canonical_store.append(
        project_id=project_id,
        content="Unscoped tag must not enter agent memory",
        tags=["agent:research"],
    )
    assert [record.id for record in service.agent_memory(AgentId.RESEARCH)] == [committed.id]
    canonical = canonical_store.get(project_id, committed.id)
    assert canonical == committed
