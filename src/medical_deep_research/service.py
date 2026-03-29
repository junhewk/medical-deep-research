from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from sqlmodel import col, desc, select

from .models import (
    ApprovalRequest,
    ApprovalStatus,
    ApiKey,
    EventType,
    ResearchArtifact,
    ResearchRun,
    ResearchStatus,
    RuntimeEvent,
    RuntimeEventPayload,
    Setting,
    utcnow,
)
from .persistence import AppDatabase
from .runtime import RunRequest, build_runtime, describe_provider_runtime


DEFAULT_MODELS = {
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "google": "gemini-2.5-flash",
    "local": "qwen3.5-27b",
}

_UICallback = Callable[[str, str], None]  # (run_id, change_type)


class ResearchService:
    def __init__(self, database: AppDatabase) -> None:
        self.database = database
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._ui_listeners: list[_UICallback] = []

    def add_ui_listener(self, callback: _UICallback) -> None:
        self._ui_listeners.append(callback)

    def _notify_ui(self, run_id: str, change_type: str) -> None:
        for cb in self._ui_listeners:
            try:
                cb(run_id, change_type)
            except Exception:
                pass

    def list_runs(self, *, limit: int = 20, offset: int = 0) -> list[ResearchRun]:
        with self.database.session() as session:
            statement = select(ResearchRun).order_by(desc(ResearchRun.created_at)).offset(offset).limit(limit)
            return list(session.exec(statement))

    def count_runs(self) -> int:
        with self.database.session() as session:
            from sqlmodel import func
            statement = select(func.count()).select_from(ResearchRun)
            return session.exec(statement).one()

    def get_run(self, run_id: str) -> ResearchRun | None:
        with self.database.session() as session:
            return session.get(ResearchRun, run_id)

    def list_events(self, run_id: str) -> list[RuntimeEvent]:
        with self.database.session() as session:
            statement = (
                select(RuntimeEvent)
                .where(RuntimeEvent.run_id == run_id)
                .order_by(col(RuntimeEvent.sequence))
            )
            return list(session.exec(statement))

    def list_artifacts(self, run_id: str) -> list[ResearchArtifact]:
        with self.database.session() as session:
            statement = (
                select(ResearchArtifact)
                .where(ResearchArtifact.run_id == run_id)
                .order_by(desc(ResearchArtifact.created_at))
            )
            return list(session.exec(statement))

    def list_approvals(self, run_id: str) -> list[ApprovalRequest]:
        with self.database.session() as session:
            statement = (
                select(ApprovalRequest)
                .where(ApprovalRequest.run_id == run_id)
                .order_by(desc(ApprovalRequest.created_at))
            )
            return list(session.exec(statement))

    def get_language(self) -> str:
        with self.database.session() as session:
            language = session.get(Setting, "language")
            return language.value if language else "en"

    def set_language(self, language: str) -> None:
        with self.database.session() as session:
            existing = session.get(Setting, "language")
            if existing:
                existing.value = language
            else:
                session.add(Setting(key="language", value=language, category="general"))
            session.commit()

    def get_api_keys(self) -> dict[str, str]:
        with self.database.session() as session:
            statement = select(ApiKey)
            return {record.service: record.api_key for record in session.exec(statement)}

    def save_api_key(self, service: str, api_key: str) -> None:
        with self.database.session() as session:
            existing = session.exec(select(ApiKey).where(ApiKey.service == service)).first()
            if existing:
                existing.api_key = api_key
            else:
                session.add(ApiKey(service=service, api_key=api_key))
            session.commit()

    def get_provider_diagnostics(self) -> list[dict[str, Any]]:
        api_keys = self.get_api_keys()
        offline_mode = self.database.settings.offline_mode
        diagnostics = []
        for provider, default_model in DEFAULT_MODELS.items():
            diagnostics.append(
                describe_provider_runtime(
                    provider,
                    api_keys=api_keys,
                    offline_mode=offline_mode,
                    default_model=default_model,
                ).model_dump()
            )
        return diagnostics

    def get_run_diagnostics(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        events = self.list_events(run_id)
        start_event = next((event for event in events if event.event_type == EventType.RUN_STARTED.value), None)
        completed_event = next(
            (event for event in reversed(events) if event.event_type == EventType.RUN_COMPLETED.value),
            None,
        )

        def parse_payload(raw: str | None) -> dict[str, Any]:
            if not raw:
                return {}
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        start_payload = parse_payload(start_event.payload_json if start_event else None)
        completed_payload = parse_payload(completed_event.payload_json if completed_event else None)
        payload = {**start_payload, **completed_payload}
        execution_mode = payload.get("execution_mode")
        if not execution_mode and start_event:
            lowered = start_event.message.lower()
            if lowered.startswith("starting native"):
                execution_mode = "native_sdk"
            elif "deterministic" in lowered:
                execution_mode = "deterministic_fallback"

        return {
            "provider": run.provider,
            "model": run.model,
            "runtime_name": run.runtime_name,
            "status": run.status,
            "execution_mode": execution_mode or "unknown",
            "sdk_available": payload.get("sdk_available"),
            "offline_mode": payload.get("offline_mode"),
            "provider_credentials_present": payload.get("provider_credentials_present"),
            "fallback_reason": payload.get("fallback_reason"),
            "ranked_results": payload.get("ranked_results"),
            "started_message": start_event.message if start_event else None,
            "completed_message": completed_event.message if completed_event else None,
        }

    def create_run(
        self,
        *,
        query: str,
        query_type: str,
        provider: str,
        model: str | None = None,
        mode: str = "detailed",
        query_payload: dict[str, Any] | None = None,
    ) -> ResearchRun:
        runtime = build_runtime(provider)
        run = ResearchRun(
            query=query,
            query_type=query_type,
            mode=mode,
            provider=provider,
            model=model or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"]),
            runtime_name=runtime.runtime_name,
            language=self.get_language(),
            query_payload_json=json.dumps(query_payload or {}),
        )
        with self.database.session() as session:
            session.add(run)
            session.commit()
            session.refresh(run)

        task = asyncio.create_task(self._execute_run(run.id), name=f"research-run-{run.id}")
        self._tasks[run.id] = task
        self._notify_ui(run.id, "run_created")
        return run

    def interrupt_run(self, run_id: str) -> None:
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if not run or run.status != ResearchStatus.RUNNING.value:
                return
            run.status = ResearchStatus.INTERRUPTED.value
            run.phase = "interrupted"
            session.add(
                ApprovalRequest(
                    run_id=run_id,
                    summary="Run interrupted by the user",
                    details_json=json.dumps({"reason": "manual interrupt"}),
                    status=ApprovalStatus.PENDING.value,
                )
            )
            session.commit()
        self._notify_ui(run_id, "run_interrupted")

    def cancel_run(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if not run:
                return
            run.status = ResearchStatus.CANCELLED.value
            run.phase = "cancelled"
            run.completed_at = utcnow()
            session.commit()
        self._notify_ui(run_id, "run_cancelled")

    def resolve_approval(self, approval_id: str, approved: bool) -> None:
        with self.database.session() as session:
            approval = session.get(ApprovalRequest, approval_id)
            if not approval:
                return
            approval.status = ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value
            approval.resolved_at = utcnow()
            session.commit()

    async def _execute_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        if run is None:
            return

        runtime = build_runtime(run.provider)
        request = RunRequest(
            run_id=run.id,
            query=run.query,
            query_type=run.query_type,
            mode=run.mode,
            provider=run.provider,
            model=run.model,
            language=run.language,
            api_keys=self.get_api_keys(),
            offline_mode=self.database.settings.offline_mode,
        )

        with self.database.session() as session:
            stored = session.get(ResearchRun, run_id)
            if stored is None:
                return
            stored.status = ResearchStatus.RUNNING.value
            stored.phase = "planning"
            stored.progress = 1
            stored.started_at = utcnow()
            session.commit()

        sequence = 0
        try:
            async for event in runtime.stream_run(request):
                sequence += 1
                self._persist_event(run_id, sequence, event)
                current_run = self.get_run(run_id)
                if current_run and current_run.status in {
                    ResearchStatus.CANCELLED.value,
                    ResearchStatus.INTERRUPTED.value,
                }:
                    return
            self._mark_run_complete(run_id)
        except asyncio.CancelledError:
            self.cancel_run(run_id)
            raise
        except Exception as exc:  # pragma: no cover - defensive failure path
            self._mark_run_failed(run_id, str(exc))

    def _persist_event(self, run_id: str, sequence: int, event: RuntimeEventPayload) -> None:
        payload_json = json.dumps(event.extra) if event.extra else None
        artifact_json = json.dumps(event.artifact_json) if event.artifact_json is not None else None
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if run is None:
                return

            run.phase = event.phase
            run.progress = event.progress
            if event.event_type == EventType.REPORT_DELTA and event.report_markdown:
                run.result_markdown = event.report_markdown
            if event.event_type == EventType.RUN_COMPLETED and event.report_markdown:
                run.result_markdown = event.report_markdown
            if event.event_type == EventType.RUN_FAILED:
                run.status = ResearchStatus.FAILED.value
                run.error_message = event.message

            session.add(
                RuntimeEvent(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=event.event_type.value,
                    phase=event.phase,
                    progress=event.progress,
                    message=event.message,
                    agent_name=event.agent_name,
                    tool_name=event.tool_name,
                    payload_json=payload_json,
                )
            )

            if event.artifact_type and event.artifact_name:
                session.add(
                    ResearchArtifact(
                        run_id=run_id,
                        artifact_type=event.artifact_type.value,
                        name=event.artifact_name,
                        content_text=event.artifact_text,
                        content_json=artifact_json,
                    )
                )

            session.commit()
        self._notify_ui(run_id, "event")

    def _mark_run_complete(self, run_id: str) -> None:
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if run is None:
                return
            run.status = ResearchStatus.COMPLETED.value
            run.phase = "complete"
            run.progress = 100
            run.completed_at = utcnow()
            session.commit()
        self._notify_ui(run_id, "run_completed")

    def _mark_run_failed(self, run_id: str, error_message: str) -> None:
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if run is None:
                return
            run.status = ResearchStatus.FAILED.value
            run.phase = "failed"
            run.error_message = error_message
            run.completed_at = utcnow()
            session.add(
                RuntimeEvent(
                    run_id=run_id,
                    sequence=len(self.list_events(run_id)) + 1,
                    event_type=EventType.RUN_FAILED.value,
                    phase="failed",
                    progress=run.progress,
                    message=error_message,
                )
            )
            session.commit()
        self._notify_ui(run_id, "run_failed")
