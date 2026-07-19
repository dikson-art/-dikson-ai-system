from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Protocol
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GitChangeSet(BaseModel):
    """Validated, reviewable input for one isolated Git commit."""

    model_config = ConfigDict(extra="forbid")

    branch: str = Field(min_length=1, max_length=200)
    commit_message: str = Field(min_length=1, max_length=500)
    patch: str = Field(min_length=1, max_length=2_000_000)
    base_ref: str = Field(default="HEAD", min_length=1, max_length=300)
    expected_head: str | None = Field(default=None, min_length=7, max_length=64)

    @field_validator("branch", "commit_message", "base_ref", "expected_head")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("patch")
    @classmethod
    def patch_must_have_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("patch must not be blank")
        return value


class GitExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=200)

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor must not be blank")
        return normalized


class GitStatus(BaseModel):
    repository: str
    branch: str | None
    head: str
    clean: bool
    changes: list[str]


class GitDiff(BaseModel):
    repository: str
    staged: bool
    patch: str
    truncated: bool = False


class GitExecution(BaseModel):
    id: str
    project_id: str
    proposal_id: str
    actor: str
    reviewer: str
    repository: str
    branch: str
    base_ref: str
    expected_head: str | None = None
    head_before: str
    patch_sha256: str
    commit_message: str
    status: GitExecutionStatus
    created_at: datetime
    completed_at: datetime | None = None
    commit_sha: str | None = None
    error: str | None = None


class GitAutomationError(RuntimeError):
    pass


class GitPolicyError(GitAutomationError):
    pass


class GitCommandError(GitAutomationError):
    def __init__(self, command: tuple[str, ...], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git command failed with exit code {returncode}")


class GitExecutionError(GitAutomationError):
    def __init__(self, execution: GitExecution) -> None:
        self.execution = execution
        super().__init__(execution.error or "git execution failed")


class GitStorageError(GitAutomationError):
    pass


class GitCorruptionError(GitStorageError):
    pass


class GitCommandRunner(Protocol):
    def run(
        self,
        repository: Path,
        arguments: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessGitRunner:
    """Shell-free Git CLI adapter with prompts, hooks, and signing disabled."""

    def __init__(self, hooks_dir: Path, *, timeout_seconds: int = 60) -> None:
        self.hooks_dir = hooks_dir.resolve()
        self.hooks_dir.mkdir(parents=True, exist_ok=True)
        self.safe_global_config = self.hooks_dir.parent / "safe-global.gitconfig"
        safe_config = "[core]\n\tautocrlf = true\n" if os.name == "nt" else ""
        self.safe_global_config.write_text(safe_config, encoding="utf-8")
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        repository: Path,
        arguments: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = (
            "git",
            "-c",
            f"core.hooksPath={self.hooks_dir}",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "user.name=Dikson-Li Automation",
            "-c",
            "user.email=dikson-li@localhost",
            "-C",
            str(repository),
            *arguments,
        )
        environment = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(self.safe_global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            raw_result = subprocess.run(
                command,
                input=input_text.encode("utf-8") if input_text is not None else None,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitCommandError(command, -1, str(exc)) from exc
        result = subprocess.CompletedProcess(
            args=raw_result.args,
            returncode=raw_result.returncode,
            stdout=raw_result.stdout.decode("utf-8", errors="replace"),
            stderr=raw_result.stderr.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            raise GitCommandError(command, result.returncode, result.stderr.strip())
        return result


class JsonlGitExecutionRepository:
    """Append-only execution journal; the latest row is the current view."""

    def __init__(self, root: Path, *, lock_timeout: float = 10) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "executions.jsonl"
        self.lock_timeout = lock_timeout

    def append(self, execution: GitExecution) -> GitExecution:
        with self._lock():
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(execution.model_dump_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise GitStorageError("Could not append Git execution") from exc
        return execution

    def list(self) -> list[GitExecution]:
        with self._lock():
            records = self._read()
        latest: dict[str, GitExecution] = {}
        order: list[str] = []
        for record in records:
            if record.id not in latest:
                order.append(record.id)
            latest[record.id] = record
        return [latest[execution_id] for execution_id in order]

    def for_proposal(self, proposal_id: str) -> GitExecution | None:
        return next(
            (item for item in self.list() if item.proposal_id == proposal_id),
            None,
        )

    def _read(self) -> list[GitExecution]:
        if not self.path.exists():
            return []
        try:
            rows = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise GitStorageError("Could not read Git executions") from exc
        records = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                records.append(GitExecution.model_validate_json(row))
            except ValueError as exc:
                raise GitCorruptionError(
                    f"Invalid executions.jsonl row at line {line_number}"
                ) from exc
        return records

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".executions.lock"), timeout=self.lock_timeout)


class GitAutomationCore:
    """Canonical Git operations with a narrow, deny-by-default command surface."""

    def __init__(
        self,
        repository: Path,
        audit_root: Path,
        *,
        runner: GitCommandRunner | None = None,
        diff_limit: int = 1_000_000,
    ) -> None:
        self.repository = repository.resolve()
        self.audit_root = audit_root.resolve()
        self.audit_root.mkdir(parents=True, exist_ok=True)
        self.worktrees_root = self.audit_root / "worktrees"
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        self.runner = runner or SubprocessGitRunner(self.audit_root / "hooks-disabled")
        self.executions = JsonlGitExecutionRepository(self.audit_root)
        self.diff_limit = diff_limit

    def status(self) -> GitStatus:
        self._ensure_repository()
        head = self._output(self.repository, ["rev-parse", "HEAD"])
        branch_result = self.runner.run(
            self.repository,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            check=False,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        changes = self._output(
            self.repository,
            ["status", "--porcelain=v1", "--untracked-files=all"],
        ).splitlines()
        return GitStatus(
            repository=str(self.repository),
            branch=branch,
            head=head,
            clean=not changes,
            changes=changes,
        )

    def diff(self, *, staged: bool = False) -> GitDiff:
        self._ensure_repository()
        arguments = ["diff", "--no-ext-diff", "--no-color"]
        if staged:
            arguments.append("--cached")
        patch = self._output(self.repository, arguments, strip=False)
        truncated = len(patch) > self.diff_limit
        if truncated:
            patch = patch[: self.diff_limit]
        return GitDiff(
            repository=str(self.repository),
            staged=staged,
            patch=patch,
            truncated=truncated,
        )

    def execute(
        self,
        project_id: str,
        proposal_id: str,
        actor: str,
        reviewer: str,
        change: GitChangeSet,
    ) -> GitExecution:
        with FileLock(str(self.audit_root / ".automation.lock"), timeout=30):
            existing = self.executions.for_proposal(proposal_id)
            if existing is not None:
                if existing.status == GitExecutionStatus.FAILED:
                    raise GitExecutionError(existing)
                return existing
            self._ensure_repository()
            self._validate_branch(change.branch)
            head_before = self._output(
                self.repository,
                ["rev-parse", "--verify", "--end-of-options", f"{change.base_ref}^{{commit}}"],
            )
            if change.expected_head and head_before != change.expected_head:
                raise GitPolicyError("base ref does not match expected_head")
            branch_ref = f"refs/heads/{change.branch}"
            branch_exists = self.runner.run(
                self.repository,
                ["show-ref", "--verify", "--quiet", branch_ref],
                check=False,
            )
            if branch_exists.returncode == 0:
                raise GitPolicyError("target branch already exists")
            if branch_exists.returncode not in {0, 1}:
                raise GitPolicyError("could not verify target branch")
            execution = GitExecution(
                id=uuid4().hex,
                project_id=project_id,
                proposal_id=proposal_id,
                actor=actor,
                reviewer=reviewer,
                repository=str(self.repository),
                branch=change.branch,
                base_ref=change.base_ref,
                expected_head=change.expected_head,
                head_before=head_before,
                patch_sha256=hashlib.sha256(change.patch.encode("utf-8")).hexdigest(),
                commit_message=change.commit_message,
                status=GitExecutionStatus.RUNNING,
                created_at=datetime.now(timezone.utc),
            )
            self.executions.append(execution)
            return self._execute_locked(execution, change)

    def _execute_locked(self, execution: GitExecution, change: GitChangeSet) -> GitExecution:
        worktree = self.worktrees_root / execution.id
        branch_created = False
        try:
            self.runner.run(
                self.repository,
                ["worktree", "add", "--detach", str(worktree), execution.head_before],
            )
            self.runner.run(worktree, ["switch", "-c", change.branch])
            branch_created = True
            self.runner.run(
                worktree,
                ["apply", "--check", "--index", "-"],
                input_text=change.patch,
            )
            self.runner.run(
                worktree,
                ["apply", "--index", "-"],
                input_text=change.patch,
            )
            self.runner.run(
                worktree,
                ["commit", "--no-gpg-sign", "-m", change.commit_message],
            )
            commit_sha = self._output(worktree, ["rev-parse", "HEAD"])
            completed = execution.model_copy(
                update={
                    "status": GitExecutionStatus.SUCCEEDED,
                    "completed_at": datetime.now(timezone.utc),
                    "commit_sha": commit_sha,
                }
            )
            self.executions.append(completed)
            return completed
        except GitAutomationError as exc:
            failed = execution.model_copy(
                update={
                    "status": GitExecutionStatus.FAILED,
                    "completed_at": datetime.now(timezone.utc),
                    "error": self._safe_error(exc),
                }
            )
            self.executions.append(failed)
            raise GitExecutionError(failed) from exc
        finally:
            self.runner.run(
                self.repository,
                ["worktree", "remove", "--force", str(worktree)],
                check=False,
            )
            current = self.executions.for_proposal(execution.proposal_id)
            if (
                branch_created
                and current is not None
                and current.status == GitExecutionStatus.FAILED
            ):
                self.runner.run(
                    self.repository,
                    ["branch", "-D", change.branch],
                    check=False,
                )

    def _ensure_repository(self) -> None:
        if not self.repository.is_dir():
            raise GitPolicyError("configured repository does not exist")
        root = Path(self._output(self.repository, ["rev-parse", "--show-toplevel"])).resolve()
        if root != self.repository:
            raise GitPolicyError("configured path must be the repository root")
        filters = self.runner.run(
            self.repository,
            [
                "config",
                "--local",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process|required)$",
            ],
            check=False,
        )
        if filters.returncode == 0 and filters.stdout.strip():
            raise GitPolicyError("repository content filters are not allowed")
        if filters.returncode not in {0, 1}:
            raise GitPolicyError("could not inspect repository content filters")

    def _validate_branch(self, branch: str) -> None:
        result = self.runner.run(
            self.repository,
            ["check-ref-format", "--branch", branch],
            check=False,
        )
        if (
            result.returncode != 0
            or not branch.startswith("agent/")
            or branch in {"agent/main", "agent/master"}
        ):
            raise GitPolicyError("invalid or protected target branch")

    def _output(self, repository: Path, arguments: list[str], *, strip: bool = True) -> str:
        output = self.runner.run(repository, arguments).stdout
        return output.strip() if strip else output

    @staticmethod
    def _safe_error(error: GitAutomationError) -> str:
        if isinstance(error, GitCommandError):
            return f"Git command failed with exit code {error.returncode}"
        return str(error)[:500]


def ensure_json_serializable(value: object) -> None:
    """Small public validation helper for adapters accepting JSON payloads."""
    json.dumps(value, ensure_ascii=False)
