from pathlib import Path

from app.agent_service import AgentFrameworkService
from dikson_li.agents import AgentId, ProposalStatus, ProposalType
from dikson_li.git_automation import (
    GitAutomationCore,
    GitChangeSet,
    GitDiff,
    GitExecution,
    GitExecutionCreate,
    GitStatus,
)


class GitAutomationService:
    """Binds approved Coding Agent proposals to the canonical Git core."""

    def __init__(
        self,
        data_dir: Path,
        repositories_dir: Path,
        project_id: str,
    ) -> None:
        self.project_id = project_id
        self.agents = AgentFrameworkService(data_dir, project_id)
        self.core = GitAutomationCore(
            repositories_dir / project_id,
            data_dir / "projects" / project_id / "git",
        )

    def status(self) -> GitStatus:
        return self.core.status()

    def diff(self, *, staged: bool = False) -> GitDiff:
        return self.core.diff(staged=staged)

    def executions(self) -> list[GitExecution]:
        return self.core.executions.list()

    def execute(self, proposal_id: str, payload: GitExecutionCreate) -> GitExecution:
        view = self.agents.proposal(proposal_id)
        if view.status != ProposalStatus.APPROVED or view.decision is None:
            raise PermissionError("code change proposal is not approved")
        proposal = view.proposal
        if proposal.agent_id != AgentId.CODING or proposal.type != ProposalType.CODE_CHANGE:
            raise ValueError("proposal is not a Coding Agent code change")
        change = GitChangeSet.model_validate(proposal.payload)
        return self.core.execute(
            self.project_id,
            proposal.id,
            payload.actor,
            view.decision.reviewer,
            change,
        )
