from pathlib import Path
import subprocess

import pytest

from dikson_li.git_automation import (
    GitAutomationCore,
    GitChangeSet,
    GitCorruptionError,
    GitExecutionError,
    GitExecutionStatus,
    GitPolicyError,
)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def initialized_repository(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    (path / "example.txt").write_text("before\n", encoding="utf-8")
    git(path, "add", "example.txt")
    git(path, "commit", "-m", "Initial")
    return path


def patch_for(repository: Path, content: str) -> str:
    target = repository / "example.txt"
    original = target.read_text(encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    patch = git(repository, "diff", "--", "example.txt") + "\n"
    target.write_text(original, encoding="utf-8")
    return patch


def test_status_diff_and_isolated_approved_commit(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "repo")
    core = GitAutomationCore(repository, tmp_path / "audit")
    head = git(repository, "rev-parse", "HEAD")
    patch = patch_for(repository, "after\n")

    assert core.status().clean is True
    assert core.diff().patch == ""
    execution = core.execute(
        "project",
        "proposal-1",
        "operator",
        "reviewer",
        GitChangeSet(
            branch="agent/change",
            commit_message="Apply approved change",
            patch=patch,
            expected_head=head,
        ),
    )

    assert execution.status == GitExecutionStatus.SUCCEEDED
    assert git(repository, "branch", "--show-current") == "main"
    assert git(repository, "show", "agent/change:example.txt") == "after"
    assert core.execute(
        "project",
        "proposal-1",
        "operator",
        "reviewer",
        GitChangeSet(
            branch="different",
            commit_message="Ignored duplicate",
            patch=patch,
        ),
    ) == execution
    assert not any(core.worktrees_root.iterdir())


def test_rejects_protected_branch_stale_head_and_invalid_patch(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "repo")
    core = GitAutomationCore(repository, tmp_path / "audit")
    patch = patch_for(repository, "after\n")

    with pytest.raises(GitPolicyError, match="protected"):
        core.execute(
            "project",
            "protected",
            "operator",
            "reviewer",
            GitChangeSet(branch="main", commit_message="No", patch=patch),
        )
    with pytest.raises(GitPolicyError, match="protected"):
        core.execute(
            "project",
            "unscoped",
            "operator",
            "reviewer",
            GitChangeSet(branch="feature", commit_message="No", patch=patch),
        )
    with pytest.raises(GitPolicyError, match="expected_head"):
        core.execute(
            "project",
            "stale",
            "operator",
            "reviewer",
            GitChangeSet(
                branch="agent/stale",
                commit_message="No",
                patch=patch,
                expected_head="0" * 40,
            ),
        )
    with pytest.raises(GitExecutionError) as error:
        core.execute(
            "project",
            "broken",
            "operator",
            "reviewer",
            GitChangeSet(
                branch="agent/broken",
                commit_message="No",
                patch="not a unified patch\n",
            ),
        )
    assert error.value.execution.status == GitExecutionStatus.FAILED
    assert git(repository, "branch", "--list", "agent/broken") == ""


def test_execution_journal_detects_corruption(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "repo")
    core = GitAutomationCore(repository, tmp_path / "audit")
    core.executions.path.write_text("{broken}\n", encoding="utf-8")

    with pytest.raises(GitCorruptionError, match="line 1"):
        core.executions.list()


def test_repository_content_filters_are_denied(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "repo")
    git(repository, "config", "filter.unsafe.smudge", "unsafe-command")
    core = GitAutomationCore(repository, tmp_path / "audit")

    with pytest.raises(GitPolicyError, match="content filters"):
        core.status()
