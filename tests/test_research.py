from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.graph_service import KnowledgeGraphService
from app.research_service import (
    OpenAIResearchSynthesizer,
    ResearchEngineService,
    ResearchProviderError,
    ResearchSynthesis,
)
from app.storage import create_project
from dikson_li.memory import JsonlMemoryStore
from dikson_li.planning import PlanActionCreate, PlanDecisionCreate
from dikson_li.research import (
    JsonlResearchRepository,
    ResearchCorruptionError,
    ResearchReport,
    ResearchStateError,
    ResearchStudyCreate,
    build_evidence,
)
from dikson_li.search import SearchHit


class StubSynthesizer:
    def synthesize(self, *, project, question, evidence) -> ResearchSynthesis:
        assert project["name"] == "Research Project"
        assert question == "Как устроена память?"
        assert evidence
        return ResearchSynthesis(
            answer=f"Память использует JSONL [{evidence[0].citation_id}].",
            gaps=[],
            used_model=True,
            model="stub-model",
        )


def test_research_repository_idempotency_lifecycle_and_corruption(tmp_path: Path) -> None:
    repository = JsonlResearchRepository(tmp_path)
    payload = ResearchStudyCreate(
        question="Canonical memory?",
        queries=[" memory ", "MEMORY", "jsonl"],
        idempotency_key="study-1",
    )
    created = repository.create("project", payload)
    repeated = repository.create("project", payload.model_copy(update={"question": "Changed?"}))
    assert repeated.study.id == created.study.id
    assert created.study.queries == ["memory", "jsonl"]
    linked = repository.link_plan(created.study.id, "plan-1")
    assert linked.plan_id == "plan-1"
    with pytest.raises(ResearchStateError, match="another plan"):
        repository.link_plan(created.study.id, "plan-2")

    empty = repository.record_evidence(created.study.id, [])
    again = repository.record_evidence(created.study.id, [])
    assert len(again.events) == len(empty.events)
    report = ResearchReport(
        answer="Insufficient evidence",
        evidence=[],
        gaps=["source missing"],
        created_at=created.study.created_at,
    )
    completed = repository.record_report(created.study.id, report)
    assert completed.report == report

    repository.events_path.write_text("{broken}\n", encoding="utf-8")
    with pytest.raises(ResearchCorruptionError, match="line 1"):
        repository.get(created.study.id)


def test_build_evidence_keeps_best_hit_and_stable_citations() -> None:
    hits = [
        SearchHit(
            id="memory:one",
            entity_type="memory",
            entity_id="one",
            title="fact",
            text="low",
            score=0.2,
        ),
        SearchHit(
            id="memory:one",
            entity_type="memory",
            entity_id="one",
            title="fact",
            text="high",
            score=0.9,
        ),
        SearchHit(
            id="wiki:two",
            entity_type="wiki_page",
            entity_id="two",
            title="Wiki",
            text="second",
            score=0.7,
        ),
    ]

    evidence = build_evidence(hits, limit=2)

    assert [(item.citation_id, item.document_id, item.text) for item in evidence] == [
        ("E1", "memory:one", "high"),
        ("E2", "wiki:two", "second"),
    ]


def test_openai_synthesizer_uses_stateless_responses_api() -> None:
    calls = []

    class Responses:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="Grounded answer [E1].")

    client = SimpleNamespace(responses=Responses())
    evidence = build_evidence(
        [
            SearchHit(
                id="memory:one",
                entity_type="memory",
                entity_id="one",
                title="fact",
                text="Evidence",
                score=0.9,
            )
        ],
        limit=1,
    )

    result = OpenAIResearchSynthesizer("key", "model", client=client).synthesize(
        project={"name": "Project"},
        question="Question?",
        evidence=evidence,
    )

    assert result.answer == "Grounded answer [E1]."
    assert result.used_model is True
    assert calls[0]["model"] == "model"
    assert calls[0]["store"] is False
    assert "[E1]" in calls[0]["input"]
    assert calls[0]["instructions"]

    class InvalidResponses:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(output_text="Unsupported claim [E9].")

    with pytest.raises(ResearchProviderError, match="citations"):
        OpenAIResearchSynthesizer(
            "key",
            "model",
            client=SimpleNamespace(responses=InvalidResponses()),
        ).synthesize(
            project={"name": "Project"},
            question="Question?",
            evidence=evidence,
        )


def test_research_service_recovers_study_created_before_plan_link(tmp_path: Path) -> None:
    service = ResearchEngineService(tmp_path, "project", synthesizer=StubSynthesizer())
    payload = ResearchStudyCreate(
        question="Recover plan link",
        idempotency_key="recover-study",
    )
    orphan = service.repository.create("project", payload)
    incomplete = service.get(orphan.study.id)
    assert incomplete.plan_id is None
    assert incomplete.plan is None

    recovered = service.create(payload)

    assert recovered.study.id == orphan.study.id
    assert recovered.plan_id
    assert recovered.plan is not None
    assert len(service.repository.list()) == 1
    assert len(service.planning.list()) == 1


def test_research_engine_runs_approved_plan_and_projects_graph(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dikson_data_dir", tmp_path)
    project_id = create_project("Research Project")["id"]
    memory = JsonlMemoryStore(tmp_path / "projects").append(
        project_id=project_id,
        kind="fact",
        content="Каноническая память хранится в JSONL.",
        tags=["memory"],
    )
    service = ResearchEngineService(tmp_path, project_id, synthesizer=StubSynthesizer())
    created = service.create(
        ResearchStudyCreate(
            question="Как устроена память?",
            queries=["JSONL memory"],
            idempotency_key="memory-study",
        )
    )
    assert created.status == "draft"
    assert [step.step.id for step in created.plan.steps] == [
        "gather-evidence",
        "synthesize-report",
    ]
    with pytest.raises(ResearchStateError, match="active"):
        service.advance(created.study.id)

    service.decide(
        created.study.id,
        PlanDecisionCreate(outcome="approved", reviewer="lead", reason="scoped"),
    )
    service.activate(
        created.study.id,
        PlanActionCreate(actor="lead", reason="execute"),
    )
    completed = service.advance(created.study.id)

    assert completed.status == "completed"
    assert completed.report is not None
    assert completed.report.answer.endswith("[E1].")
    assert completed.report.proposal_id
    assert {step.status for step in completed.plan.steps} == {"succeeded"}
    assert len(service.tasks.list()) == 2
    assert len(service.agents.runs()) == 2
    proposals = service.agents.proposals(agent_id="research")
    assert len(proposals) == 1
    assert proposals[0].proposal.type == "research_report"
    assert proposals[0].status == "pending"

    repeated = service.advance(created.study.id)
    assert repeated.report.proposal_id == completed.report.proposal_id
    assert len(service.agents.proposals(agent_id="research")) == 1

    graph = KnowledgeGraphService(tmp_path, project_id).snapshot()
    research_node_id = f"research:{created.study.id}"
    assert research_node_id in {node.id for node in graph.nodes}
    assert any(
        edge.from_node_id == research_node_id
        and edge.to_node_id == f"memory:{memory.id}"
        and edge.type == "derived_from"
        for edge in graph.edges
    )
