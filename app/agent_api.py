from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from filelock import Timeout

from app.agent_service import AgentFrameworkService
from app.config import settings
from app.storage import load_project
from dikson_li.agents import (
    AgentCorruptionError,
    AgentDecision,
    AgentDecisionCreate,
    AgentDefinition,
    AgentId,
    AgentPolicyError,
    AgentProposal,
    AgentProposalCreate,
    AgentProposalView,
    AgentRegistry,
    AgentRun,
    AgentRunCreate,
    AgentStorageError,
    DuplicateDecisionError,
    ProposalStatus,
)
from dikson_li.memory import (
    MemoryCorruptionError,
    MemoryRecord,
    MemoryStorageError,
)


router = APIRouter(tags=["agents"])


def service(project_id: str) -> AgentFrameworkService:
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Проект не найден") from exc
    return AgentFrameworkService(settings.dikson_data_dir, project_id)


def agent_storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Локальный журнал агентов повреждён")


@router.get("/agents", response_model=list[AgentDefinition])
def agent_registry() -> list[AgentDefinition]:
    return AgentRegistry().list()


@router.get("/agents/{agent_id}", response_model=AgentDefinition)
def agent_definition(agent_id: AgentId) -> AgentDefinition:
    return AgentRegistry().get(agent_id)


@router.post(
    "/projects/{project_id}/agents/{agent_id}/runs",
    response_model=AgentRun,
    status_code=201,
)
def agent_run_start(project_id: str, agent_id: AgentId, payload: AgentRunCreate) -> AgentRun:
    try:
        return service(project_id).start_run(agent_id, payload)
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise agent_storage_error() from exc


@router.get("/projects/{project_id}/agents/runs", response_model=list[AgentRun])
def agent_runs(project_id: str, agent_id: AgentId | None = None) -> list[AgentRun]:
    try:
        return service(project_id).runs(agent_id)
    except (AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise agent_storage_error() from exc


@router.post(
    "/projects/{project_id}/agents/{agent_id}/runs/{run_id}/proposals",
    response_model=AgentProposal,
    status_code=201,
)
def agent_proposal_submit(
    project_id: str,
    agent_id: AgentId,
    run_id: str,
    payload: AgentProposalCreate,
) -> AgentProposal:
    try:
        return service(project_id).submit_proposal(agent_id, run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Запуск агента не найден") from exc
    except AgentPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise agent_storage_error() from exc


@router.get(
    "/projects/{project_id}/agents/proposals",
    response_model=list[AgentProposalView],
)
def agent_proposals(
    project_id: str,
    agent_id: AgentId | None = None,
    status: ProposalStatus | None = None,
) -> list[AgentProposalView]:
    try:
        return service(project_id).proposals(agent_id=agent_id, status=status)
    except (AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise agent_storage_error() from exc


@router.post(
    "/projects/{project_id}/agents/proposals/{proposal_id}/decisions",
    response_model=AgentDecision,
    status_code=201,
)
def agent_proposal_decide(
    project_id: str, proposal_id: str, payload: AgentDecisionCreate
) -> AgentDecision:
    try:
        return service(project_id).decide(proposal_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Предложение агента не найдено") from exc
    except DuplicateDecisionError as exc:
        raise HTTPException(status_code=409, detail="Решение уже принято") from exc
    except (AgentCorruptionError, AgentStorageError, Timeout) as exc:
        raise agent_storage_error() from exc


@router.post(
    "/projects/{project_id}/agents/proposals/{proposal_id}/commit-memory",
    response_model=MemoryRecord,
)
def agent_memory_commit(project_id: str, proposal_id: str) -> MemoryRecord:
    try:
        return service(project_id).commit_agent_memory(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Предложение агента не найдено") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="Предложение ещё не подтверждено") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        AgentCorruptionError,
        AgentStorageError,
        MemoryCorruptionError,
        MemoryStorageError,
        Timeout,
    ) as exc:
        raise agent_storage_error() from exc


@router.get(
    "/projects/{project_id}/agents/{agent_id}/memory",
    response_model=list[MemoryRecord],
)
def agent_memory(
    project_id: str,
    agent_id: AgentId,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[MemoryRecord]:
    try:
        return service(project_id).agent_memory(agent_id)[-limit:]
    except (MemoryCorruptionError, MemoryStorageError, Timeout) as exc:
        raise agent_storage_error() from exc
