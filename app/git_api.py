from fastapi import APIRouter, HTTPException
from filelock import Timeout

from app.config import settings
from app.git_service import GitAutomationService
from app.storage import load_project
from dikson_li.agents import AgentCorruptionError, AgentStorageError
from dikson_li.git_automation import (
    GitAutomationError,
    GitCommandError,
    GitCorruptionError,
    GitDiff,
    GitExecution,
    GitExecutionCreate,
    GitExecutionError,
    GitPolicyError,
    GitStatus,
    GitStorageError,
)


router = APIRouter(tags=["git"])


def service(project_id: str) -> GitAutomationService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return GitAutomationService(
        settings.dikson_data_dir,
        settings.git_repositories_dir,
        project_id,
    )


def git_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Local Git audit storage is corrupted")


@router.get("/projects/{project_id}/git/status", response_model=GitStatus)
def git_status(project_id: str) -> GitStatus:
    try:
        return service(project_id).status()
    except GitPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitCommandError as exc:
        raise HTTPException(status_code=503, detail="Git command failed") from exc
    except (GitCorruptionError, GitStorageError, Timeout) as exc:
        raise git_storage_error() from exc


@router.get("/projects/{project_id}/git/diff", response_model=GitDiff)
def git_diff(project_id: str, staged: bool = False) -> GitDiff:
    try:
        return service(project_id).diff(staged=staged)
    except GitPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (GitCorruptionError, GitStorageError, Timeout) as exc:
        raise git_storage_error() from exc
    except GitAutomationError as exc:
        raise HTTPException(status_code=503, detail="Git command failed") from exc


@router.get("/projects/{project_id}/git/executions", response_model=list[GitExecution])
def git_executions(project_id: str) -> list[GitExecution]:
    try:
        return service(project_id).executions()
    except (GitCorruptionError, GitStorageError, Timeout) as exc:
        raise git_storage_error() from exc


@router.post(
    "/projects/{project_id}/git/proposals/{proposal_id}/execute",
    response_model=GitExecution,
)
def git_execute(
    project_id: str,
    proposal_id: str,
    payload: GitExecutionCreate,
) -> GitExecution:
    try:
        return service(project_id).execute(proposal_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent proposal not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, GitPolicyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GitExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        AgentCorruptionError,
        AgentStorageError,
        GitCorruptionError,
        GitStorageError,
        Timeout,
    ) as exc:
        raise git_storage_error() from exc
