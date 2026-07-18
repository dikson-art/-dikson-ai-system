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


class AgentId(StrEnum):
    RESEARCH = "research"
    PLANNING = "planning"
    MEMORY = "memory"
    WIKI = "wiki"
    CODING = "coding"
    REVIEW = "review"
    DOCUMENTATION = "documentation"


class AgentTool(StrEnum):
    SEMANTIC_SEARCH = "semantic_search"
    MEMORY_READ = "memory_read"
    MEMORY_PROPOSE = "memory_propose"
    WIKI_READ = "wiki_read"
    WIKI_PROPOSE = "wiki_propose"
    GRAPH_READ = "graph_read"
    SOURCE_READ = "source_read"
    PLAN_PROPOSE = "plan_propose"
    CODE_READ = "code_read"
    CODE_PROPOSE = "code_propose"
    GIT_READ = "git_read"
    REVIEW_PROPOSE = "review_propose"
    DOCUMENTATION_PROPOSE = "documentation_propose"
    AGENT_MEMORY_PROPOSE = "agent_memory_propose"


class ProposalType(StrEnum):
    RESEARCH_REPORT = "research_report"
    PLAN = "plan"
    MEMORY_CHANGE = "memory_change"
    WIKI_CHANGE = "wiki_change"
    CODE_CHANGE = "code_change"
    REVIEW = "review"
    DOCUMENTATION = "documentation"
    AGENT_MEMORY = "agent_memory"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: AgentId
    name: str
    description: str
    responsibilities: tuple[str, ...]
    tools: frozenset[AgentTool]
    proposal_types: frozenset[ProposalType]
    memory_tag: str


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=4_000)
    requested_tools: set[AgentTool] = Field(default_factory=set)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("objective must not be blank")
        return normalized

    @field_validator("context")
    @classmethod
    def context_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_json(value, "context")
        return value


class AgentRun(BaseModel):
    id: str
    project_id: str
    agent_id: AgentId
    objective: str
    requested_tools: set[AgentTool]
    context: dict[str, Any]
    created_at: datetime


class AgentProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ProposalType
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "summary")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("payload")
    @classmethod
    def payload_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_json(value, "payload")
        return value


class AgentProposal(AgentProposalCreate):
    id: str
    project_id: str
    run_id: str
    agent_id: AgentId
    created_at: datetime


class AgentDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: ProposalStatus
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("outcome")
    @classmethod
    def outcome_must_be_final(cls, value: ProposalStatus) -> ProposalStatus:
        if value == ProposalStatus.PENDING:
            raise ValueError("decision outcome must be approved or rejected")
        return value

    @field_validator("reviewer", "reason")
    @classmethod
    def normalize_decision_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class AgentDecision(AgentDecisionCreate):
    id: str
    project_id: str
    proposal_id: str
    decided_at: datetime


class AgentProposalView(BaseModel):
    proposal: AgentProposal
    status: ProposalStatus
    decision: AgentDecision | None = None


class AgentPolicyError(ValueError):
    pass


class DuplicateDecisionError(ValueError):
    pass


class AgentStorageError(RuntimeError):
    pass


class AgentCorruptionError(AgentStorageError):
    pass


class AgentRegistry:
    def __init__(self, definitions: tuple[AgentDefinition, ...] | None = None) -> None:
        selected = definitions or BUILTIN_AGENTS
        self._definitions = {definition.id: definition for definition in selected}
        if len(self._definitions) != len(selected):
            raise ValueError("agent ids must be unique")

    def list(self) -> list[AgentDefinition]:
        return [
            self._definitions[agent_id] for agent_id in AgentId if agent_id in self._definitions
        ]

    def get(self, agent_id: AgentId) -> AgentDefinition:
        try:
            return self._definitions[agent_id]
        except KeyError as exc:
            raise KeyError(agent_id) from exc

    def authorize_tools(self, agent_id: AgentId, requested: set[AgentTool]) -> None:
        forbidden = requested - set(self.get(agent_id).tools)
        if forbidden:
            names = ", ".join(sorted(tool.value for tool in forbidden))
            raise AgentPolicyError(f"tools not allowed for {agent_id.value}: {names}")

    def authorize_proposal(self, agent_id: AgentId, proposal_type: ProposalType) -> None:
        if proposal_type not in self.get(agent_id).proposal_types:
            raise AgentPolicyError(
                f"proposal type {proposal_type.value} is not allowed for {agent_id.value}"
            )


class JsonlAgentRepository:
    """Append-only audit repository for runs, proposals, and human decisions."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.root / "runs.jsonl"
        self.proposals_path = self.root / "proposals.jsonl"
        self.decisions_path = self.root / "decisions.jsonl"
        self.lock_timeout = lock_timeout

    def add_run(self, project_id: str, agent_id: AgentId, payload: AgentRunCreate) -> AgentRun:
        run = AgentRun(
            id=uuid4().hex,
            project_id=project_id,
            agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
            **payload.model_dump(),
        )
        with self._lock():
            self._append(self.runs_path, run.model_dump_json())
        return run

    def runs(self) -> list[AgentRun]:
        with self._lock():
            return self._read_rows(self.runs_path, AgentRun)

    def add_proposal(
        self,
        project_id: str,
        agent_id: AgentId,
        run_id: str,
        payload: AgentProposalCreate,
    ) -> AgentProposal:
        with self._lock():
            run = self._find(self._read_rows(self.runs_path, AgentRun), run_id)
            if run.agent_id != agent_id:
                raise KeyError(run_id)
            proposal = AgentProposal(
                id=uuid4().hex,
                project_id=project_id,
                run_id=run_id,
                agent_id=agent_id,
                created_at=datetime.now(timezone.utc),
                **payload.model_dump(),
            )
            self._append(self.proposals_path, proposal.model_dump_json())
        return proposal

    def proposals(self) -> list[AgentProposal]:
        with self._lock():
            return self._read_rows(self.proposals_path, AgentProposal)

    def decisions(self) -> list[AgentDecision]:
        with self._lock():
            return self._read_rows(self.decisions_path, AgentDecision)

    def decide(
        self, project_id: str, proposal_id: str, payload: AgentDecisionCreate
    ) -> AgentDecision:
        with self._lock():
            self._find(self._read_rows(self.proposals_path, AgentProposal), proposal_id)
            decisions = self._read_rows(self.decisions_path, AgentDecision)
            if any(decision.proposal_id == proposal_id for decision in decisions):
                raise DuplicateDecisionError(proposal_id)
            decision = AgentDecision(
                id=uuid4().hex,
                project_id=project_id,
                proposal_id=proposal_id,
                decided_at=datetime.now(timezone.utc),
                **payload.model_dump(),
            )
            self._append(self.decisions_path, decision.model_dump_json())
        return decision

    def _read_rows(self, path: Path, model):
        if not path.exists():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise AgentStorageError(f"Could not read {path.name}") from exc
        result = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                result.append(model.model_validate_json(row))
            except ValueError as exc:
                raise AgentCorruptionError(
                    f"Invalid {path.name} row at line {line_number}"
                ) from exc
        return result

    @staticmethod
    def _find(records, record_id: str):
        for record in records:
            if record.id == record_id:
                return record
        raise KeyError(record_id)

    def _append(self, path: Path, row: str) -> None:
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(row + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise AgentStorageError(f"Could not append {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".agents.lock"), timeout=self.lock_timeout)


def _agent(
    agent_id: AgentId,
    name: str,
    description: str,
    responsibilities: tuple[str, ...],
    tools: tuple[AgentTool, ...],
    proposal_types: tuple[ProposalType, ...],
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=name,
        description=description,
        responsibilities=responsibilities,
        tools=frozenset((*tools, AgentTool.AGENT_MEMORY_PROPOSE)),
        proposal_types=frozenset((*proposal_types, ProposalType.AGENT_MEMORY)),
        memory_tag=f"agent:{agent_id.value}",
    )


BUILTIN_AGENTS = (
    _agent(
        AgentId.RESEARCH,
        "Research Agent",
        "Collects evidence and identifies knowledge gaps.",
        ("analyze sources", "build evidence", "identify gaps"),
        (
            AgentTool.SEMANTIC_SEARCH,
            AgentTool.GRAPH_READ,
            AgentTool.SOURCE_READ,
            AgentTool.MEMORY_READ,
        ),
        (ProposalType.RESEARCH_REPORT,),
    ),
    _agent(
        AgentId.PLANNING,
        "Planning Agent",
        "Turns objectives into reviewable plans.",
        ("decompose objectives", "identify dependencies", "propose plans"),
        (
            AgentTool.SEMANTIC_SEARCH,
            AgentTool.GRAPH_READ,
            AgentTool.MEMORY_READ,
            AgentTool.PLAN_PROPOSE,
        ),
        (ProposalType.PLAN,),
    ),
    _agent(
        AgentId.MEMORY,
        "Memory Agent",
        "Reviews and proposes durable knowledge changes.",
        ("detect conflicts", "classify knowledge", "propose memory changes"),
        (AgentTool.MEMORY_READ, AgentTool.SEMANTIC_SEARCH, AgentTool.MEMORY_PROPOSE),
        (ProposalType.MEMORY_CHANGE,),
    ),
    _agent(
        AgentId.WIKI,
        "Wiki Agent",
        "Maintains structured project documentation proposals.",
        ("organize pages", "maintain references", "propose wiki changes"),
        (AgentTool.WIKI_READ, AgentTool.SEMANTIC_SEARCH, AgentTool.WIKI_PROPOSE),
        (ProposalType.WIKI_CHANGE,),
    ),
    _agent(
        AgentId.CODING,
        "Coding Agent",
        "Prepares scoped code-change proposals.",
        ("analyze code", "design changes", "propose patches"),
        (AgentTool.CODE_READ, AgentTool.GIT_READ, AgentTool.CODE_PROPOSE),
        (ProposalType.CODE_CHANGE,),
    ),
    _agent(
        AgentId.REVIEW,
        "Review Agent",
        "Reviews facts, logic, references, and code changes.",
        ("verify claims", "find defects", "assess risk"),
        (
            AgentTool.CODE_READ,
            AgentTool.GIT_READ,
            AgentTool.SEMANTIC_SEARCH,
            AgentTool.REVIEW_PROPOSE,
        ),
        (ProposalType.REVIEW,),
    ),
    _agent(
        AgentId.DOCUMENTATION,
        "Documentation Agent",
        "Prepares documentation and release-note proposals.",
        ("document behavior", "maintain architecture", "prepare release notes"),
        (AgentTool.WIKI_READ, AgentTool.CODE_READ, AgentTool.DOCUMENTATION_PROPOSE),
        (ProposalType.DOCUMENTATION,),
    ),
)


def _ensure_json(value: Any, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serializable") from exc
