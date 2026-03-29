from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class QueryType(StrEnum):
    PICO = "pico"
    PCC = "pcc"
    FREE = "free"


class ResearchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    AGENT_STARTED = "agent_started"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUESTED = "approval_requested"
    ARTIFACT_CREATED = "artifact_created"
    REPORT_DELTA = "report_delta"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class ArtifactType(StrEnum):
    TODO_LIST = "todo_list"
    SEARCH_PLAN = "search_plan"
    SEARCH_RESULTS = "search_results"
    SOURCE_PLAN = "source_plan"
    EVIDENCE_SUMMARY = "evidence_summary"
    RANKED_RESULTS = "ranked_results"
    VERIFICATION_REPORT = "verification_report"
    FINAL_REPORT = "final_report"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ResearchRun(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    query: str
    query_type: str = Field(default=QueryType.PICO.value, index=True)
    mode: str = Field(default="detailed")
    provider: str = Field(index=True)
    model: str
    runtime_name: str
    language: str = Field(default="en")
    status: str = Field(default=ResearchStatus.PENDING.value, index=True)
    phase: str = Field(default="init")
    progress: int = Field(default=0)
    title: str | None = None
    query_payload_json: str | None = None
    result_markdown: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RuntimeEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(foreign_key="researchrun.id", index=True)
    sequence: int = Field(index=True)
    event_type: str = Field(index=True)
    phase: str
    progress: int = 0
    message: str
    agent_name: str | None = None
    tool_name: str | None = None
    payload_json: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ResearchArtifact(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(foreign_key="researchrun.id", index=True)
    artifact_type: str = Field(index=True)
    name: str
    content_text: str | None = None
    content_json: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ApprovalRequest(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(foreign_key="researchrun.id", index=True)
    summary: str
    details_json: str | None = None
    status: str = Field(default=ApprovalStatus.PENDING.value, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    resolved_at: datetime | None = None


class ApiKey(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    service: str = Field(unique=True, index=True)
    api_key: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    category: str | None = None
    updated_at: datetime | None = None


class RuntimeEventPayload(SQLModel):
    event_type: EventType
    phase: str
    progress: int
    message: str
    agent_name: str | None = None
    tool_name: str | None = None
    artifact_type: ArtifactType | None = None
    artifact_name: str | None = None
    artifact_text: str | None = None
    artifact_json: dict[str, Any] | list[Any] | None = None
    report_markdown: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
