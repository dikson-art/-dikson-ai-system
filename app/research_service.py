from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Protocol

from filelock import FileLock
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from app.agent_service import AgentFrameworkService
from app.config import settings
from app.planning_service import PlanningService
from app.search_service import SearchProviderError, SemanticSearchService
from app.storage import load_project
from app.task_service import TaskQueueService
from dikson_li.agents import AgentId, AgentProposalCreate, ProposalType
from dikson_li.planning import (
    PlanActionCreate,
    PlanCreate,
    PlanDecisionCreate,
    PlanStatus,
    PlanStepStatus,
    PlanView,
)
from dikson_li.research import (
    JsonlResearchRepository,
    ResearchEvidence,
    ResearchReport,
    ResearchSnapshot,
    ResearchStateError,
    ResearchStudy,
    ResearchStudyCreate,
    build_evidence,
)
from dikson_li.tasks import (
    TaskClaimCreate,
    TaskCompleteCreate,
    TaskFailCreate,
)


class ResearchProviderError(RuntimeError):
    pass


class ResearchSynthesis(BaseModel):
    answer: str
    gaps: list[str] = Field(default_factory=list)
    used_model: bool = False
    model: str | None = None


class ResearchSynthesizer(Protocol):
    def synthesize(
        self,
        *,
        project: dict[str, Any],
        question: str,
        evidence: list[ResearchEvidence],
    ) -> ResearchSynthesis: ...


class LocalResearchSynthesizer:
    def synthesize(
        self,
        *,
        project: dict[str, Any],
        question: str,
        evidence: list[ResearchEvidence],
    ) -> ResearchSynthesis:
        if not evidence:
            return ResearchSynthesis(
                answer="В материалах проекта не найдено достаточно данных для ответа.",
                gaps=["Нужны дополнительные релевантные источники."],
            )
        return ResearchSynthesis(
            answer=(
                "Релевантные фрагменты найдены. Добавьте OPENAI_API_KEY, чтобы получить "
                "синтезированный ответ."
            ),
            gaps=["Автоматический синтез недоступен без модели."],
        )


class OpenAIResearchSynthesizer:
    """Stateless OpenAI Responses API adapter for evidence-grounded synthesis."""

    def __init__(self, api_key: str, model: str, *, client: Any | None = None) -> None:
        self.model = model
        self.client = client or OpenAI(api_key=api_key)

    def synthesize(
        self,
        *,
        project: dict[str, Any],
        question: str,
        evidence: list[ResearchEvidence],
    ) -> ResearchSynthesis:
        if not evidence:
            return LocalResearchSynthesizer().synthesize(
                project=project,
                question=question,
                evidence=evidence,
            )
        context = "\n\n".join(
            f"[{item.citation_id}] {item.title} — {item.entity_type.value}\n{item.text}"
            for item in evidence
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=(
                    "Ты Research Agent системы DIKSON. Отвечай только по предоставленным "
                    "материалам. После каждого существенного утверждения указывай citation "
                    "вида [E1]. Не выдумывай факты. В конце добавь раздел 'Пробелы', если "
                    "данных недостаточно."
                ),
                input=(
                    f"Проект: {project['name']}\n"
                    f"Описание: {project.get('description', '')}\n"
                    f"Исследовательский вопрос: {question}\n\nМатериалы:\n{context}"
                ),
                store=False,
            )
        except OpenAIError as exc:
            raise ResearchProviderError("OpenAI research synthesis failed") from exc
        output = response.output_text.strip()
        if not output:
            raise ResearchProviderError("OpenAI research synthesis returned no text")
        citations = set(re.findall(r"\[E\d+\]", output))
        allowed = {f"[{item.citation_id}]" for item in evidence}
        if not citations or citations - allowed:
            raise ResearchProviderError("OpenAI research synthesis returned invalid citations")
        return ResearchSynthesis(
            answer=output,
            used_model=True,
            model=self.model,
        )


class ResearchStudyView(BaseModel):
    study: ResearchStudy
    status: PlanStatus
    plan_id: str | None = None
    plan: PlanView | None = None
    evidence: list[ResearchEvidence]
    report: ResearchReport | None = None


class ResearchEngineService:
    """Runs evidence-grounded studies through canonical plans, agents and tasks."""

    GATHER_STEP = "gather-evidence"
    REPORT_STEP = "synthesize-report"

    def __init__(
        self,
        data_dir: Path,
        project_id: str,
        *,
        synthesizer: ResearchSynthesizer | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.project_id = project_id
        self.project_root = data_dir / "projects" / project_id
        self.repository = JsonlResearchRepository(self.project_root / "research")
        self.planning = PlanningService(data_dir, project_id)
        self.agents = AgentFrameworkService(data_dir, project_id)
        self.tasks = TaskQueueService(data_dir, project_id)
        self.synthesizer = synthesizer or self._configured_synthesizer()
        self.orchestration_lock = FileLock(
            str(self.project_root / "research" / ".orchestration.lock")
        )

    def create(self, payload: ResearchStudyCreate) -> ResearchStudyView:
        with self.orchestration_lock:
            snapshot = self.repository.create(self.project_id, payload)
            snapshot = self._ensure_plan(snapshot)
            return self._view(snapshot)

    def list(self) -> list[ResearchStudyView]:
        return [self._view(snapshot) for snapshot in self.repository.list()]

    def get(self, study_id: str) -> ResearchStudyView:
        return self._view(self.repository.get(study_id))

    def decide(self, study_id: str, payload: PlanDecisionCreate) -> ResearchStudyView:
        snapshot = self.repository.get(study_id)
        self.planning.decide(self._plan_id(snapshot), payload)
        return self.get(study_id)

    def activate(self, study_id: str, payload: PlanActionCreate) -> ResearchStudyView:
        snapshot = self.repository.get(study_id)
        self.planning.activate(self._plan_id(snapshot), payload)
        return self.get(study_id)

    def advance(self, study_id: str) -> ResearchStudyView:
        with self.orchestration_lock:
            snapshot = self.repository.get(study_id)
            plan_id = self._plan_id(snapshot)
            current_status = self.planning.get(plan_id).status
            if current_status == PlanStatus.COMPLETED:
                return self.get(study_id)
            if current_status != PlanStatus.ACTIVE:
                raise ResearchStateError("research plan must be active before advance")
            for _ in range(4):
                plan = self.planning.dispatch_ready(plan_id)
                queued = [step for step in plan.steps if step.status == PlanStepStatus.QUEUED]
                if not queued:
                    break
                progressed = False
                for step in queued:
                    if step.step.id not in {self.GATHER_STEP, self.REPORT_STEP} or not step.task_id:
                        continue
                    claimed = self.tasks.claim(
                        TaskClaimCreate(
                            worker_id=f"research-engine:{study_id}",
                            lease_seconds=300,
                            agent_id=AgentId.RESEARCH,
                            task_id=step.task_id,
                        )
                    )
                    if claimed is None:
                        continue
                    try:
                        result = self._execute_step(snapshot.study.id, step.step.id, step.run_id)
                    except (ResearchProviderError, SearchProviderError) as exc:
                        self.tasks.fail(
                            claimed.task.id,
                            TaskFailCreate(
                                lease_token=claimed.lease_token,
                                error=str(exc),
                                retryable=True,
                            ),
                        )
                        raise
                    self.tasks.complete(
                        claimed.task.id,
                        TaskCompleteCreate(lease_token=claimed.lease_token, result=result),
                    )
                    snapshot = self.repository.get(study_id)
                    progressed = True
                if not progressed:
                    break
            return self.get(study_id)

    def quick_answer(self, question: str) -> dict[str, Any]:
        project = load_project(self.project_id)
        evidence = self._collect(ResearchStudyCreate(question=question, evidence_limit=6))
        synthesis = self.synthesizer.synthesize(
            project=project,
            question=question,
            evidence=evidence,
        )
        return {
            "answer": synthesis.answer,
            "evidence": [self._legacy_evidence(item) for item in evidence],
            "used_model": synthesis.used_model,
        }

    def _ensure_plan(self, snapshot: ResearchSnapshot) -> ResearchSnapshot:
        if snapshot.plan_id is not None:
            return snapshot
        plan = next(
            (
                item
                for item in self.planning.list()
                if item.plan.metadata.get("research_study_id") == snapshot.study.id
            ),
            None,
        )
        if plan is None:
            plan = self.planning.create(self._plan_payload(snapshot))
        return self.repository.link_plan(snapshot.study.id, plan.plan.id)

    def _plan_payload(self, snapshot: ResearchSnapshot) -> PlanCreate:
        study = snapshot.study
        return PlanCreate(
            title=f"Research: {study.question[:240]}",
            objective=study.question,
            metadata={"research_study_id": study.id, "kind": "research"},
            steps=[
                {
                    "id": self.GATHER_STEP,
                    "title": "Gather evidence",
                    "objective": f"Collect evidence for: {study.question}",
                    "agent_id": "research",
                    "requested_tools": [
                        "semantic_search",
                        "graph_read",
                        "source_read",
                        "memory_read",
                    ],
                    "acceptance_criteria": [
                        "Evidence is deduplicated and each item has a stable citation ID"
                    ],
                },
                {
                    "id": self.REPORT_STEP,
                    "title": "Synthesize report",
                    "objective": f"Create a cited report for: {study.question}",
                    "agent_id": "research",
                    "depends_on": [self.GATHER_STEP],
                    "acceptance_criteria": [
                        "Every material claim is grounded in collected evidence",
                        "Knowledge gaps are explicit",
                    ],
                },
            ],
        )

    def _execute_step(self, study_id: str, step_id: str, run_id: str | None) -> dict[str, Any]:
        snapshot = self.repository.get(study_id)
        if step_id == self.GATHER_STEP:
            if not snapshot.evidence:
                snapshot = self.repository.record_evidence(
                    study_id,
                    self._collect(snapshot.study),
                )
            return {"evidence_count": len(snapshot.evidence)}
        if step_id == self.REPORT_STEP:
            if run_id is None:
                raise ResearchStateError("report step has no agent run")
            if snapshot.report is None:
                synthesis = self.synthesizer.synthesize(
                    project=load_project(self.project_id),
                    question=snapshot.study.question,
                    evidence=snapshot.evidence,
                )
                proposal = self.agents.submit_proposal(
                    AgentId.RESEARCH,
                    run_id,
                    AgentProposalCreate(
                        type=ProposalType.RESEARCH_REPORT,
                        title=f"Research report: {snapshot.study.question[:240]}",
                        summary=synthesis.answer[:10_000],
                        payload={
                            "research_study_id": study_id,
                            "answer": synthesis.answer,
                            "evidence": [
                                item.model_dump(mode="json") for item in snapshot.evidence
                            ],
                            "gaps": synthesis.gaps,
                            "used_model": synthesis.used_model,
                            "model": synthesis.model,
                        },
                        idempotency_key=f"research:{study_id}:report",
                    ),
                )
                snapshot = self.repository.record_report(
                    study_id,
                    ResearchReport(
                        answer=synthesis.answer,
                        evidence=snapshot.evidence,
                        gaps=synthesis.gaps,
                        used_model=synthesis.used_model,
                        model=synthesis.model,
                        proposal_id=proposal.id,
                        created_at=datetime.now(timezone.utc),
                    ),
                )
            return {
                "proposal_id": snapshot.report.proposal_id,
                "evidence_count": len(snapshot.report.evidence),
            }
        raise ResearchStateError(f"unknown research step {step_id}")

    def _collect(self, study: ResearchStudyCreate) -> list[ResearchEvidence]:
        queries = [study.question, *study.queries]
        unique_queries = list(dict.fromkeys(query.casefold() for query in queries))
        original_by_key = {query.casefold(): query for query in queries}
        hits = []
        search = SemanticSearchService(self.data_dir, self.project_id)
        for key in unique_queries:
            hits.extend(
                search.search(
                    original_by_key[key],
                    limit=study.evidence_limit,
                    min_score=study.min_score,
                )
            )
        return build_evidence(hits, limit=study.evidence_limit)

    def _view(self, snapshot: ResearchSnapshot) -> ResearchStudyView:
        if snapshot.plan_id is None:
            return ResearchStudyView(
                study=snapshot.study,
                status=PlanStatus.DRAFT,
                evidence=snapshot.evidence,
                report=snapshot.report,
            )
        plan_id = snapshot.plan_id
        plan = self.planning.get(plan_id)
        return ResearchStudyView(
            study=snapshot.study,
            status=plan.status,
            plan_id=plan_id,
            plan=plan,
            evidence=snapshot.evidence,
            report=snapshot.report,
        )

    @staticmethod
    def _plan_id(snapshot: ResearchSnapshot) -> str:
        if snapshot.plan_id is None:
            raise ResearchStateError("research study has no plan")
        return snapshot.plan_id

    @staticmethod
    def _configured_synthesizer() -> ResearchSynthesizer:
        if not settings.openai_api_key:
            return LocalResearchSynthesizer()
        return OpenAIResearchSynthesizer(settings.openai_api_key, settings.openai_model)

    @staticmethod
    def _legacy_evidence(item: ResearchEvidence) -> dict[str, Any]:
        payload = {
            "id": item.document_id,
            "entity_type": item.entity_type.value,
            "entity_id": item.entity_id,
            "title": item.title,
            "text": item.text,
            "score": item.score,
            "metadata": item.metadata,
        }
        for key in ("source_id", "filename", "chunk"):
            if key in item.metadata:
                payload[key] = item.metadata[key]
        return payload
