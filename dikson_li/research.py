from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dikson_li.search import SearchEntityType, SearchHit


class ResearchEventType(StrEnum):
    PLAN_LINKED = "plan_linked"
    EVIDENCE_COLLECTED = "evidence_collected"
    REPORT_COMPLETED = "report_completed"


class ResearchStudyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=10_000)
    queries: list[str] = Field(default_factory=list, max_length=10)
    evidence_limit: int = Field(default=12, ge=1, le=50)
    min_score: float = Field(default=0.05, ge=0, le=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("question", "idempotency_key")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for query in value:
            item = query.strip()
            if len(item) > 1_000:
                raise ValueError("research queries must not exceed 1000 characters")
            key = item.casefold()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized


class ResearchStudy(ResearchStudyCreate):
    id: str
    project_id: str
    created_at: datetime


class ResearchEvidence(BaseModel):
    citation_id: str
    document_id: str
    entity_type: SearchEntityType
    entity_id: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchReport(BaseModel):
    answer: str
    evidence: list[ResearchEvidence]
    gaps: list[str] = Field(default_factory=list)
    used_model: bool = False
    model: str | None = None
    proposal_id: str | None = None
    created_at: datetime


class ResearchEvent(BaseModel):
    id: str
    project_id: str
    study_id: str
    type: ResearchEventType
    created_at: datetime
    plan_id: str | None = None
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    report: ResearchReport | None = None


class ResearchSnapshot(BaseModel):
    study: ResearchStudy
    plan_id: str | None = None
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    report: ResearchReport | None = None
    events: list[ResearchEvent] = Field(default_factory=list)


class ResearchStorageError(RuntimeError):
    pass


class ResearchCorruptionError(ResearchStorageError):
    pass


class ResearchStateError(ValueError):
    pass


class JsonlResearchRepository:
    """Append-only studies and evidence/report lifecycle events."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.studies_path = self.root / "studies.jsonl"
        self.events_path = self.root / "events.jsonl"
        self.lock_timeout = lock_timeout

    def create(self, project_id: str, payload: ResearchStudyCreate) -> ResearchSnapshot:
        with self._lock():
            studies = self._read_rows(self.studies_path, ResearchStudy)
            if payload.idempotency_key:
                for study in studies:
                    if study.idempotency_key == payload.idempotency_key:
                        return self._snapshot(study, self._events_for(study.id))
            study = ResearchStudy(
                id=uuid4().hex,
                project_id=project_id,
                created_at=datetime.now(timezone.utc),
                **payload.model_dump(),
            )
            self._append(self.studies_path, study.model_dump_json())
        return ResearchSnapshot(study=study)

    def list(self) -> list[ResearchSnapshot]:
        with self._lock():
            studies = self._read_rows(self.studies_path, ResearchStudy)
            events = self._read_rows(self.events_path, ResearchEvent)
        by_study: dict[str, list[ResearchEvent]] = {}
        for event in events:
            by_study.setdefault(event.study_id, []).append(event)
        return [self._snapshot(study, by_study.get(study.id, [])) for study in studies]

    def get(self, study_id: str) -> ResearchSnapshot:
        with self._lock():
            study = self._find(self._read_rows(self.studies_path, ResearchStudy), study_id)
            events = self._events_for(study_id)
        return self._snapshot(study, events)

    def link_plan(self, study_id: str, plan_id: str) -> ResearchSnapshot:
        with self._lock():
            study, events, snapshot = self._locked_snapshot(study_id)
            if snapshot.plan_id is not None:
                if snapshot.plan_id != plan_id:
                    raise ResearchStateError("research study is linked to another plan")
                return snapshot
            event = self._event(study, ResearchEventType.PLAN_LINKED, plan_id=plan_id)
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(study, [*events, event])

    def record_evidence(self, study_id: str, evidence: list[ResearchEvidence]) -> ResearchSnapshot:
        with self._lock():
            study, events, snapshot = self._locked_snapshot(study_id)
            if any(event.type == ResearchEventType.EVIDENCE_COLLECTED for event in events):
                return snapshot
            event = self._event(
                study,
                ResearchEventType.EVIDENCE_COLLECTED,
                evidence=evidence,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(study, [*events, event])

    def record_report(self, study_id: str, report: ResearchReport) -> ResearchSnapshot:
        with self._lock():
            study, events, snapshot = self._locked_snapshot(study_id)
            if snapshot.report is not None:
                return snapshot
            if not any(event.type == ResearchEventType.EVIDENCE_COLLECTED for event in events):
                raise ResearchStateError("evidence must be collected before report")
            if report.evidence != snapshot.evidence:
                raise ResearchStateError("report evidence must match collected evidence")
            event = self._event(
                study,
                ResearchEventType.REPORT_COMPLETED,
                report=report,
            )
            self._append(self.events_path, event.model_dump_json())
        return self._snapshot(study, [*events, event])

    def _locked_snapshot(
        self, study_id: str
    ) -> tuple[ResearchStudy, list[ResearchEvent], ResearchSnapshot]:
        study = self._find(self._read_rows(self.studies_path, ResearchStudy), study_id)
        events = self._events_for(study_id)
        return study, events, self._snapshot(study, events)

    def _events_for(self, study_id: str) -> list[ResearchEvent]:
        return [
            event
            for event in self._read_rows(self.events_path, ResearchEvent)
            if event.study_id == study_id
        ]

    @staticmethod
    def _snapshot(study: ResearchStudy, events: list[ResearchEvent]) -> ResearchSnapshot:
        plan_id = None
        evidence: list[ResearchEvidence] = []
        report = None
        for event in events:
            if event.type == ResearchEventType.PLAN_LINKED:
                plan_id = event.plan_id
            elif event.type == ResearchEventType.EVIDENCE_COLLECTED:
                evidence = event.evidence
            elif event.type == ResearchEventType.REPORT_COMPLETED:
                report = event.report
        return ResearchSnapshot(
            study=study,
            plan_id=plan_id,
            evidence=evidence,
            report=report,
            events=events,
        )

    @staticmethod
    def _event(
        study: ResearchStudy,
        event_type: ResearchEventType,
        *,
        plan_id: str | None = None,
        evidence: list[ResearchEvidence] | None = None,
        report: ResearchReport | None = None,
    ) -> ResearchEvent:
        return ResearchEvent(
            id=uuid4().hex,
            project_id=study.project_id,
            study_id=study.id,
            type=event_type,
            created_at=datetime.now(timezone.utc),
            plan_id=plan_id,
            evidence=evidence or [],
            report=report,
        )

    def _read_rows(self, path: Path, model):
        if not path.exists():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ResearchStorageError(f"Could not read {path.name}") from exc
        records = []
        for line_number, row in enumerate(rows, start=1):
            if not row.strip():
                continue
            try:
                records.append(model.model_validate_json(row))
            except ValueError as exc:
                raise ResearchCorruptionError(
                    f"Invalid {path.name} row at line {line_number}"
                ) from exc
        return records

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
            raise ResearchStorageError(f"Could not append {path.name}") from exc

    def _lock(self) -> FileLock:
        return FileLock(str(self.root / ".research.lock"), timeout=self.lock_timeout)


def build_evidence(hits: list[SearchHit], *, limit: int) -> list[ResearchEvidence]:
    """Deduplicate multi-query hits and assign stable report-local citations."""

    best_by_document: dict[str, SearchHit] = {}
    for hit in hits:
        current = best_by_document.get(hit.id)
        if current is None or hit.score > current.score:
            best_by_document[hit.id] = hit
    ranked = sorted(
        best_by_document.values(),
        key=lambda item: (-item.score, item.entity_type.value, item.id),
    )[:limit]
    return [
        ResearchEvidence(
            citation_id=f"E{index}",
            document_id=hit.id,
            entity_type=hit.entity_type,
            entity_id=hit.entity_id,
            title=hit.title,
            text=hit.text,
            score=hit.score,
            metadata=hit.metadata,
        )
        for index, hit in enumerate(ranked, start=1)
    ]
