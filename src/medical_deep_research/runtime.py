from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from contextlib import contextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, TypeVar

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from .models import ArtifactType, EventType, RuntimeEventPayload
from .research import (
    build_query_plan,
    empty_verification_summary,
    flatten_studies,
    render_report,
    render_verification_report,
    score_and_rank_results,
    search_source,
    verify_studies,
)
from .research.models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary
import httpx

from .research.search import POLITE_EMAIL
from .research.planning import suggest_databases as _suggest_databases


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]
OPENAI_MCP_TIMEOUT_SECONDS = 20.0
GOOGLE_MCP_TIMEOUT_SECONDS = 20.0
LITERATURE_TOOL_FILTER = ["aggregate_search"]
EVIDENCE_TOOL_FILTER = ["rank_results", "verify_results"]
MAX_AGENT_SEARCH_ITERATIONS = 2
SEARCH_GUIDANCE_TIMEOUT_SECONDS = 20.0
REWIND_DECISION_TIMEOUT_SECONDS = 15.0
FINAL_SYNTHESIS_TIMEOUT_SECONDS = 25.0
ANTHROPIC_AGENTIC_TIMEOUT_SECONDS = 300.0
ANTHROPIC_AGENTIC_MAX_TURNS = 25
TModel = TypeVar("TModel", bound=BaseModel)
_log = logging.getLogger(__name__)


class RunRequest(SQLModel):
    run_id: str
    query: str
    query_type: str
    mode: str
    provider: str
    model: str
    language: str = "en"
    api_keys: dict[str, str] = Field(default_factory=dict)
    offline_mode: bool = False


class AgentResearchOutput(BaseModel):
    plan: QueryPlan
    search_results: list[SearchProviderResult] = Field(default_factory=list)
    ranked_studies: list[ScoredStudy] = Field(default_factory=list)
    verification: VerificationSummary = Field(
        default_factory=lambda: empty_verification_summary(
            "Verification output was not returned by the provider runtime."
        )
    )
    final_report: str


class SearchGuidanceOutput(BaseModel):
    strategy_summary: str
    source_queries: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RewindDecisionOutput(BaseModel):
    should_rewind: bool = False
    rationale: str
    source_queries: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class FinalSynthesisOutput(BaseModel):
    final_report: str


class ProviderDiagnostics(BaseModel):
    provider: str
    runtime_name: str
    default_model: str | None = None
    sdk_available: bool
    offline_mode: bool
    provider_credentials_present: bool
    search_credentials_present: dict[str, bool] = Field(default_factory=dict)
    active_execution_path: str
    fallback_reason: str | None = None


class ResearchRuntime(ABC):
    provider: str
    runtime_name: str
    sdk_module: str | None = None

    @property
    def sdk_available(self) -> bool:
        if not self.sdk_module:
            return False
        return importlib.util.find_spec(self.sdk_module) is not None

    @abstractmethod
    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:  # type: ignore[override]
        raise NotImplementedError
        yield  # pragma: no cover


def _source_tool_name(source: str) -> str:
    return f"literature.search_{source.lower().replace(' ', '_')}"


def _provider_api_env(provider: str, api_keys: dict[str, str]) -> dict[str, str]:
    if provider == "openai":
        api_key = api_keys.get("openai") or os.getenv("OPENAI_API_KEY")
        return {"OPENAI_API_KEY": api_key} if api_key else {}
    if provider == "anthropic":
        api_key = api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")
        return {"ANTHROPIC_API_KEY": api_key} if api_key else {}
    if provider == "google":
        api_key = (
            api_keys.get("google")
            or api_keys.get("gemini")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not api_key:
            return {}
        return {"GOOGLE_API_KEY": api_key, "GEMINI_API_KEY": api_key}
    return {}


def _search_api_env(api_keys: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    ncbi = api_keys.get("ncbi") or os.getenv("MDR_NCBI_API_KEY")
    scopus = api_keys.get("scopus") or os.getenv("MDR_SCOPUS_API_KEY")
    semantic_scholar = (
        api_keys.get("semantic_scholar")
        or api_keys.get("semanticscholar")
        or os.getenv("MDR_SEMANTIC_SCHOLAR_API_KEY")
    )
    if ncbi:
        env["MDR_NCBI_API_KEY"] = ncbi
    if scopus:
        env["MDR_SCOPUS_API_KEY"] = scopus
    if semantic_scholar:
        env["MDR_SEMANTIC_SCHOLAR_API_KEY"] = semantic_scholar
    return env


def _has_native_credentials(provider: str, api_keys: dict[str, str]) -> bool:
    return bool(_provider_api_env(provider, api_keys))


def provider_fallback_reason(runtime: ResearchRuntime, request: RunRequest) -> str | None:
    if request.offline_mode:
        return "Offline mode is enabled."
    if not runtime.sdk_available:
        return f"{runtime.runtime_name} is not installed."
    if not _has_native_credentials(runtime.provider, request.api_keys):
        return f"{runtime.provider} API key is not configured."
    return None


def describe_provider_runtime(
    provider: str,
    *,
    api_keys: dict[str, str],
    offline_mode: bool,
    default_model: str | None = None,
) -> ProviderDiagnostics:
    runtime = build_runtime(provider)
    provider_credentials_present = _has_native_credentials(provider, api_keys)
    search_credentials = _search_api_env(api_keys)
    request = RunRequest(
        run_id="diagnostics",
        query="diagnostics",
        query_type="free",
        mode="detailed",
        provider=provider,
        model=default_model or "",
        api_keys=api_keys,
        offline_mode=offline_mode,
    )
    fallback_reason = provider_fallback_reason(runtime, request)
    return ProviderDiagnostics(
        provider=provider,
        runtime_name=runtime.runtime_name,
        default_model=default_model,
        sdk_available=runtime.sdk_available,
        offline_mode=offline_mode,
        provider_credentials_present=provider_credentials_present,
        search_credentials_present={
            "ncbi": "MDR_NCBI_API_KEY" in search_credentials,
            "scopus": "MDR_SCOPUS_API_KEY" in search_credentials,
            "semantic_scholar": "MDR_SEMANTIC_SCHOLAR_API_KEY" in search_credentials,
        },
        active_execution_path="deterministic_fallback" if fallback_reason else "native_sdk",
        fallback_reason=fallback_reason,
    )


def _python_executable() -> str:
    preferred = REPO_ROOT / ".venv" / "bin" / "python"
    if preferred.exists():
        return str(preferred)
    return str(Path(sys.executable).resolve())


def _build_mcp_server_env(request: RunRequest) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{pythonpath}" if pythonpath else str(SRC_ROOT)
    env.update(_search_api_env(request.api_keys))
    env["MDR_OFFLINE_MODE"] = "1" if request.offline_mode else "0"
    return env


def _openai_mcp_stdio_params(server_name: str, request: RunRequest) -> dict[str, object]:
    return {
        "command": _python_executable(),
        "args": ["-m", "medical_deep_research.mcp.servers", server_name, "--transport", "stdio"],
        "env": _build_mcp_server_env(request),
        "cwd": str(REPO_ROOT),
    }


@contextmanager
def _temporary_env(updates: dict[str, str]) -> Iterator[None]:
    previous: dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            os.environ[key] = value
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _native_agent_instructions(request: RunRequest, runtime_name: str) -> str:
    offline = "true" if request.offline_mode else "false"
    return "\n".join(
        [
            f"You are the provider-native medical research orchestrator for {runtime_name}.",
            "Use the attached MCP tools only. Do not invent studies, citations, or verification details.",
            "Execute this exact workflow:",
            f"1. Call `aggregate_search` with query, query_type=`{request.query_type}`, provider=`{request.provider}`, and offline_mode={offline}.",
            "2. Call `rank_results` with the aggregated `studies` from step 1. Use context `clinical` when the plan domain is clinical, otherwise `general`.",
            f"3. Call `verify_results` with the ranked studies and offline_mode={offline}.",
            "4. Return the final structured JSON object directly.",
            "Use the `plan` and `results` fields from `aggregate_search`, the `studies` field from `rank_results`, and the `summary` field from `verify_results`.",
            "Set `search_results` to the normalized source results from `aggregate_search`.",
            "Set `ranked_studies` to the ranked studies from `rank_results`, truncated to the top 8 items if needed.",
            "Set `verification` to the verification summary from `verify_results`.",
            "Write `final_report` as concise markdown with sections for Executive Summary, Methods, Ranked Evidence, Verification, and References.",
            "Return only valid JSON matching the structured schema. Do not wrap the JSON in markdown fences or prose.",
        ]
    )


def _native_user_prompt(request: RunRequest) -> str:
    return "\n".join(
        [
            f"Research query: {request.query}",
            f"Query type: {request.query_type}",
            f"Provider: {request.provider}",
            f"Preferred model: {request.model}",
            f"Offline mode: {'enabled' if request.offline_mode else 'disabled'}",
            "Build the literature review through MCP tools and return the structured output.",
        ]
    )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_json_object_from_text(text: str) -> dict[str, Any]:
    stripped = _strip_json_fence(text)
    if not stripped:
        raise ValueError("Provider output was empty.")
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(stripped)
    except JSONDecodeError:
        for index, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(stripped[index:])
            except JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Provider output did not contain a valid JSON object.")
    if not isinstance(parsed, dict):
        raise ValueError("Provider output JSON was not an object.")
    return parsed


def _coerce_native_output(payload: Any) -> AgentResearchOutput:
    return _coerce_model_output(payload, AgentResearchOutput)


def _coerce_model_output(payload: Any, output_model: type[TModel]) -> TModel:
    if isinstance(payload, output_model):
        return payload
    if hasattr(payload, "model_dump"):
        return output_model.model_validate(payload.model_dump())
    if isinstance(payload, dict):
        if len(payload) == 1:
            wrapper_key = next(iter(payload))
            if wrapper_key in {"result", "response", "research_output"}:
                return _coerce_model_output(payload[wrapper_key], output_model)
        return output_model.model_validate(payload)
    if isinstance(payload, str):
        return output_model.model_validate(_parse_json_object_from_text(payload))
    raise TypeError(f"Unsupported provider output type: {type(payload).__name__}")


def _get_mapping_or_attr(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _tool_name_from_raw_item(raw_item: Any) -> str:
    namespace = _get_mapping_or_attr(raw_item, "namespace")
    name = _get_mapping_or_attr(raw_item, "name") or _get_mapping_or_attr(raw_item, "type")
    if namespace and name and namespace != name:
        return f"{namespace}.{name}"
    if name:
        return str(name)
    return "tool"


def _claude_text_from_blocks(blocks: list[Any]) -> str:
    text_parts = [block.text for block in blocks if getattr(block, "text", None)]
    return "\n".join(part for part in text_parts if part).strip()


def _google_text_from_event(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = [part.text for part in parts if getattr(part, "text", None)]
    return "\n".join(part for part in text_parts if part).strip()


class DeterministicRuntime(ResearchRuntime):
    planner_name: str = "Planner"
    search_agent_name: str = "Search Agent"
    synthesis_agent_name: str = "Synthesis Agent"
    verifier_name: str = "Verification Agent"

    def _execution_mode(self, request: RunRequest) -> str:
        del request
        return "deterministic"

    def _run_start_extra(self, request: RunRequest) -> dict[str, Any]:
        return {
            "sdk_available": self.sdk_available,
            "offline_mode": request.offline_mode,
            "execution_mode": self._execution_mode(request),
            "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
        }

    def _run_completed_extra(self, request: RunRequest, ranked_results: int) -> dict[str, Any]:
        extra = self._run_start_extra(request)
        extra["ranked_results"] = ranked_results
        return extra

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        plan = build_query_plan(request.query, request.query_type, request.provider)
        yield RuntimeEventPayload(
            event_type=EventType.RUN_STARTED,
            phase="planning",
            progress=5,
            message=f"Starting deterministic {self.runtime_name} research run",
            extra=self._run_start_extra(request),
        )
        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="planning",
            progress=10,
            message=f"{self.planner_name} is building the source-specific query plan",
            agent_name=self.planner_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="planning",
            progress=18,
            message="Created initial todo list",
            artifact_type=ArtifactType.TODO_LIST,
            artifact_name="Research TODOs",
            artifact_text="\n".join(f"- {todo}" for todo in plan.todos),
        )
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="planning",
            progress=22,
            message="Prepared deterministic query plan",
            tool_name="literature.keyword_bundle",
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="planning",
            progress=28,
            message="Saved search plan artifact",
            artifact_type=ArtifactType.SEARCH_PLAN,
            artifact_name="Search Plan",
            artifact_json=plan.model_dump(),
        )

        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="searching",
            progress=34,
            message=f"{self.search_agent_name} is executing the fixed source order",
            agent_name=self.search_agent_name,
        )

        provider_results: list[SearchProviderResult] = []
        for index, source in enumerate(plan.databases):
            source_query = plan.source_queries.get(source, plan.normalized_query)
            base_progress = 36 + index * 8
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_CALLED,
                phase="searching",
                progress=base_progress,
                message=f"Searching {source}",
                tool_name=_source_tool_name(source),
                extra={"query": source_query},
            )
            result = await search_source(
                source,
                source_query,
                api_keys=request.api_keys,
                max_results=6,
                offline_mode=request.offline_mode,
                domain=plan.domain,
            )
            provider_results.append(result)
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="searching",
                progress=min(base_progress + 5, 72),
                message=f"{source} completed with {len(result.studies)} studies",
                tool_name=_source_tool_name(source),
                extra={"error": result.error, "skipped": result.skipped, "count": len(result.studies)},
            )
            yield RuntimeEventPayload(
                event_type=EventType.ARTIFACT_CREATED,
                phase="searching",
                progress=min(base_progress + 6, 74),
                message=f"Captured {source} search results",
                artifact_type=ArtifactType.SEARCH_RESULTS,
                artifact_name=f"{source} Results",
                artifact_json=result.model_dump(),
            )

        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="searching",
            progress=76,
            message="Captured source execution summary",
            artifact_type=ArtifactType.SOURCE_PLAN,
            artifact_name="Source Execution Summary",
            artifact_json={
                "sources": [result.source for result in provider_results],
                "counts": {result.source: len(result.studies) for result in provider_results},
                "errors": {result.source: result.error for result in provider_results if result.error},
            },
        )

        all_studies = flatten_studies(provider_results)
        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="searching",
            progress=78,
            message="Scoring and ranking aggregated studies",
            agent_name=self.search_agent_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="searching",
            progress=80,
            message="Ranking studies with deterministic scoring",
            tool_name="evidence.rank_results",
        )
        ranked = score_and_rank_results(all_studies, context="clinical" if plan.domain == "clinical" else "general")
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_RESULT,
            phase="searching",
            progress=82,
            message=f"Ranked {len(ranked)} studies",
            tool_name="evidence.rank_results",
        )
        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="synthesizing",
            progress=84,
            message=f"{self.synthesis_agent_name} is assembling the deterministic report",
            agent_name=self.synthesis_agent_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="synthesizing",
            progress=86,
            message="Saved ranked evidence artifact",
            artifact_type=ArtifactType.RANKED_RESULTS,
            artifact_name="Ranked Results",
            artifact_json={"studies": [study.model_dump() for study in ranked[:12]]},
        )
        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="verifying",
            progress=88,
            message=f"{self.verifier_name} is checking PubMed identifiers",
            agent_name=self.verifier_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="verifying",
            progress=90,
            message="Running deterministic verification checks",
            tool_name="evidence.verify_results",
        )
        verification = await verify_studies(
            ranked,
            api_keys=request.api_keys,
            offline_mode=request.offline_mode,
            limit=8,
        )
        verification_report = render_verification_report(verification)
        if not ranked:
            verification = empty_verification_summary(
                "No ranked studies were available for identifier verification."
            )
            verification_report = render_verification_report(verification)
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_RESULT,
            phase="verifying",
            progress=93,
            message="Verification checks completed",
            tool_name="evidence.verify_results",
            extra=verification.model_dump(),
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="verifying",
            progress=95,
            message="Saved verification artifact",
            artifact_type=ArtifactType.VERIFICATION_REPORT,
            artifact_name="Verification Report",
            artifact_text=verification_report,
        )
        final_report = render_report(
            query=request.query,
            plan=plan,
            search_results=provider_results,
            ranked_studies=ranked,
            verification=verification,
            provider=request.provider,
            runtime_name=self.runtime_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.REPORT_DELTA,
            phase="synthesizing",
            progress=97,
            message="Report body updated from ranked evidence",
            report_markdown=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="complete",
            progress=100,
            message="Saved final report artifact",
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.RUN_COMPLETED,
            phase="complete",
            progress=100,
            message=f"{self.runtime_name} run completed",
            report_markdown=final_report,
            extra=self._run_completed_extra(request, len(ranked)),
        )


class NativeSDKRuntime(DeterministicRuntime):
    native_agent_name: str = "Native Research Agent"
    max_search_iterations: int = MAX_AGENT_SEARCH_ITERATIONS

    def _execution_mode(self, request: RunRequest) -> str:
        return "deterministic_fallback" if self._should_fallback(request) else "native_sdk"

    def _run_start_extra(self, request: RunRequest) -> dict[str, Any]:
        extra = super()._run_start_extra(request)
        fallback_reason = provider_fallback_reason(self, request)
        if fallback_reason:
            extra["fallback_reason"] = fallback_reason
        return extra

    def _should_fallback(self, request: RunRequest) -> bool:
        return provider_fallback_reason(self, request) is not None

    def _native_start_events(self, request: RunRequest) -> list[RuntimeEventPayload]:
        return [
            RuntimeEventPayload(
                event_type=EventType.RUN_STARTED,
                phase="planning",
                progress=5,
                message=f"Starting native {self.runtime_name} research run",
                extra={
                    "sdk_available": self.sdk_available,
                    "offline_mode": request.offline_mode,
                    "execution_mode": "native_sdk",
                    "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                },
            ),
            RuntimeEventPayload(
                event_type=EventType.AGENT_STARTED,
                phase="planning",
                progress=12,
                message=f"{self.native_agent_name} is guiding search checkpoints",
                agent_name=self.native_agent_name,
            ),
        ]

    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        raise NotImplementedError

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.strip().split())

    def _safe_agent_name(self, suffix: str) -> str:
        sanitized = "".join(
            character if character.isalnum() or character == "_" else "_"
            for character in f"{self.provider}_{suffix}"
        )
        return sanitized if sanitized and not sanitized[0].isdigit() else f"agent_{sanitized}"

    def _compact_study_summary(self, study: ScoredStudy) -> dict[str, Any]:
        abstract = (study.abstract or "").replace("\n", " ").strip()
        return {
            "reference_number": study.reference_number,
            "title": study.title,
            "source": study.source,
            "sources": study.sources,
            "journal": study.journal,
            "publication_year": study.publication_year,
            "doi": study.doi,
            "pmid": study.pmid,
            "evidence_level": study.evidence_level,
            "composite_score": study.composite_score,
            "citation_count": study.citation_count,
            "abstract_excerpt": abstract[:500],
        }

    def _plan_summary_payload(self, plan: QueryPlan) -> dict[str, Any]:
        return {
            "query": plan.query,
            "query_type": plan.query_type,
            "domain": plan.domain,
            "keywords": plan.keywords,
            "databases": plan.databases,
            "source_queries": plan.source_queries,
            "notes": plan.notes,
        }

    def _search_state_payload(
        self,
        *,
        plan: QueryPlan,
        results: list[SearchProviderResult],
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
        iteration: int,
    ) -> dict[str, Any]:
        return {
            "iteration": iteration + 1,
            "plan": self._plan_summary_payload(plan),
            "source_counts": {result.source: len(result.studies) for result in results},
            "source_errors": {result.source: result.error for result in results if result.error},
            "ranked_count": len(ranked),
            "top_ranked_studies": [self._compact_study_summary(study) for study in ranked[:8]],
            "verification": verification.model_dump(),
        }

    def _apply_guidance(
        self,
        plan: QueryPlan,
        *,
        source_queries: dict[str, str],
        note_prefix: str,
        notes: list[str] | None = None,
        summary: str | None = None,
    ) -> QueryPlan:
        updated = plan.model_copy(deep=True)
        allowed_sources = set(updated.databases)
        changed_sources: list[str] = []
        for source, query in source_queries.items():
            normalized = self._normalize_text(query)
            if source not in allowed_sources or not normalized:
                continue
            if updated.source_queries.get(source) != normalized:
                updated.source_queries[source] = normalized
                changed_sources.append(source)
        extra_notes = list(updated.notes)
        if summary:
            extra_notes.append(f"{note_prefix}: {summary}")
        elif changed_sources:
            extra_notes.append(f"{note_prefix}: updated {', '.join(changed_sources)}")
        for note in notes or []:
            normalized_note = self._normalize_text(note)
            if normalized_note:
                extra_notes.append(f"{note_prefix}: {normalized_note}")
        updated.notes = extra_notes
        return updated

    async def _request_search_guidance(
        self,
        request: RunRequest,
        base_plan: QueryPlan,
    ) -> SearchGuidanceOutput:
        instructions = "\n".join(
            [
                "You are refining literature search queries for recall-oriented medical research.",
                "Broaden carefully: prefer simpler terms, synonyms, and less restrictive phrasing.",
                "Only update source_queries for sources that need changes.",
                "Do not add unsupported sources or invent tool results.",
                "Keep the study intent aligned with the original query.",
            ]
        )
        prompt = "\n".join(
            [
                "Original query:",
                request.query,
                "",
                "Deterministic base plan JSON:",
                json.dumps(self._plan_summary_payload(base_plan), indent=2),
                "",
                "Return revised source queries only where a broader or cleaner query is useful.",
            ]
        )
        return await self._run_structured_checkpoint(
            request,
            task_name="search_guidance",
            instructions=instructions,
            prompt=prompt,
            output_model=SearchGuidanceOutput,
        )

    async def _request_rewind_decision(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        results: list[SearchProviderResult],
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
        iteration: int,
    ) -> RewindDecisionOutput:
        instructions = "\n".join(
            [
                "You are deciding whether the literature search should be rewound with adjusted source queries.",
                "Rewind only when another search pass is likely to materially improve coverage or reduce obvious noise.",
                "Reasons to rewind include: too few relevant studies, source failures, poor verification coverage, or queries that are clearly too narrow.",
                "If no rewind is needed, set should_rewind to false and leave source_queries empty.",
                "If rewind is needed, only update source_queries for the affected sources.",
            ]
        )
        prompt = "\n".join(
            [
                "Current search state JSON:",
                json.dumps(
                    self._search_state_payload(
                        plan=plan,
                        results=results,
                        ranked=ranked,
                        verification=verification,
                        iteration=iteration,
                    ),
                    indent=2,
                ),
                "",
                "Decide whether another search cycle is warranted.",
            ]
        )
        return await self._run_structured_checkpoint(
            request,
            task_name="rewind_decision",
            instructions=instructions,
            prompt=prompt,
            output_model=RewindDecisionOutput,
        )

    async def _request_final_synthesis(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        results: list[SearchProviderResult],
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
    ) -> FinalSynthesisOutput:
        instructions = "\n".join(
            [
                "Write a medical evidence report in markdown from the supplied deterministic evidence bundle.",
                "Do not invent citations, PMIDs, or findings that are not present in the input.",
                "Be explicit when evidence is weak, indirect, missing, or contradicted by source failures.",
                "Use sections: Executive Summary, Methods, Ranked Evidence, Verification, References.",
            ]
        )
        prompt = "\n".join(
            [
                "Research state JSON:",
                json.dumps(
                    self._search_state_payload(
                        plan=plan,
                        results=results,
                        ranked=ranked,
                        verification=verification,
                        iteration=max(self.max_search_iterations - 1, 0),
                    ),
                    indent=2,
                ),
                "",
                f"Runtime name: {self.runtime_name}",
                f"Provider: {request.provider}",
                "Return the final report only in the structured schema.",
            ]
        )
        return await self._run_structured_checkpoint(
            request,
            task_name="final_synthesis",
            instructions=instructions,
            prompt=prompt,
            output_model=FinalSynthesisOutput,
        )

    async def _run_search_iteration(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        iteration: int,
    ) -> tuple[list[RuntimeEventPayload], list[SearchProviderResult], list[ScoredStudy], VerificationSummary]:
        events: list[RuntimeEventPayload] = []
        provider_results: list[SearchProviderResult] = []
        progress_base = 34 + iteration * 24
        events.append(
            RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="searching",
            progress=progress_base,
            message=f"{self.search_agent_name} is executing search cycle {iteration + 1}",
            agent_name=self.search_agent_name,
            )
        )

        for index, source in enumerate(plan.databases):
            source_query = plan.source_queries.get(source, plan.normalized_query)
            step_progress = min(progress_base + 2 + index * 3, 52 + iteration * 20)
            events.append(
                RuntimeEventPayload(
                event_type=EventType.TOOL_CALLED,
                phase="searching",
                progress=step_progress,
                message=f"Searching {source} in cycle {iteration + 1}",
                tool_name=_source_tool_name(source),
                extra={"query": source_query, "iteration": iteration + 1},
                )
            )
            result = await search_source(
                source,
                source_query,
                api_keys=request.api_keys,
                max_results=6,
                offline_mode=request.offline_mode,
                domain=plan.domain,
            )
            provider_results.append(result)
            events.append(
                RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="searching",
                progress=min(step_progress + 1, 54 + iteration * 20),
                message=f"{source} completed with {len(result.studies)} studies",
                tool_name=_source_tool_name(source),
                extra={
                    "error": result.error,
                    "skipped": result.skipped,
                    "count": len(result.studies),
                    "iteration": iteration + 1,
                },
                )
            )
            events.append(
                RuntimeEventPayload(
                event_type=EventType.ARTIFACT_CREATED,
                phase="searching",
                progress=min(step_progress + 2, 56 + iteration * 20),
                message=f"Captured {source} search results for cycle {iteration + 1}",
                artifact_type=ArtifactType.SEARCH_RESULTS,
                artifact_name=f"{source} Results (Cycle {iteration + 1})",
                artifact_json=result.model_dump(),
                )
            )

        events.append(
            RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="searching",
            progress=min(progress_base + 14, 60 + iteration * 20),
            message=f"Captured source execution summary for cycle {iteration + 1}",
            artifact_type=ArtifactType.SOURCE_PLAN,
            artifact_name=f"Source Execution Summary (Cycle {iteration + 1})",
            artifact_json={
                "iteration": iteration + 1,
                "sources": [result.source for result in provider_results],
                "counts": {result.source: len(result.studies) for result in provider_results},
                "errors": {result.source: result.error for result in provider_results if result.error},
            },
            )
        )

        all_studies = flatten_studies(provider_results)
        events.append(
            RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="searching",
            progress=min(progress_base + 16, 62 + iteration * 20),
            message=f"Ranking studies for cycle {iteration + 1}",
            tool_name="evidence.rank_results",
            )
        )
        ranked = score_and_rank_results(
            all_studies,
            context="clinical" if plan.domain == "clinical" else "general",
        )
        events.append(
            RuntimeEventPayload(
            event_type=EventType.TOOL_RESULT,
            phase="searching",
            progress=min(progress_base + 18, 64 + iteration * 20),
            message=f"Ranked {len(ranked)} studies in cycle {iteration + 1}",
            tool_name="evidence.rank_results",
            )
        )
        events.append(
            RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="synthesizing",
            progress=min(progress_base + 19, 65 + iteration * 20),
            message=f"Saved ranked evidence artifact for cycle {iteration + 1}",
            artifact_type=ArtifactType.RANKED_RESULTS,
            artifact_name=f"Ranked Results (Cycle {iteration + 1})",
            artifact_json={"studies": [study.model_dump() for study in ranked[:12]]},
            )
        )

        events.append(
            RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="verifying",
            progress=min(progress_base + 20, 66 + iteration * 20),
            message=f"{self.verifier_name} is checking PubMed identifiers for cycle {iteration + 1}",
            agent_name=self.verifier_name,
            )
        )
        events.append(
            RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="verifying",
            progress=min(progress_base + 21, 67 + iteration * 20),
            message=f"Running verification checks for cycle {iteration + 1}",
            tool_name="evidence.verify_results",
            )
        )
        verification = await verify_studies(
            ranked,
            api_keys=request.api_keys,
            offline_mode=request.offline_mode,
            limit=8,
        )
        if not ranked:
            verification = empty_verification_summary(
                "No ranked studies were available for identifier verification."
            )
        events.append(
            RuntimeEventPayload(
            event_type=EventType.TOOL_RESULT,
            phase="verifying",
            progress=min(progress_base + 22, 68 + iteration * 20),
            message=f"Verification checks completed for cycle {iteration + 1}",
            tool_name="evidence.verify_results",
            extra=verification.model_dump(),
            )
        )
        events.append(
            RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="verifying",
            progress=min(progress_base + 23, 69 + iteration * 20),
            message=f"Saved verification artifact for cycle {iteration + 1}",
            artifact_type=ArtifactType.VERIFICATION_REPORT,
            artifact_name=f"Verification Report (Cycle {iteration + 1})",
            artifact_text=render_verification_report(verification),
            )
        )
        return events, provider_results, ranked, verification

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in super().stream_run(request):
                yield event
            return

        for event in self._native_start_events(request):
            yield event

        base_plan = build_query_plan(request.query, request.query_type, request.provider)
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="planning",
            progress=16,
            message="Requesting provider-guided query broadening",
            tool_name="agent.search_guidance",
        )
        try:
            guidance = await asyncio.wait_for(
                self._request_search_guidance(request, base_plan),
                timeout=SEARCH_GUIDANCE_TIMEOUT_SECONDS,
            )
            plan = self._apply_guidance(
                base_plan,
                source_queries=guidance.source_queries,
                note_prefix="Search guidance",
                notes=guidance.notes,
                summary=guidance.strategy_summary,
            )
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="planning",
                progress=20,
                message="Provider returned search guidance",
                tool_name="agent.search_guidance",
                extra=guidance.model_dump(),
            )
        except Exception as exc:
            plan = base_plan
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="planning",
                progress=20,
                message="Provider search guidance failed; using deterministic plan",
                tool_name="agent.search_guidance",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )

        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="planning",
            progress=24,
            message="Created initial todo list",
            artifact_type=ArtifactType.TODO_LIST,
            artifact_name="Research TODOs",
            artifact_text="\n".join(f"- {todo}" for todo in plan.todos),
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="planning",
            progress=28,
            message="Saved search plan artifact",
            artifact_type=ArtifactType.SEARCH_PLAN,
            artifact_name="Search Plan",
            artifact_json=plan.model_dump(),
        )

        current_plan = plan
        final_results: list[SearchProviderResult] = []
        final_ranked: list[ScoredStudy] = []
        final_verification = empty_verification_summary(
            "Verification was not reached in the provider-guided loop."
        )

        for iteration in range(self.max_search_iterations):
            iteration_events, provider_results, ranked, verification = await self._run_search_iteration(
                request,
                plan=current_plan,
                iteration=iteration,
            )
            for event in iteration_events:
                yield event
            final_results = provider_results
            final_ranked = ranked
            final_verification = verification

            if iteration + 1 >= self.max_search_iterations:
                break

            yield RuntimeEventPayload(
                event_type=EventType.TOOL_CALLED,
                phase="evaluating",
                progress=72 + iteration * 10,
                message=f"Requesting rewind decision after cycle {iteration + 1}",
                tool_name="agent.rewind_decision",
            )
            try:
                rewind = await asyncio.wait_for(
                    self._request_rewind_decision(
                        request,
                        plan=current_plan,
                        results=provider_results,
                        ranked=ranked,
                        verification=verification,
                        iteration=iteration,
                    ),
                    timeout=REWIND_DECISION_TIMEOUT_SECONDS,
                )
                yield RuntimeEventPayload(
                    event_type=EventType.TOOL_RESULT,
                    phase="evaluating",
                    progress=74 + iteration * 10,
                    message=f"Provider returned rewind decision after cycle {iteration + 1}",
                    tool_name="agent.rewind_decision",
                    extra=rewind.model_dump(),
                )
            except Exception as exc:
                rewind = RewindDecisionOutput(
                    should_rewind=False,
                    rationale="Provider rewind decision failed; continuing with current evidence.",
                    notes=[f"{type(exc).__name__}: {exc}"],
                )
                yield RuntimeEventPayload(
                    event_type=EventType.TOOL_RESULT,
                    phase="evaluating",
                    progress=74 + iteration * 10,
                    message=f"Provider rewind decision failed after cycle {iteration + 1}",
                    tool_name="agent.rewind_decision",
                    extra=rewind.model_dump(),
                )

            updated_plan = self._apply_guidance(
                current_plan,
                source_queries=rewind.source_queries,
                note_prefix="Rewind decision",
                notes=rewind.notes,
                summary=rewind.rationale,
            )
            if not rewind.should_rewind or updated_plan.source_queries == current_plan.source_queries:
                break

            current_plan = updated_plan
            yield RuntimeEventPayload(
                event_type=EventType.ARTIFACT_CREATED,
                phase="evaluating",
                progress=76 + iteration * 10,
                message=f"Saved rewound search plan for cycle {iteration + 2}",
                artifact_type=ArtifactType.SEARCH_PLAN,
                artifact_name=f"Search Plan (Cycle {iteration + 2})",
                artifact_json=current_plan.model_dump(),
            )

        deterministic_report = render_report(
            query=request.query,
            plan=current_plan,
            search_results=final_results,
            ranked_studies=final_ranked,
            verification=final_verification,
            provider=request.provider,
            runtime_name=self.runtime_name,
        )
        yield RuntimeEventPayload(
            event_type=EventType.TOOL_CALLED,
            phase="synthesizing",
            progress=90,
            message="Requesting provider final synthesis",
            tool_name="agent.final_synthesis",
        )
        try:
            synthesis = await asyncio.wait_for(
                self._request_final_synthesis(
                    request,
                    plan=current_plan,
                    results=final_results,
                    ranked=final_ranked,
                    verification=final_verification,
                ),
                timeout=FINAL_SYNTHESIS_TIMEOUT_SECONDS,
            )
            final_report = synthesis.final_report.strip() or deterministic_report
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="synthesizing",
                progress=93,
                message="Provider final synthesis completed",
                tool_name="agent.final_synthesis",
                extra={"report_length": len(final_report)},
            )
        except Exception as exc:
            final_report = deterministic_report
            yield RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase="synthesizing",
                progress=93,
                message="Provider final synthesis failed; using deterministic report",
                tool_name="agent.final_synthesis",
                extra={"error": f"{type(exc).__name__}: {exc}", "report_length": len(final_report)},
            )

        yield RuntimeEventPayload(
            event_type=EventType.REPORT_DELTA,
            phase="synthesizing",
            progress=97,
            message="Report body updated from provider-guided evidence loop",
            report_markdown=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="complete",
            progress=100,
            message="Saved final report artifact",
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.RUN_COMPLETED,
            phase="complete",
            progress=100,
            message=f"{self.runtime_name} run completed",
            report_markdown=final_report,
            extra={
                "sdk_available": self.sdk_available,
                "offline_mode": request.offline_mode,
                "execution_mode": "native_sdk",
                "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                "ranked_results": len(final_ranked),
            },
        )


class OpenAIRuntime(NativeSDKRuntime):
    provider = "openai"
    runtime_name = "OpenAI Agents SDK"
    sdk_module = "agents"
    planner_name = "OpenAI Planner"
    search_agent_name = "OpenAI Search Agent"
    synthesis_agent_name = "OpenAI Synthesis Agent"
    verifier_name = "OpenAI Verification Agent"
    native_agent_name = "OpenAI MCP Research Agent"

    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        from agents import Agent, Runner
        from agents.agent_output import AgentOutputSchema

        with _temporary_env(_provider_api_env(self.provider, request.api_keys)):
            agent = Agent(
                name=self._safe_agent_name(task_name),
                instructions=instructions,
                model=request.model,
                output_type=AgentOutputSchema(output_model, strict_json_schema=False),
            )
            result = await Runner.run(
                agent,
                prompt,
                max_turns=4,
            )
        return _coerce_model_output(result.final_output, output_model)


# ---------------------------------------------------------------------------
# Anthropic agentic infrastructure
# ---------------------------------------------------------------------------

class _AgenticEventBridge:
    """Bridges claude_agent_sdk hook callbacks to RuntimeEventPayload events.

    Tool-lifecycle hooks push events onto an asyncio.Queue; the main
    ``stream_run`` coroutine yields from the queue to feed the service layer.
    """

    _PHASE_MAP: dict[str, tuple[str, int]] = {
        "mcp__literature__plan_search": ("planning", 12),
        "mcp__literature__suggest_databases": ("planning", 14),
        "mcp__literature__search_pubmed": ("searching", 20),
        "mcp__literature__search_openalex": ("searching", 30),
        "mcp__literature__search_cochrane": ("searching", 40),
        "mcp__literature__search_semantic_scholar": ("searching", 50),
        "mcp__literature__search_scopus": ("searching", 58),
        "mcp__evidence__get_studies": ("ranking", 68),
        "mcp__evidence__finalize_ranking": ("ranking", 75),
        "mcp__evidence__verify_studies": ("verifying", 82),
        "mcp__evidence__synthesize_report": ("synthesizing", 92),
        "mcp__workspace__write_todos": ("planning", 8),
        "mcp__workspace__update_progress": ("planning", 10),
        "mcp__fulltext__fetch_fulltext": ("fulltext", 78),
        "mcp__fulltext__parse_pdf": ("fulltext", 80),
    }

    def __init__(self) -> None:
        self.queue: asyncio.Queue[RuntimeEventPayload | None] = asyncio.Queue()
        self._intermediate: dict[str, Any] = {}
        self._todos: list[str] = []
        self._tool_call_count = 0
        self._result: str | None = None
        # Shared state: search tools write here, evidence tools read from here
        self.search_results: list[SearchProviderResult] = []
        self.ranked_studies: list[ScoredStudy] = []
        self.verification: VerificationSummary | None = None
        self.plan: QueryPlan | None = None
        self._pre_scored: list[ScoredStudy] = []
        self._pdf_urls: dict[int, str] = {}
        self._error: Exception | None = None

    def _phase_for(self, tool_name: str) -> tuple[str, int]:
        if tool_name in self._PHASE_MAP:
            return self._PHASE_MAP[tool_name]
        if tool_name.startswith("search_"):
            return ("searching", 35)
        return ("searching", 50)

    # -- Hook callbacks (conform to HookCallback signature) ------------------

    async def pre_tool_use(  # type: ignore[return]
        self,
        hook_input: Any,
        tool_use_id: str | None,
        context: Any,
    ) -> Any:
        tool_name = hook_input.get("tool_name", "unknown")
        tool_input = hook_input.get("tool_input", {})
        phase, progress = self._phase_for(tool_name)
        self._tool_call_count += 1
        # Verbose logging for debugging
        input_summary = {k: (str(v)[:120] + "..." if len(str(v)) > 120 else v) for k, v in tool_input.items()}
        _log.info(
            "[AGENT CALL #%d] %s  input=%s",
            self._tool_call_count, tool_name, json.dumps(input_summary, default=str),
        )
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.TOOL_CALLED,
                phase=phase,
                progress=min(progress + self._tool_call_count, 97),
                message=f"Agent calling {tool_name}",
                tool_name=tool_name,
                extra={"tool_input": input_summary},
            )
        )
        return {"hookEventName": "PreToolUse"}

    async def post_tool_use(  # type: ignore[return]
        self,
        hook_input: Any,
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        tool_name = hook_input.get("tool_name", "unknown")
        response = hook_input.get("tool_response")
        phase, progress = self._phase_for(tool_name)
        # Verbose logging for debugging
        resp_str = str(response) if response else "<empty>"
        resp_preview = resp_str[:300] + "..." if len(resp_str) > 300 else resp_str
        _log.info(
            "[AGENT RESULT #%d] %s  response_len=%d  preview=%s",
            self._tool_call_count, tool_name, len(resp_str), resp_preview,
        )
        # Stash intermediate results for partial recovery (use namespaced keys)
        short_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name
        if short_name in ("get_studies", "finalize_ranking", "verify_studies", "synthesize_report", "plan_search", "fetch_fulltext"):
            self._intermediate[short_name] = response
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase=phase,
                progress=min(progress + self._tool_call_count + 1, 97),
                message=f"Agent received result from {tool_name}",
                tool_name=tool_name,
                extra={"response_length": len(resp_str)},
            )
        )
        return {"hookEventName": "PostToolUse"}

    # -- Direct calls from workspace tools -----------------------------------

    async def emit_todos(self, items: list[str]) -> None:
        self._todos = list(items)
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.ARTIFACT_CREATED,
                phase="planning",
                progress=8,
                message="Agent created research TODO list",
                artifact_type=ArtifactType.TODO_LIST,
                artifact_name="Research TODOs",
                artifact_text="\n".join(f"- {item}" for item in items),
            )
        )

    async def emit_progress(self, phase: str, message: str) -> None:
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.AGENT_STARTED,
                phase=phase,
                progress=min(10 + self._tool_call_count * 3, 97),
                message=message,
                agent_name="Claude Research Agent",
            )
        )

    # -- Completion ----------------------------------------------------------

    def set_result(self, text: str | None) -> None:
        self._result = text

    def set_error(self, exc: Exception | Any) -> None:
        if isinstance(exc, Exception):
            self._error = exc
        else:
            self._error = RuntimeError(str(exc))


def _build_anthropic_mcp_servers(
    request: RunRequest,
    bridge: _AgenticEventBridge,
) -> dict[str, Any]:
    """Build in-process MCP servers for the Anthropic agentic runtime.

    Returns a dict suitable for ``ClaudeAgentOptions.mcp_servers``.
    Tools use *bridge* as shared state: search tools write results there,
    evidence tools read from there — the agent never passes large JSON blobs.
    """
    from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool

    # -- Literature tools ----------------------------------------------------

    @tool("plan_search", "Build a search plan. Returns keywords, databases, and source queries.", {
        "query": str, "query_type": str,
    })
    async def plan_search_tool(args: dict[str, Any]) -> dict[str, Any]:
        plan = build_query_plan(
            args["query"],
            args.get("query_type", request.query_type),
            request.provider,
        )
        bridge.plan = plan
        return {"content": [{"type": "text", "text": json.dumps(plan.model_dump())}]}

    @tool("suggest_databases", "Suggest database coverage for a research query", {
        "query": str,
    })
    async def suggest_databases_tool(args: dict[str, Any]) -> dict[str, Any]:
        dbs = _suggest_databases(args["query"], request.provider)
        return {"content": [{"type": "text", "text": json.dumps(dbs)}]}

    def _make_search_tool(source: str, name: str, description: str, default_max: int = 8) -> SdkMcpTool[Any]:
        @tool(name, description, {"query": str, "max_results": int})
        async def _search(args: dict[str, Any]) -> dict[str, Any]:
            result = await search_source(
                source,
                args["query"],
                api_keys=request.api_keys,
                max_results=args.get("max_results", default_max),
                offline_mode=request.offline_mode,
                domain="clinical",
            )
            # Store full data in shared state for evidence tools
            bridge.search_results.append(result)
            # Return rich per-study summaries so agent can reason about evidence
            studies_summary = []
            for s in result.studies:
                abstract = (s.abstract or "").replace("\n", " ").strip()
                studies_summary.append({
                    "title": s.title,
                    "journal": s.journal,
                    "year": s.publication_year,
                    "pmid": s.pmid,
                    "doi": s.doi,
                    "evidence_level": s.evidence_level,
                    "citation_count": s.citation_count,
                    "abstract": abstract[:300] + "..." if len(abstract) > 300 else abstract,
                })
            summary = {
                "source": result.source,
                "count": len(result.studies),
                "error": result.error,
                "studies": studies_summary,
            }
            return {"content": [{"type": "text", "text": json.dumps(summary)}]}
        return _search

    search_pubmed = _make_search_tool("PubMed", "search_pubmed", "Search PubMed for medical literature")
    search_openalex = _make_search_tool("OpenAlex", "search_openalex", "Search OpenAlex for open-access academic papers")
    search_cochrane = _make_search_tool("Cochrane", "search_cochrane", "Search Cochrane for systematic reviews", 6)
    search_semantic_scholar = _make_search_tool(
        "Semantic Scholar", "search_semantic_scholar", "Search Semantic Scholar for academic papers",
    )
    search_scopus = _make_search_tool("Scopus", "search_scopus", "Search Scopus for academic citations")

    literature_server = create_sdk_mcp_server("literature", tools=[
        plan_search_tool,
        suggest_databases_tool,
        search_pubmed,
        search_openalex,
        search_cochrane,
        search_semantic_scholar,
        search_scopus,
    ])

    # -- Evidence tools (read from shared state, no JSON args needed) ---------

    @tool("get_studies", "Deduplicate and pre-score ALL collected studies. Returns full details (abstracts, metadata, scores) for your review.", {
        "context": str,
    })
    async def get_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        all_studies = flatten_studies(bridge.search_results)
        if not all_studies:
            return {"content": [{"type": "text", "text": json.dumps({"error": "No studies collected yet. Run search tools first.", "studies": []})}]}
        context = args.get("context", "general")
        pre_scored = score_and_rank_results(all_studies, context=context)
        # Store pre-scored list; agent will reorder via finalize_ranking
        bridge._pre_scored = pre_scored
        studies_out = []
        for s in pre_scored:
            abstract = (s.abstract or "").replace("\n", " ").strip()
            studies_out.append({
                "idx": s.reference_number,
                "title": s.title,
                "abstract": abstract[:500] + "..." if len(abstract) > 500 else abstract,
                "journal": s.journal,
                "year": s.publication_year,
                "pmid": s.pmid,
                "doi": s.doi,
                "authors": s.authors[:3],
                "evidence_level": s.evidence_level,
                "citation_count": s.citation_count,
                "sources": s.sources,
                "pre_score": s.composite_score,
                "score_breakdown": {
                    "evidence": s.evidence_level_score,
                    "citations": s.citation_score,
                    "recency": s.recency_score,
                },
            })
        return {"content": [{"type": "text", "text": json.dumps({
            "total": len(studies_out),
            "context": context,
            "studies": studies_out,
        })}]}

    @tool("finalize_ranking", "Submit your ranking after reviewing the studies from get_studies. Pass ordered indices (best first).", {
        "ranked_indices": list, "rationale": str,
    })
    async def finalize_ranking_tool(args: dict[str, Any]) -> dict[str, Any]:
        pre_scored = getattr(bridge, "_pre_scored", None)
        if not pre_scored:
            return {"content": [{"type": "text", "text": json.dumps({"error": "Call get_studies first."})}]}
        idx_map = {s.reference_number: s for s in pre_scored}
        indices = args.get("ranked_indices", [])
        # Build final ranked list in the order the agent chose
        ranked: list[ScoredStudy] = []
        seen: set[int] = set()
        for i, idx in enumerate(indices, start=1):
            idx = int(idx)
            if idx in idx_map and idx not in seen:
                study = idx_map[idx].model_copy(deep=True)
                study.reference_number = i
                ranked.append(study)
                seen.add(idx)
        # Append any the agent didn't mention (lower priority)
        for s in pre_scored:
            if s.reference_number not in seen:
                study = s.model_copy(deep=True)
                study.reference_number = len(ranked) + 1
                ranked.append(study)
        bridge.ranked_studies = ranked
        return {"content": [{"type": "text", "text": json.dumps({
            "status": "ok",
            "total_ranked": len(ranked),
            "top_5": [{"rank": s.reference_number, "title": s.title} for s in ranked[:5]],
            "rationale": args.get("rationale", ""),
        })}]}

    @tool("verify_studies", "Verify PMIDs of the ranked studies against PubMed. Reads from shared state.", {})
    async def verify_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        if not bridge.ranked_studies:
            return {"content": [{"type": "text", "text": json.dumps({"error": "No ranked studies. Call finalize_ranking first."})}]}
        summary = await verify_studies(
            bridge.ranked_studies,
            api_keys=request.api_keys,
            offline_mode=request.offline_mode,
            limit=8,
        )
        bridge.verification = summary
        return {"content": [{"type": "text", "text": json.dumps({"verified": summary.verified_pmids, "missing": summary.missing_pmids, "markdown": render_verification_report(summary)})}]}

    @tool("synthesize_report", "Generate the final markdown report from ALL collected data. Reads from shared state.", {})
    async def synthesize_report_tool(args: dict[str, Any]) -> dict[str, Any]:
        plan = bridge.plan or build_query_plan(request.query, request.query_type, request.provider)
        verification = bridge.verification or empty_verification_summary("Verification was not run.")
        report = render_report(
            query=request.query,
            plan=plan,
            search_results=bridge.search_results,
            ranked_studies=bridge.ranked_studies,
            verification=verification,
            provider=request.provider,
            runtime_name="Anthropic Agent SDK",
        )
        bridge._intermediate["synthesize_report"] = report
        return {"content": [{"type": "text", "text": report}]}

    evidence_server = create_sdk_mcp_server("evidence", tools=[
        get_studies_tool,
        finalize_ranking_tool,
        verify_studies_tool,
        synthesize_report_tool,
    ])

    # -- Workspace tools -----------------------------------------------------

    @tool("write_todos", "Create a research TODO list to plan the workflow", {
        "items": list,
    })
    async def write_todos_tool(args: dict[str, Any]) -> dict[str, Any]:
        items = [str(item) for item in args.get("items", [])]
        await bridge.emit_todos(items)
        return {"content": [{"type": "text", "text": json.dumps({"status": "ok", "count": len(items)})}]}

    @tool("update_progress", "Signal a phase transition or progress update to the user", {
        "phase": str, "message": str,
    })
    async def update_progress_tool(args: dict[str, Any]) -> dict[str, Any]:
        await bridge.emit_progress(args["phase"], args["message"])
        return {"content": [{"type": "text", "text": json.dumps({"status": "ok"})}]}

    workspace_server = create_sdk_mcp_server("workspace", tools=[
        write_todos_tool,
        update_progress_tool,
    ])

    # -- Fulltext tools (unpywall + opendataloader-pdf) -----------------------

    _EBM_HIGH_EVIDENCE = {"Level I", "Level II"}

    @tool("fetch_fulltext", "Look up free full-text PDFs via Unpaywall + PMC for Level I & II ranked studies (parallel). Call AFTER finalize_ranking.", {})
    async def fetch_fulltext_tool(args: dict[str, Any]) -> dict[str, Any]:
        import asyncio as _aio
        candidates = [
            s for s in bridge.ranked_studies
            if s.evidence_level in _EBM_HIGH_EVIDENCE and s.doi and s.reference_number is not None
        ]
        if not candidates:
            return {"content": [{"type": "text", "text": json.dumps({"error": "No Level I/II studies with DOIs found."})}]}

        try:
            from unpywall.utils import UnpywallCredentials
            from unpywall import Unpywall
            UnpywallCredentials(POLITE_EMAIL)
            has_unpywall = True
        except ImportError:
            has_unpywall = False

        found_ranks: dict[int, dict[str, Any]] = {}
        unpywall_hits = 0
        pmc_hits = 0

        # Pass 1: Parallel Unpaywall lookup (10 concurrent)
        if has_unpywall:
            sem = _aio.Semaphore(10)

            async def _lookup(s: ScoredStudy) -> None:
                nonlocal unpywall_hits
                rank = s.reference_number
                if rank is None:
                    return
                async with sem:
                    try:
                        pdf_link = await _aio.to_thread(Unpywall.get_pdf_link, s.doi)
                        if pdf_link:
                            found_ranks[rank] = {
                                "rank": rank, "title": s.title,
                                "doi": s.doi, "pmid": s.pmid,
                                "evidence_level": s.evidence_level,
                                "pdf_url": pdf_link, "source": "unpaywall",
                            }
                            unpywall_hits += 1
                    except Exception:
                        pass

            await _aio.gather(*[_lookup(s) for s in candidates])

        # Pass 2: PMC for remaining Level I/II studies with PMIDs
        remaining = [s for s in candidates if s.pmid and s.reference_number not in found_ranks]
        if remaining:
            ids_param = ",".join(s.pmid for s in remaining if s.pmid)
            pmid_to_pmcid: dict[str, str] = {}
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True) as client:
                    resp = await client.get(
                        "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                        params={"ids": ids_param, "format": "json", "tool": "medical-deep-research", "email": POLITE_EMAIL},
                    )
                    resp.raise_for_status()
                for r in resp.json().get("records", []):
                    if r.get("pmcid") and r.get("pmid"):
                        pmid_to_pmcid[r["pmid"]] = r["pmcid"]
            except Exception as exc:
                _log.info("[FULLTEXT] PMC ID converter failed: %s", exc)

            # OA service lookup (parallel, 5 concurrent)
            sem_pmc = _aio.Semaphore(5)

            async def _pmc_lookup(s: ScoredStudy) -> None:
                nonlocal pmc_hits
                rank = s.reference_number
                if rank is None or not s.pmid:
                    return
                pmcid = pmid_to_pmcid.get(s.pmid)
                if not pmcid or rank in found_ranks:
                    return
                async with sem_pmc:
                    try:
                        import xml.etree.ElementTree as _ET
                        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True) as client:
                            resp = await client.get(
                                "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
                                params={"id": pmcid},
                            )
                            resp.raise_for_status()
                        root = _ET.fromstring(resp.text)
                        tgz_href = None
                        for link in root.findall(".//link"):
                            if link.attrib.get("format") == "tgz":
                                tgz_href = link.attrib.get("href")
                                break
                        if tgz_href:
                            if tgz_href.startswith("ftp://"):
                                tgz_href = tgz_href.replace("ftp://ftp.ncbi.nlm.nih.gov/", "https://ftp.ncbi.nlm.nih.gov/")
                            found_ranks[rank] = {
                                "rank": rank, "title": s.title,
                                "doi": s.doi, "pmid": s.pmid, "pmcid": pmcid,
                                "evidence_level": s.evidence_level,
                                "pdf_url": tgz_href, "source": "pmc",
                            }
                            pmc_hits += 1
                    except Exception as exc:
                        _log.info("[FULLTEXT] PMC OA failed for %s: %s", pmcid, exc)

            await _aio.gather(*[_pmc_lookup(s) for s in remaining])

        bridge._pdf_urls = {r["rank"]: r["pdf_url"] for r in found_ranks.values()}
        available = sorted(found_ranks.values(), key=lambda r: r["rank"])
        total_I_II = len(candidates)
        _log.info("[FULLTEXT] %d PDFs found (unpaywall=%d, pmc=%d) from %d Level I/II studies",
                  len(available), unpywall_hits, pmc_hits, total_I_II)
        return {"content": [{"type": "text", "text": json.dumps({
            "level_I_II_studies": total_I_II,
            "pdfs_found": len(available),
            "unpaywall_hits": unpywall_hits,
            "pmc_hits": pmc_hits,
            "available": available,
        })}]}

    @tool("parse_pdf", "Download and parse a full-text PDF to markdown. Call AFTER fetch_fulltext.", {
        "rank": int,
    })
    async def parse_pdf_tool(args: dict[str, Any]) -> dict[str, Any]:
        import asyncio as _aio
        import io
        import tarfile
        import tempfile
        rank = args.get("rank", 1)
        pdf_urls = getattr(bridge, "_pdf_urls", {})
        study = next((s for s in bridge.ranked_studies if s.reference_number == rank), None)
        title = study.title if study else f"Study #{rank}"
        doi = study.doi if study else None

        pdf_bytes: bytes | None = None
        source = "none"

        # Strategy 1: PMC tgz package (most reliable for OA papers)
        url = pdf_urls.get(rank, "")
        if url.endswith(".tar.gz"):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name.endswith(".pdf"):
                            f = tar.extractfile(member)
                            if f:
                                pdf_bytes = f.read()
                                source = "pmc_tgz"
                                _log.info("[PARSE_PDF] Extracted %d bytes from PMC tgz for rank %d", len(pdf_bytes), rank)
                            break
            except Exception as exc:
                _log.info("[PARSE_PDF] PMC tgz extraction failed for rank %d: %s", rank, exc)

        # Strategy 2: unpywall download_pdf_handle
        if not pdf_bytes and doi:
            try:
                from unpywall.utils import UnpywallCredentials
                from unpywall import Unpywall
                UnpywallCredentials(POLITE_EMAIL)
                handle = await _aio.to_thread(Unpywall.download_pdf_handle, doi)
                if handle:
                    raw = handle.read()
                    if raw[:5] == b"%PDF-":
                        pdf_bytes = raw
                        source = "unpywall"
                        _log.info("[PARSE_PDF] Downloaded %d bytes via unpywall for rank %d", len(pdf_bytes), rank)
            except Exception as exc:
                _log.info("[PARSE_PDF] unpywall download failed for rank %d: %s", rank, exc)

        # Strategy 3: direct URL (for non-tgz Unpaywall links)
        if not pdf_bytes and url and not url.endswith(".tar.gz"):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; MedicalDeepResearch/1.0)"},
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if resp.content[:5] == b"%PDF-":
                        pdf_bytes = resp.content
                        source = "direct_url"
                        _log.info("[PARSE_PDF] Downloaded %d bytes via direct URL for rank %d", len(pdf_bytes), rank)
            except Exception as exc:
                _log.info("[PARSE_PDF] Direct URL failed for rank %d: %s", rank, exc)

        if not pdf_bytes:
            return {"content": [{"type": "text", "text": json.dumps({"error": f"Could not download PDF for rank {rank}", "title": title})}]}

        # Write to temp file and parse with opendataloader-pdf
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            pdf_path = f.name

        text = ""
        try:
            import opendataloader_pdf
            import glob as _glob
            output_dir = tempfile.mkdtemp()
            await _aio.to_thread(
                opendataloader_pdf.convert,
                input_path=[pdf_path],
                output_dir=output_dir,
                format="markdown",
            )
            md_files = _glob.glob(f"{output_dir}/**/*.md", recursive=True)
            if md_files:
                with open(md_files[0]) as mf:
                    text = mf.read()
            _log.info("[PARSE_PDF] Parsed %d chars markdown for rank %d via opendataloader-pdf (source=%s)", len(text), rank, source)
        except ImportError:
            text = f"[opendataloader-pdf not installed. PDF: {len(pdf_bytes)} bytes from {source}.]"
        except Exception as exc:
            text = f"[PDF parse error: {exc}. PDF: {len(pdf_bytes)} bytes from {source}.]"
        finally:
            import os as _os
            try:
                _os.unlink(pdf_path)
            except OSError:
                pass

        if len(text) > 8000:
            text = text[:8000] + f"\n\n[... truncated, {len(text)} chars total]"

        return {"content": [{"type": "text", "text": json.dumps({
            "rank": rank, "title": title, "source": source,
            "text_length": len(text), "fulltext": text,
        })}]}

    fulltext_server = create_sdk_mcp_server("fulltext", tools=[
        fetch_fulltext_tool,
        parse_pdf_tool,
    ])

    return {
        "literature": literature_server,
        "evidence": evidence_server,
        "workspace": workspace_server,
        "fulltext": fulltext_server,
    }


def _anthropic_agentic_system_prompt(request: RunRequest) -> str:
    """Build the system prompt for the Claude agentic research session."""
    offline_note = (
        "\n\nOFFLINE MODE IS ENABLED. All search tools will return empty/mock results. "
        "Acknowledge this limitation in your report."
        if request.offline_mode
        else ""
    )
    return f"""\
You are an autonomous medical literature research agent. Conduct a literature \
review and produce a markdown report.

## Tools

**Planning**: plan_search, suggest_databases, write_todos, update_progress
**Search** (one call each): search_pubmed, search_openalex, search_cochrane, search_semantic_scholar, search_scopus
**Evidence** (reads from shared state — NO large JSON arguments needed):
- get_studies(context) — deduplicates and pre-scores all collected studies, returns full details for YOUR review
- finalize_ranking(ranked_indices, rationale) — submit your ranking. Pass indices best-first.
- verify_studies() — verifies PMIDs of ranked studies
- synthesize_report() — renders final report from all collected data
**Fulltext** (call AFTER finalize_ranking):
- fetch_fulltext() — queries Unpaywall + PubMed Central for free PDFs across ALL ranked studies
- parse_pdf(rank) — downloads and parses a specific study's PDF to extract full text

## Workflow (follow exactly)

1. Call `plan_search` with the query.
2. Call search tools (one per database, use queries from the plan). Search 3-4 databases.
3. Call `get_studies` with context="clinical" or "general". Review abstracts, assess relevance and evidence quality.
4. Call `finalize_ranking` with your ordered list of study indices (best first) and rationale.
5. Call `fetch_fulltext` to find free PDFs across all ranked studies (Unpaywall + PMC).
6. Call `parse_pdf` for 1-3 studies that have PDFs available — read the full text to deepen your understanding.
7. Call `verify_studies` to validate PMIDs.
8. Call `synthesize_report` to render the final report. Include its output in your final message.

Do NOT pass study data as arguments — tools read from shared state.
Do NOT repeat searches. One call per database, then move forward.

## Rules

- ONLY cite studies returned by search tools. NEVER invent PMIDs, DOIs, or findings.
- Your final message must contain the complete report from synthesize_report.

## Query

- **Query**: {request.query}
- **Type**: {request.query_type}
- **Language**: {request.language}{offline_note}
"""


class AnthropicRuntime(NativeSDKRuntime):
    provider = "anthropic"
    runtime_name = "Anthropic Agent SDK"
    sdk_module = "claude_agent_sdk"
    planner_name = "Claude Planner"
    search_agent_name = "Claude Search Agent"
    synthesis_agent_name = "Claude Synthesis Agent"
    verifier_name = "Claude Verification Agent"
    native_agent_name = "Claude MCP Research Agent"

    # -- Agentic stream_run (replaces 3-checkpoint pattern) ------------------

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        # Fallback to deterministic if SDK / credentials unavailable
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return

        from claude_agent_sdk import ClaudeAgentOptions, query
        from claude_agent_sdk.types import HookMatcher

        bridge = _AgenticEventBridge()
        mcp_servers = _build_anthropic_mcp_servers(request, bridge)

        yield RuntimeEventPayload(
            event_type=EventType.RUN_STARTED,
            phase="planning",
            progress=5,
            message=f"Starting agentic {self.runtime_name} research run",
            extra={
                "sdk_available": self.sdk_available,
                "offline_mode": request.offline_mode,
                "execution_mode": "native_sdk_agentic",
                "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
            },
        )
        yield RuntimeEventPayload(
            event_type=EventType.AGENT_STARTED,
            phase="planning",
            progress=7,
            message=f"{self.native_agent_name} is autonomously driving the research workflow",
            agent_name=self.native_agent_name,
        )

        options = ClaudeAgentOptions(
            tools=[],  # Disable built-in Claude Code tools; only MCP tools
            model=request.model,
            mcp_servers=mcp_servers,
            allowed_tools=[
                # MCP tools are namespaced as mcp__{server}__{tool}
                "mcp__literature__plan_search", "mcp__literature__suggest_databases",
                "mcp__literature__search_pubmed", "mcp__literature__search_openalex",
                "mcp__literature__search_cochrane", "mcp__literature__search_semantic_scholar",
                "mcp__literature__search_scopus",
                "mcp__evidence__get_studies", "mcp__evidence__finalize_ranking",
                "mcp__evidence__verify_studies",
                "mcp__evidence__synthesize_report",
                "mcp__fulltext__fetch_fulltext", "mcp__fulltext__parse_pdf",
                "mcp__workspace__write_todos", "mcp__workspace__update_progress",
            ],
            hooks={
                "PreToolUse": [HookMatcher(hooks=[bridge.pre_tool_use])],  # type: ignore[list-item]
                "PostToolUse": [HookMatcher(hooks=[bridge.post_tool_use])],  # type: ignore[list-item]
            },
            system_prompt=_anthropic_agentic_system_prompt(request),
            max_turns=ANTHROPIC_AGENTIC_MAX_TURNS,
            permission_mode="dontAsk",
            cwd=str(REPO_ROOT),
            env=_provider_api_env(self.provider, request.api_keys),
        )

        user_prompt = (
            f"Conduct a thorough literature review for the following query:\n\n"
            f"{request.query}\n\n"
            f"Query type: {request.query_type}\n"
            f"Follow your recommended workflow: plan → search → rank → verify → synthesize.\n"
            f"Provide the complete markdown report in your final response."
        )

        # Run agent in a background task; yield events from bridge queue
        agent_task = asyncio.create_task(
            self._run_agent_task(query, user_prompt, options, bridge)
        )

        # Yield events as the agent calls tools
        while True:
            queued: RuntimeEventPayload | None = await bridge.queue.get()
            if queued is None:
                break
            yield queued

        # Await the task to surface exceptions
        try:
            await agent_task
        except Exception as exc:
            _log.warning("Anthropic agentic task error: %s", exc)
            bridge.set_error(exc)

        # Extract final report
        final_report = bridge._result
        if not final_report or not final_report.strip():
            # Partial recovery from intermediate tool results
            final_report = self._recover_report_from_bridge(request, bridge)

        yield RuntimeEventPayload(
            event_type=EventType.REPORT_DELTA,
            phase="synthesizing",
            progress=97,
            message="Report assembled from agentic research workflow",
            report_markdown=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="complete",
            progress=100,
            message="Saved final report artifact",
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        )
        yield RuntimeEventPayload(
            event_type=EventType.RUN_COMPLETED,
            phase="complete",
            progress=100,
            message=f"{self.runtime_name} agentic run completed",
            report_markdown=final_report,
            extra={
                "sdk_available": self.sdk_available,
                "offline_mode": request.offline_mode,
                "execution_mode": "native_sdk_agentic",
                "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                "tool_calls": bridge._tool_call_count,
                "had_error": bridge._error is not None,
            },
        )

    async def _run_agent_task(
        self,
        query_fn: Any,
        prompt: str,
        options: Any,
        bridge: _AgenticEventBridge,
    ) -> None:
        """Execute the Claude agent query with a timeout; push sentinel when done."""
        try:
            from claude_agent_sdk.types import ResultMessage

            final_text: str | None = None

            async def _inner() -> None:
                nonlocal final_text
                async for message in query_fn(prompt=prompt, options=options):
                    if not isinstance(message, ResultMessage):
                        continue
                    if message.is_error:
                        details = [*(message.errors or [])]
                        if message.result:
                            details.append(message.result)
                        raise RuntimeError(
                            "; ".join(d for d in details if d)
                            or "Anthropic Agent SDK returned an error."
                        )
                    if message.result:
                        final_text = message.result

            await asyncio.wait_for(_inner(), timeout=ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_result(final_text)
        except asyncio.TimeoutError:
            _log.warning("Anthropic agentic run timed out after %ss", ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_error(TimeoutError(f"Agent timed out after {ANTHROPIC_AGENTIC_TIMEOUT_SECONDS}s"))
        except Exception as exc:
            _log.warning("Anthropic agentic run failed: %s", exc)
            bridge.set_error(exc)
        finally:
            await bridge.queue.put(None)

    def _recover_report_from_bridge(
        self,
        request: RunRequest,
        bridge: _AgenticEventBridge,
    ) -> str:
        """Build a report from whatever the agent produced via shared state."""
        # If synthesize_report was called, use its output directly
        synth_data = bridge._intermediate.get("synthesize_report")
        if synth_data and isinstance(synth_data, str) and synth_data.strip():
            return synth_data

        # Otherwise build deterministic report from bridge shared state
        plan = bridge.plan or build_query_plan(request.query, request.query_type, request.provider)
        verification = bridge.verification or empty_verification_summary(
            "Verification was incomplete due to agent timeout or error."
        )

        return render_report(
            query=request.query,
            plan=plan,
            search_results=bridge.search_results,
            ranked_studies=bridge.ranked_studies,
            verification=verification,
            provider=request.provider,
            runtime_name=f"{self.runtime_name} (partial recovery)",
        )


class GoogleRuntime(NativeSDKRuntime):
    provider = "google"
    runtime_name = "Google ADK"
    sdk_module = "google.adk"
    planner_name = "ADK Planner"
    search_agent_name = "ADK Search Workflow"
    synthesis_agent_name = "ADK Synthesis Workflow"
    verifier_name = "ADK Verification Workflow"
    native_agent_name = "AdkMcpResearchAgent"

    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types as genai_types
        output: TModel | None = None
        output_key = f"{task_name}_output"

        with _temporary_env(_provider_api_env(self.provider, request.api_keys)):
            agent = Agent(
                name=self._safe_agent_name(task_name),
                description=f"{self.runtime_name} structured {task_name}",
                model=request.model,
                instruction=instructions,
                tools=[],
                output_schema=output_model,
                output_key=output_key,
            )
            session_service = InMemorySessionService()
            runner = Runner(
                agent=agent,
                app_name="MedicalDeepResearch",
                session_service=session_service,
                auto_create_session=True,
            )

            async for event in runner.run_async(
                user_id=request.run_id,
                session_id=f"{request.run_id}-{task_name}",
                new_message=genai_types.UserContent(
                    parts=[genai_types.Part(text=prompt)]
                ),
            ):
                candidate = event.actions.state_delta.get(output_key)
                if candidate is not None:
                    output = _coerce_model_output(candidate, output_model)
                elif event.is_final_response():
                    text = _google_text_from_event(event)
                    if text:
                        output = _coerce_model_output(text, output_model)

        if output is None:
            raise RuntimeError(f"Google ADK did not return a structured {task_name} result.")
        return output


def build_runtime(provider: str) -> ResearchRuntime:
    if provider == "anthropic":
        return AnthropicRuntime()
    if provider == "google":
        return GoogleRuntime()
    return OpenAIRuntime()


ScriptedRuntime = DeterministicRuntime
