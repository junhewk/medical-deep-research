from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from contextlib import contextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, TypeVar

from pydantic import BaseModel
from sqlmodel import Field

from .models import ArtifactType, EventType, RunRequest, RuntimeEventPayload
from .provider_config import (
    DEEPSEEK_BASE_URL,
    deepseek_api_key,
    deepseek_reasoning_effort,
    deepseek_thinking_body,
    local_base_url,
    normalize_model_id,
)
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
from .progress import ProgressTracker
from .research.models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary
from .agentic_tools import (
    AgenticEventBridge,
    MAX_REPORT_STUDIES,
    STUDY_PAGE_SIZE,
    TOOL_DESCRIPTIONS,
    agentic_system_prompt,
    recover_report_from_bridge,
    report_quality_issues,
    tool_appraise_evidence,
    tool_await_user_pdfs,
    tool_browse_studies,
    tool_fetch_fulltext,
    tool_finalize_ranking,
    tool_get_studies,
    tool_parse_pdf,
    tool_plan_search,
    tool_screen_studies,
    tool_search,
    tool_snowball,
    tool_suggest_databases,
    tool_submit_report,
    tool_synthesize_report,
    tool_translate_report,
    tool_update_progress,
    tool_verify_studies,
    tool_write_todos,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]
OPENAI_MCP_TIMEOUT_SECONDS = 20.0
GOOGLE_MCP_TIMEOUT_SECONDS = 20.0
LITERATURE_TOOL_FILTER = ["aggregate_search"]
EVIDENCE_TOOL_FILTER = ["rank_results", "verify_results"]
MAX_AGENT_SEARCH_ITERATIONS = 2
DEFAULT_SEARCH_RESULTS_PER_SOURCE = 15
MAX_AGENT_SEARCH_RESULTS_PER_SOURCE = 25
SEARCH_GUIDANCE_TIMEOUT_SECONDS = 20.0
SCREENING_TIMEOUT_SECONDS = 20.0
REWIND_DECISION_TIMEOUT_SECONDS = 15.0
APPRAISAL_TIMEOUT_SECONDS = 30.0
FINAL_SYNTHESIS_TIMEOUT_SECONDS = 25.0
ANTHROPIC_AGENTIC_TIMEOUT_SECONDS = 300.0
ANTHROPIC_AGENTIC_MAX_TURNS = 25
LOCAL_AGENTIC_TIMEOUT_SECONDS = 600.0
TModel = TypeVar("TModel", bound=BaseModel)
_log = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _ev(
    tracker: ProgressTracker,
    event_type: EventType,
    phase: str,
    message: str,
    *,
    complete: bool = False,
    **kwargs: Any,
) -> RuntimeEventPayload:
    """Build an event whose phase label and percent come from the tracker."""
    if complete:
        label = tracker.phase_label(phase)
        progress = tracker.complete()
    else:
        label, _ = tracker.enter(phase)
        progress = tracker.advance()
    return RuntimeEventPayload(
        event_type=event_type,
        phase=label,
        progress=progress,
        message=message,
        **kwargs,
    )


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


class ScreeningExclusion(BaseModel):
    reference_number: int
    reason: str


class ScreeningOutput(BaseModel):
    included_reference_numbers: list[int] = Field(default_factory=list)
    exclusions: list[ScreeningExclusion] = Field(default_factory=list)
    rationale: str = ""


class AppraisedFinding(BaseModel):
    finding: str
    certainty: str  # High | Moderate | Low | Very Low
    rationale: str = ""
    reference_numbers: list[int] = Field(default_factory=list)


class AppraisalOutput(BaseModel):
    findings: list[AppraisedFinding] = Field(default_factory=list)
    overall_note: str = ""


class FinalSynthesisOutput(BaseModel):
    final_report: str


@dataclass
class _IterationResult:
    events: list[RuntimeEventPayload]
    provider_results: list[SearchProviderResult]
    ranked: list[ScoredStudy]
    verification: VerificationSummary
    screening: dict[str, Any] | None = None
    appraisal: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


class ProviderDiagnostics(BaseModel):
    provider: str
    runtime_name: str
    runtime_engine: str | None = None
    default_model: str | None = None
    sdk_available: bool
    offline_mode: bool
    provider_credentials_present: bool
    search_credentials_present: dict[str, bool] = Field(default_factory=dict)
    active_execution_path: str
    fallback_reason: str | None = None


def _format_exception(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message}"


def _trim_diagnostic_text(text: str | None, *, max_chars: int = 2000) -> str | None:
    if not text:
        return None
    stripped = str(text).strip()
    if not stripped:
        return None
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


def _exception_diagnostics(exc: Exception | None) -> dict[str, Any]:
    if exc is None:
        return {}
    diagnostics: dict[str, Any] = {
        "sdk_error_type": type(exc).__name__,
    }
    exit_code = getattr(exc, "exit_code", None)
    if exit_code is not None:
        diagnostics["sdk_exit_code"] = exit_code
    stderr = _trim_diagnostic_text(getattr(exc, "stderr", None))
    if stderr:
        diagnostics["sdk_stderr"] = stderr
    return diagnostics


def _agentic_failure_diagnostics(bridge: AgenticEventBridge) -> dict[str, Any]:
    diagnostics = _exception_diagnostics(bridge._error)
    stderr_tail = _trim_diagnostic_text(bridge._intermediate.get("sdk_stderr_tail"))
    if stderr_tail:
        diagnostics["sdk_stderr_tail"] = stderr_tail
    return diagnostics


class ResearchRuntime(ABC):
    provider: str
    runtime_name: str
    sdk_module: str | None = None
    runtime_engine: str | None = None

    @property
    def sdk_available(self) -> bool:
        if not self.sdk_module:
            return False
        try:
            return importlib.util.find_spec(self.sdk_module) is not None
        except (ModuleNotFoundError, ValueError):
            return False

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
    if provider == "deepseek":
        api_key = deepseek_api_key(api_keys)
        return {"DEEPSEEK_API_KEY": api_key} if api_key else {}
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
    ncbi = (api_keys.get("ncbi") or os.getenv("MDR_NCBI_API_KEY") or "").strip()
    scopus = (api_keys.get("scopus") or os.getenv("MDR_SCOPUS_API_KEY") or "").strip()
    semantic_scholar = (
        api_keys.get("semantic_scholar")
        or api_keys.get("semanticscholar")
        or os.getenv("MDR_SEMANTIC_SCHOLAR_API_KEY")
        or ""
    )
    semantic_scholar = semantic_scholar.strip()
    if ncbi:
        env["MDR_NCBI_API_KEY"] = ncbi
    if scopus:
        env["MDR_SCOPUS_API_KEY"] = scopus
    if semantic_scholar:
        env["MDR_SEMANTIC_SCHOLAR_API_KEY"] = semantic_scholar
    return env


def _search_credentials_present(api_keys: dict[str, str]) -> dict[str, bool]:
    search_credentials = _search_api_env(api_keys)
    return {
        "ncbi": "MDR_NCBI_API_KEY" in search_credentials,
        "scopus": "MDR_SCOPUS_API_KEY" in search_credentials,
        "semantic_scholar": "MDR_SEMANTIC_SCHOLAR_API_KEY" in search_credentials,
    }


def _has_native_credentials(provider: str, api_keys: dict[str, str]) -> bool:
    if provider == "local":
        return True
    return bool(_provider_api_env(provider, api_keys))


def _legacy_claude_sdk_dependency_reason() -> str | None:
    if os.name == "nt":
        configured = os.getenv("CLAUDE_CODE_GIT_BASH_PATH")
        candidates = [
            configured,
            shutil.which("bash"),
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ]
        if any(candidate and Path(candidate).exists() for candidate in candidates):
            return None
        return (
            "Legacy Claude SDK mode requires Git Bash on Windows. Install Git for Windows "
            "or set CLAUDE_CODE_GIT_BASH_PATH to bash.exe."
        )
    if shutil.which("git"):
        return None
    return "Legacy Claude SDK mode requires Git on PATH."


def provider_fallback_reason(runtime: ResearchRuntime, request: RunRequest) -> str | None:
    if request.offline_mode:
        return "Offline mode is enabled."
    if not runtime.sdk_available:
        return f"{runtime.runtime_name} is not installed."
    if runtime.runtime_engine == "claude_sdk_legacy":
        dependency_reason = _legacy_claude_sdk_dependency_reason()
        if dependency_reason:
            return dependency_reason
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
        runtime_engine=runtime.runtime_engine,
        default_model=default_model,
        sdk_available=runtime.sdk_available,
        offline_mode=offline_mode,
        provider_credentials_present=provider_credentials_present,
        search_credentials_present=_search_credentials_present(api_keys),
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


def _message_content_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part.strip()).strip()
    return ""


def _langchain_final_text(result: Any) -> str | None:
    messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
    if messages:
        for message in reversed(list(messages)):
            text = _message_content_text(message)
            if text:
                return text
    final_output = result.get("final_output") if isinstance(result, dict) else getattr(result, "final_output", None)
    if isinstance(final_output, str) and final_output.strip():
        return final_output.strip()
    if isinstance(result, str) and result.strip():
        return result.strip()
    return None


class _ReportSubmitted(BaseException):
    """Internal control-flow sentinel used to stop LangChain after accepted submit_report."""


class _ReportRejected(Exception):
    """Raised when repeated report quality failures should stop the agent loop."""


class _ReportRecoveryRequested(BaseException):
    """Stop a local agent after a usable rejected draft and recover deterministically."""


def _anthropic_cached_system_prompt(system_prompt: str) -> Any:
    """Wrap the stable Anthropic system prompt in an ephemeral cache block."""
    from langchain_core.messages import SystemMessage

    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


class DeterministicRuntime(ResearchRuntime):
    planner_name: str = "Planner"
    search_agent_name: str = "Search Agent"
    synthesis_agent_name: str = "Synthesis Agent"
    verifier_name: str = "Verification Agent"
    # Pre-seeded tracker so a mid-stream fallback continues from the percent
    # already shown to the user instead of regressing to 0.
    _seed_tracker: ProgressTracker | None = None

    def _execution_mode(self, request: RunRequest) -> str:
        del request
        return "deterministic"

    def _run_start_extra(self, request: RunRequest) -> dict[str, Any]:
        return {
            "sdk_available": self.sdk_available,
            "offline_mode": request.offline_mode,
            "execution_mode": self._execution_mode(request),
            "runtime_engine": self.runtime_engine,
            "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
            "search_credentials_present": _search_credentials_present(request.api_keys),
        }

    def _run_completed_extra(self, request: RunRequest, ranked_results: int) -> dict[str, Any]:
        extra = self._run_start_extra(request)
        extra["ranked_results"] = ranked_results
        return extra

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        tracker = getattr(self, "_seed_tracker", None) or ProgressTracker()
        plan = build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
        yield _ev(
            tracker,
            EventType.RUN_STARTED,
            "planning",
            f"Starting deterministic {self.runtime_name} research run",
            extra=self._run_start_extra(request),
        )
        yield _ev(
            tracker,
            EventType.AGENT_STARTED,
            "planning",
            f"{self.planner_name} is building the source-specific query plan",
            agent_name=self.planner_name,
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Created initial todo list",
            artifact_type=ArtifactType.TODO_LIST,
            artifact_name="Research TODOs",
            artifact_text="\n".join(f"- {todo}" for todo in plan.todos),
        )
        yield _ev(
            tracker,
            EventType.TOOL_CALLED,
            "planning",
            "Prepared deterministic query plan",
            tool_name="literature.keyword_bundle",
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Saved search plan artifact",
            artifact_type=ArtifactType.SEARCH_PLAN,
            artifact_name="Search Plan",
            artifact_json=plan.model_dump(),
        )

        yield _ev(
            tracker,
            EventType.AGENT_STARTED,
            "searching",
            f"{self.search_agent_name} is executing the fixed source order",
            agent_name=self.search_agent_name,
        )

        provider_results: list[SearchProviderResult] = []
        for source in plan.databases:
            source_query = plan.source_queries.get(source, plan.normalized_query)
            yield _ev(
                tracker,
                EventType.TOOL_CALLED,
                "searching",
                f"Searching {source}",
                tool_name=_source_tool_name(source),
                extra={"query": source_query},
            )
            result = await search_source(
                source,
                source_query,
                api_keys=request.api_keys,
                max_results=DEFAULT_SEARCH_RESULTS_PER_SOURCE,
                offline_mode=request.offline_mode,
                domain=plan.domain,
                start_year=request.search_start_year,
                scopus_view=request.scopus_view,
            )
            provider_results.append(result)
            yield _ev(
                tracker,
                EventType.TOOL_RESULT,
                "searching",
                f"{source} completed with {len(result.studies)} studies",
                tool_name=_source_tool_name(source),
                extra={"error": result.error, "skipped": result.skipped, "count": len(result.studies)},
            )
            yield _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "searching",
                f"Captured {source} search results",
                artifact_type=ArtifactType.SEARCH_RESULTS,
                artifact_name=f"{source} Results",
                artifact_json=result.model_dump(),
            )

        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "searching",
            "Captured source execution summary",
            artifact_type=ArtifactType.SOURCE_PLAN,
            artifact_name="Source Execution Summary",
            artifact_json={
                "sources": [result.source for result in provider_results],
                "counts": {result.source: len(result.studies) for result in provider_results},
                "errors": {result.source: result.error for result in provider_results if result.error},
            },
        )

        all_studies = flatten_studies(provider_results)
        yield _ev(
            tracker,
            EventType.AGENT_STARTED,
            "ranking",
            "Scoring and ranking aggregated studies",
            agent_name=self.search_agent_name,
        )
        yield _ev(
            tracker,
            EventType.TOOL_CALLED,
            "ranking",
            "Ranking studies with deterministic scoring",
            tool_name="evidence.rank_results",
        )
        ranked = score_and_rank_results(
            all_studies,
            context="clinical" if plan.domain == "clinical" else "general",
            query=request.query,
            query_payload=request.query_payload,
        )
        yield _ev(
            tracker,
            EventType.TOOL_RESULT,
            "ranking",
            f"Ranked {len(ranked)} studies",
            tool_name="evidence.rank_results",
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "ranking",
            "Saved ranked evidence artifact",
            artifact_type=ArtifactType.RANKED_RESULTS,
            artifact_name="Ranked Results",
            artifact_json={"studies": [study.model_dump() for study in ranked]},
        )
        yield _ev(
            tracker,
            EventType.AGENT_STARTED,
            "verifying",
            f"{self.verifier_name} is checking PubMed identifiers",
            agent_name=self.verifier_name,
        )
        yield _ev(
            tracker,
            EventType.TOOL_CALLED,
            "verifying",
            "Running deterministic verification checks",
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
        yield _ev(
            tracker,
            EventType.TOOL_RESULT,
            "verifying",
            "Verification checks completed",
            tool_name="evidence.verify_results",
            extra=verification.model_dump(),
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "verifying",
            "Saved verification artifact",
            artifact_type=ArtifactType.VERIFICATION_REPORT,
            artifact_name="Verification Report",
            artifact_text=verification_report,
        )
        yield _ev(
            tracker,
            EventType.AGENT_STARTED,
            "synthesizing",
            f"{self.synthesis_agent_name} is assembling the deterministic report",
            agent_name=self.synthesis_agent_name,
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
        translation_bridge = AgenticEventBridge()
        translation_bridge.progress = tracker
        final_report, translate_events = await _maybe_translate_report(request, translation_bridge, final_report)
        for evt in translate_events:
            yield evt
        yield _ev(
            tracker,
            EventType.REPORT_DELTA,
            "synthesizing",
            "Report body updated from ranked evidence",
            report_markdown=final_report,
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved final report artifact",
            complete=True,
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        )
        yield _ev(
            tracker,
            EventType.RUN_COMPLETED,
            "complete",
            f"{self.runtime_name} run completed",
            complete=True,
            report_markdown=final_report,
            extra={
                **self._run_completed_extra(request, len(ranked)),
                **_translation_diagnostics(translation_bridge),
            },
        )


class AgenticFailureFallbackRuntime(DeterministicRuntime):
    def __init__(
        self,
        source_runtime: ResearchRuntime,
        fallback_reason: str,
        failure_diagnostics: dict[str, Any] | None = None,
        tracker: ProgressTracker | None = None,
    ) -> None:
        self._seed_tracker = tracker
        self.provider = source_runtime.provider
        self.runtime_name = f"{source_runtime.runtime_name} deterministic fallback"
        self.sdk_module = source_runtime.sdk_module
        self.runtime_engine = source_runtime.runtime_engine
        self._source_sdk_available = source_runtime.sdk_available
        self.planner_name = getattr(source_runtime, "planner_name", self.planner_name)
        self.search_agent_name = getattr(source_runtime, "search_agent_name", self.search_agent_name)
        self.synthesis_agent_name = getattr(source_runtime, "synthesis_agent_name", self.synthesis_agent_name)
        self.verifier_name = getattr(source_runtime, "verifier_name", self.verifier_name)
        self.fallback_reason = fallback_reason
        self.failure_diagnostics = failure_diagnostics or {}

    @property
    def sdk_available(self) -> bool:
        return self._source_sdk_available

    def _execution_mode(self, request: RunRequest) -> str:
        del request
        return "deterministic_fallback"

    def _run_start_extra(self, request: RunRequest) -> dict[str, Any]:
        extra = super()._run_start_extra(request)
        extra.update(
            {
                "fallback_reason": self.fallback_reason,
                "agentic_fallback": True,
                "source_execution_mode": "native_sdk_agentic",
                "report_source": "deterministic_fallback",
                **self.failure_diagnostics,
            }
        )
        return extra


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

    def _native_start_events(self, request: RunRequest, tracker: ProgressTracker) -> list[RuntimeEventPayload]:
        return [
            _ev(
                tracker,
                EventType.RUN_STARTED,
                "planning",
                f"Starting native {self.runtime_name} research run",
                extra={
                    "sdk_available": self.sdk_available,
                    "offline_mode": request.offline_mode,
                    "execution_mode": "native_sdk",
                    "runtime_engine": self.runtime_engine,
                    "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                    "search_credentials_present": _search_credentials_present(request.api_keys),
                },
            ),
            _ev(
                tracker,
                EventType.AGENT_STARTED,
                "planning",
                f"{self.native_agent_name} is guiding search checkpoints",
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
        screening: dict[str, Any] | None = None,
        appraisal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "iteration": iteration + 1,
            "plan": self._plan_summary_payload(plan),
            "source_counts": {result.source: len(result.studies) for result in results},
            "source_errors": {result.source: result.error for result in results if result.error},
            "ranked_count": len(ranked),
            "top_ranked_studies": [self._compact_study_summary(study) for study in ranked[:8]],
            "verification": verification.model_dump(),
        }
        if screening:
            payload["screening"] = {
                "included": screening.get("included"),
                "excluded_count": len(screening.get("excluded", [])),
                "top_exclusion_reasons": [ex.get("reason") for ex in screening.get("excluded", [])[:5]],
            }
        if appraisal:
            findings = appraisal.get("findings", [])
            histogram: dict[str, int] = {}
            low_findings: list[str] = []
            for finding in findings:
                certainty = str(finding.get("certainty", "")).strip() or "Unknown"
                histogram[certainty] = histogram.get(certainty, 0) + 1
                if certainty.lower() in ("low", "very low"):
                    low_findings.append(str(finding.get("finding", "")))
            payload["appraisal"] = {
                "certainty_histogram": histogram,
                "low_certainty_findings": low_findings[:5],
            }
        return payload

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
        screening: dict[str, Any] | None = None,
        appraisal: dict[str, Any] | None = None,
    ) -> RewindDecisionOutput:
        instructions = "\n".join(
            [
                "You are deciding whether the literature search should be rewound with adjusted source queries.",
                "Rewind only when another search pass is likely to materially improve coverage or reduce obvious noise.",
                "Reasons to rewind include: too few relevant studies, source failures, poor verification coverage, or queries that are clearly too narrow.",
                "Also rewind when screening left fewer than 3 included studies (broaden the queries),",
                "or when no High/Moderate-certainty evidence exists for the core outcome (target RCTs, systematic reviews, or registered trials).",
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
                        screening=screening,
                        appraisal=appraisal,
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

    async def _request_screening(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        pre_ranked: list[ScoredStudy],
    ) -> ScreeningOutput:
        instructions = "\n".join(
            [
                "You are screening retrieved studies for an evidence review against the research question.",
                "Include studies that match the population, intervention/exposure, comparator, and outcomes of interest.",
                "Exclude studies that are off-topic, the wrong population, the wrong intervention/comparator, or the wrong study type — give a short reason for each exclusion.",
                "Return included_reference_numbers for the studies to keep and exclusions for the studies to drop.",
                "When in doubt, include the study. Do not exclude more than half unless they are clearly irrelevant.",
            ]
        )
        prompt = "\n".join(
            [
                "Research question:",
                request.query,
                "",
                "Candidate studies JSON:",
                json.dumps([self._compact_study_summary(study) for study in pre_ranked], indent=2),
                "",
                "Decide which studies to include and which to exclude (with reasons).",
            ]
        )
        return await self._run_structured_checkpoint(
            request,
            task_name="screening",
            instructions=instructions,
            prompt=prompt,
            output_model=ScreeningOutput,
        )

    async def _request_appraisal(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
    ) -> AppraisalOutput:
        instructions = "\n".join(
            [
                "You are appraising the certainty of evidence (GRADE) for the key findings of this review.",
                "For each major finding, start High for RCT/meta-analysis-based evidence and Low for observational evidence.",
                "Rate DOWN for risk of bias, inconsistency, indirectness, and imprecision.",
                "Report certainty as exactly one of: High, Moderate, Low, Very Low — with a one-line rationale and the supporting reference numbers.",
                "Base findings only on the supplied studies; do not invent outcomes.",
            ]
        )
        prompt = "\n".join(
            [
                "Research question:",
                request.query,
                "",
                "Ranked studies JSON:",
                json.dumps([self._compact_study_summary(study) for study in ranked[:STUDY_PAGE_SIZE]], indent=2),
                "",
                "Return a GRADE certainty assessment per major finding.",
            ]
        )
        return await self._run_structured_checkpoint(
            request,
            task_name="appraisal",
            instructions=instructions,
            prompt=prompt,
            output_model=AppraisalOutput,
        )

    async def _request_final_synthesis(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        results: list[SearchProviderResult],
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
        screening: dict[str, Any] | None = None,
        appraisal: dict[str, Any] | None = None,
    ) -> FinalSynthesisOutput:
        instructions = "\n".join(
            [
                "Write a medical evidence report in markdown from the supplied deterministic evidence bundle.",
                "Do not invent citations, PMIDs, or findings that are not present in the input.",
                "Be explicit when evidence is weak, indirect, missing, or contradicted by source failures.",
                "State the GRADE certainty of evidence (High/Moderate/Low/Very Low) for each major finding using the appraisal data.",
                "If the appraisal was based on abstracts only, note that limitation; in Methods, note how many studies were screened out.",
                "Use sections: Executive Summary, Methods, Ranked Evidence, Certainty of Evidence, Verification, References.",
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
                        screening=screening,
                        appraisal=appraisal,
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
        tracker: ProgressTracker,
    ) -> _IterationResult:
        events: list[RuntimeEventPayload] = []
        provider_results: list[SearchProviderResult] = []
        notes: list[str] = []
        events.append(
            _ev(
                tracker,
                EventType.AGENT_STARTED,
                "searching",
                f"{self.search_agent_name} is executing search cycle {iteration + 1}",
                agent_name=self.search_agent_name,
            )
        )

        for source in plan.databases:
            source_query = plan.source_queries.get(source, plan.normalized_query)
            events.append(
                _ev(
                    tracker,
                    EventType.TOOL_CALLED,
                    "searching",
                    f"Searching {source} in cycle {iteration + 1}",
                    tool_name=_source_tool_name(source),
                    extra={"query": source_query, "iteration": iteration + 1},
                )
            )
            result = await search_source(
                source,
                source_query,
                api_keys=request.api_keys,
                max_results=DEFAULT_SEARCH_RESULTS_PER_SOURCE,
                offline_mode=request.offline_mode,
                domain=plan.domain,
                start_year=request.search_start_year,
                scopus_view=request.scopus_view,
            )
            provider_results.append(result)
            events.append(
                _ev(
                    tracker,
                    EventType.TOOL_RESULT,
                    "searching",
                    f"{source} completed with {len(result.studies)} studies",
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
                _ev(
                    tracker,
                    EventType.ARTIFACT_CREATED,
                    "searching",
                    f"Captured {source} search results for cycle {iteration + 1}",
                    artifact_type=ArtifactType.SEARCH_RESULTS,
                    artifact_name=f"{source} Results (Cycle {iteration + 1})",
                    artifact_json=result.model_dump(),
                )
            )

        events.append(
            _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "searching",
                f"Captured source execution summary for cycle {iteration + 1}",
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
            _ev(
                tracker,
                EventType.TOOL_CALLED,
                "ranking",
                f"Ranking studies for cycle {iteration + 1}",
                tool_name="evidence.rank_results",
            )
        )
        ranked = score_and_rank_results(
            all_studies,
            context="clinical" if plan.domain == "clinical" else "general",
            query=request.query,
            query_payload=request.query_payload,
        )
        events.append(
            _ev(
                tracker,
                EventType.TOOL_RESULT,
                "ranking",
                f"Ranked {len(ranked)} studies in cycle {iteration + 1}",
                tool_name="evidence.rank_results",
            )
        )

        # Screening checkpoint: include/exclude against the question, then renumber.
        screening_summary: dict[str, Any] | None = None
        if ranked:
            events.append(
                _ev(
                    tracker,
                    EventType.TOOL_CALLED,
                    "screening",
                    f"Screening studies against the question for cycle {iteration + 1}",
                    tool_name="agent.screen_studies",
                )
            )
            ranked, screening_summary, screen_note = await self._apply_screening(request, plan=plan, ranked=ranked)
            if screen_note:
                notes.append(screen_note)
            events.append(
                _ev(
                    tracker,
                    EventType.ARTIFACT_CREATED,
                    "screening",
                    f"Saved screening decisions for cycle {iteration + 1}",
                    artifact_type=ArtifactType.SCREENING_DECISIONS,
                    artifact_name=f"Screening Decisions (Cycle {iteration + 1})",
                    artifact_json=screening_summary,
                )
            )

        events.append(
            _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "ranking",
                f"Saved ranked evidence artifact for cycle {iteration + 1}",
                artifact_type=ArtifactType.RANKED_RESULTS,
                artifact_name=f"Ranked Results (Cycle {iteration + 1})",
                artifact_json={"studies": [study.model_dump() for study in ranked]},
            )
        )

        events.append(
            _ev(
                tracker,
                EventType.AGENT_STARTED,
                "verifying",
                f"{self.verifier_name} is checking PubMed identifiers for cycle {iteration + 1}",
                agent_name=self.verifier_name,
            )
        )
        events.append(
            _ev(
                tracker,
                EventType.TOOL_CALLED,
                "verifying",
                f"Running verification checks for cycle {iteration + 1}",
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
            _ev(
                tracker,
                EventType.TOOL_RESULT,
                "verifying",
                f"Verification checks completed for cycle {iteration + 1}",
                tool_name="evidence.verify_results",
                extra=verification.model_dump(),
            )
        )
        events.append(
            _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "verifying",
                f"Saved verification artifact for cycle {iteration + 1}",
                artifact_type=ArtifactType.VERIFICATION_REPORT,
                artifact_name=f"Verification Report (Cycle {iteration + 1})",
                artifact_text=render_verification_report(verification),
            )
        )

        # Appraisal checkpoint: GRADE certainty per major finding.
        appraisal_summary: dict[str, Any] | None = None
        if ranked:
            events.append(
                _ev(
                    tracker,
                    EventType.TOOL_CALLED,
                    "appraising",
                    f"Appraising certainty of evidence (GRADE) for cycle {iteration + 1}",
                    tool_name="agent.appraise_evidence",
                )
            )
            appraisal_summary, appraise_note = await self._apply_appraisal(
                request, plan=plan, ranked=ranked, verification=verification
            )
            if appraise_note:
                notes.append(appraise_note)
            events.append(
                _ev(
                    tracker,
                    EventType.ARTIFACT_CREATED,
                    "appraising",
                    f"Saved GRADE appraisal for cycle {iteration + 1}",
                    artifact_type=ArtifactType.APPRAISAL_SUMMARY,
                    artifact_name=f"GRADE Appraisal (Cycle {iteration + 1})",
                    artifact_json=appraisal_summary,
                )
            )

        return _IterationResult(
            events=events,
            provider_results=provider_results,
            ranked=ranked,
            verification=verification,
            screening=screening_summary,
            appraisal=appraisal_summary,
            notes=notes,
        )

    async def _apply_screening(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        ranked: list[ScoredStudy],
    ) -> tuple[list[ScoredStudy], dict[str, Any], str | None]:
        """Run the screening checkpoint; on failure, include all studies.

        Returns the (renumbered) included studies, a screening summary, and an
        optional note for the rewind decision.
        """
        title_by_ref = {s.reference_number: s.title for s in ranked}
        try:
            decision = await asyncio.wait_for(
                self._request_screening(request, plan=plan, pre_ranked=ranked),
                timeout=SCREENING_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            summary = {
                "screened_count": len(ranked),
                "included": len(ranked),
                "excluded": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            return ranked, summary, None

        excluded_map = {
            ex.reference_number: ex.reason
            for ex in decision.exclusions
            if ex.reference_number in title_by_ref
        }
        included_set = set(decision.included_reference_numbers)
        kept: list[ScoredStudy] = []
        for study in ranked:
            ref = study.reference_number
            # Exclude only when explicitly excluded and not explicitly included.
            if ref in excluded_map and ref not in included_set:
                continue
            kept.append(study)
        if not kept:  # Never screen everything out.
            kept = list(ranked)
            excluded_map = {}
        # Renumber contiguously so the report reference gate stays satisfied.
        renumbered: list[ScoredStudy] = []
        for new_ref, study in enumerate(kept, start=1):
            copy = study.model_copy(deep=True)
            copy.reference_number = new_ref
            renumbered.append(copy)
        summary = {
            "screened_count": len(ranked),
            "included": len(renumbered),
            "excluded": [
                {"reference_number": ref, "title": title_by_ref.get(ref, ""), "reason": reason}
                for ref, reason in excluded_map.items()
            ],
            "rationale": decision.rationale,
        }
        note = None
        if len(renumbered) < 3:
            note = f"Screening left only {len(renumbered)} studies; broaden the searches."
        return renumbered, summary, note

    async def _apply_appraisal(
        self,
        request: RunRequest,
        *,
        plan: QueryPlan,
        ranked: list[ScoredStudy],
        verification: VerificationSummary,
    ) -> tuple[dict[str, Any], str | None]:
        """Run the appraisal checkpoint; on failure, return a skipped summary."""
        try:
            appraisal = await asyncio.wait_for(
                self._request_appraisal(request, plan=plan, ranked=ranked, verification=verification),
                timeout=APPRAISAL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return {"findings": [], "skipped": True, "error": f"{type(exc).__name__}: {exc}"}, "Appraisal was skipped."
        findings = [f.model_dump() for f in appraisal.findings]
        summary = {"findings": findings, "overall_note": appraisal.overall_note}
        note = None
        high_moderate = [
            f for f in appraisal.findings if f.certainty.strip().lower() in ("high", "moderate")
        ]
        if appraisal.findings and not high_moderate:
            note = "No High/Moderate-certainty evidence was found for the core outcomes."
        return summary, note

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in super().stream_run(request):
                yield event
            return

        tracker = ProgressTracker()
        for event in self._native_start_events(request, tracker):
            yield event

        base_plan = build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
        yield _ev(
            tracker,
            EventType.TOOL_CALLED,
            "planning",
            "Requesting provider-guided query broadening",
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
            yield _ev(
                tracker,
                EventType.TOOL_RESULT,
                "planning",
                "Provider returned search guidance",
                tool_name="agent.search_guidance",
                extra=guidance.model_dump(),
            )
        except Exception as exc:
            plan = base_plan
            yield _ev(
                tracker,
                EventType.TOOL_RESULT,
                "planning",
                "Provider search guidance failed; using deterministic plan",
                tool_name="agent.search_guidance",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )

        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Created initial todo list",
            artifact_type=ArtifactType.TODO_LIST,
            artifact_name="Research TODOs",
            artifact_text="\n".join(f"- {todo}" for todo in plan.todos),
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Saved search plan artifact",
            artifact_type=ArtifactType.SEARCH_PLAN,
            artifact_name="Search Plan",
            artifact_json=plan.model_dump(),
        )

        current_plan = plan
        final_results: list[SearchProviderResult] = []
        final_ranked: list[ScoredStudy] = []
        final_screening: dict[str, Any] | None = None
        final_appraisal: dict[str, Any] | None = None
        final_verification = empty_verification_summary(
            "Verification was not reached in the provider-guided loop."
        )

        for iteration in range(self.max_search_iterations):
            iteration_result = await self._run_search_iteration(
                request,
                plan=current_plan,
                iteration=iteration,
                tracker=tracker,
            )
            for event in iteration_result.events:
                yield event
            provider_results = iteration_result.provider_results
            ranked = iteration_result.ranked
            verification = iteration_result.verification
            final_results = provider_results
            final_ranked = ranked
            final_verification = verification
            final_screening = iteration_result.screening
            final_appraisal = iteration_result.appraisal

            if iteration + 1 >= self.max_search_iterations:
                break

            yield _ev(
                tracker,
                EventType.TOOL_CALLED,
                "evaluating",
                f"Requesting rewind decision after cycle {iteration + 1}",
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
                        screening=iteration_result.screening,
                        appraisal=iteration_result.appraisal,
                    ),
                    timeout=REWIND_DECISION_TIMEOUT_SECONDS,
                )
                yield _ev(
                    tracker,
                    EventType.TOOL_RESULT,
                    "evaluating",
                    f"Provider returned rewind decision after cycle {iteration + 1}",
                    tool_name="agent.rewind_decision",
                    extra=rewind.model_dump(),
                )
            except Exception as exc:
                rewind = RewindDecisionOutput(
                    should_rewind=False,
                    rationale="Provider rewind decision failed; continuing with current evidence.",
                    notes=[f"{type(exc).__name__}: {exc}"],
                )
                yield _ev(
                    tracker,
                    EventType.TOOL_RESULT,
                    "evaluating",
                    f"Provider rewind decision failed after cycle {iteration + 1}",
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
            yield _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "evaluating",
                f"Saved rewound search plan for cycle {iteration + 2}",
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
        yield _ev(
            tracker,
            EventType.TOOL_CALLED,
            "synthesizing",
            "Requesting provider final synthesis",
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
                    screening=final_screening,
                    appraisal=final_appraisal,
                ),
                timeout=FINAL_SYNTHESIS_TIMEOUT_SECONDS,
            )
            final_report = synthesis.final_report.strip() or deterministic_report
            yield _ev(
                tracker,
                EventType.TOOL_RESULT,
                "synthesizing",
                "Provider final synthesis completed",
                tool_name="agent.final_synthesis",
                extra={"report_length": len(final_report)},
            )
        except Exception as exc:
            final_report = deterministic_report
            yield _ev(
                tracker,
                EventType.TOOL_RESULT,
                "synthesizing",
                "Provider final synthesis failed; using deterministic report",
                tool_name="agent.final_synthesis",
                extra={"error": f"{type(exc).__name__}: {exc}", "report_length": len(final_report)},
            )

        yield _ev(
            tracker,
            EventType.REPORT_DELTA,
            "synthesizing",
            "Report body updated from provider-guided evidence loop",
            report_markdown=final_report,
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved final report artifact",
            complete=True,
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        )
        yield _ev(
            tracker,
            EventType.RUN_COMPLETED,
            "complete",
            f"{self.runtime_name} run completed",
            complete=True,
            report_markdown=final_report,
            extra={
                "sdk_available": self.sdk_available,
                "offline_mode": request.offline_mode,
                "execution_mode": "native_sdk",
                "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                "ranked_results": len(final_ranked),
            },
        )




# ---------------------------------------------------------------------------
# Shared agentic user prompt
# ---------------------------------------------------------------------------

def _agentic_user_prompt(request: RunRequest) -> str:
    return (
        f"Conduct a thorough literature review for the following query:\n\n"
        f"{request.query}\n\n"
        f"Query type: {request.query_type}\n"
        f"Follow your recommended workflow: plan \u2192 search \u2192 rank \u2192 verify \u2192 synthesize.\n"
        f"Provide the complete markdown report in your final response."
    )


# ---------------------------------------------------------------------------
# Agentic event helpers (shared across provider runtimes)
# ---------------------------------------------------------------------------

def _agentic_run_started(
    runtime: ResearchRuntime, request: RunRequest, bridge: AgenticEventBridge
) -> RuntimeEventPayload:
    return _ev(
        bridge.progress,
        EventType.RUN_STARTED,
        "planning",
        f"Starting agentic {runtime.runtime_name} research run",
        extra={
            "sdk_available": runtime.sdk_available,
            "offline_mode": request.offline_mode,
            "execution_mode": "native_sdk_agentic",
            "runtime_engine": runtime.runtime_engine,
            "provider_credentials_present": _has_native_credentials(runtime.provider, request.api_keys),
            "search_credentials_present": _search_credentials_present(request.api_keys),
        },
    )


def _agentic_agent_started(agent_name: str, bridge: AgenticEventBridge) -> RuntimeEventPayload:
    return _ev(
        bridge.progress,
        EventType.AGENT_STARTED,
        "planning",
        f"{agent_name} is autonomously driving the research workflow",
        agent_name=agent_name,
    )


async def _maybe_translate_report(
    request: RunRequest,
    bridge: AgenticEventBridge,
    report: str,
) -> tuple[str, list[RuntimeEventPayload]]:
    """Translate the report if language is not English. Returns (report, events)."""
    if request.language in ("en", "english", "") or not report.strip():
        return report, []
    if request.offline_mode:
        bridge._intermediate["translation_status"] = "skipped"
        bridge._intermediate["translation_error"] = "Offline mode is enabled."
        return report, []
    if request.provider != "local" and not _has_native_credentials(request.provider, request.api_keys):
        bridge._intermediate["translation_status"] = "skipped"
        bridge._intermediate["translation_error"] = f"{request.provider} API key is not configured."
        return report, []

    _log.info("Translating report to %s", request.language)
    events: list[RuntimeEventPayload] = []

    # Save the English original as an artifact before translating
    events.append(_ev(
        bridge.progress,
        EventType.ARTIFACT_CREATED,
        "translating",
        "Saved original English report",
        artifact_type=ArtifactType.FINAL_REPORT,
        artifact_name="Report (English)",
        artifact_text=report,
    ))
    events.append(_ev(
        bridge.progress,
        EventType.AGENT_STARTED,
        "translating",
        f"Translating report to {request.language}",
        agent_name="Report Translator",
    ))
    try:
        result = await tool_translate_report(request, bridge, report, request.language)
        if result.get("status") == "ok" and result.get("length", 0) > 200:
            translated = bridge._intermediate.get("submitted_report", "") or bridge._result or ""
            if translated.strip():
                bridge._intermediate["translation_status"] = "ok"
                _log.info("Translation completed: %d chars", len(translated))
                return translated, events
        bridge._intermediate["translation_status"] = "failed"
        bridge._intermediate["translation_error"] = str(result.get("error") or result)
        _log.warning("Translation returned error or empty: %s", result)
    except Exception as exc:
        bridge._intermediate["translation_status"] = "failed"
        bridge._intermediate["translation_error"] = _format_exception(exc)
        _log.warning("Translation failed: %s", exc, exc_info=True)
    return report, events


def _translation_diagnostics(bridge: AgenticEventBridge) -> dict[str, Any]:
    status = bridge._intermediate.get("translation_status")
    if not status:
        return {}
    diagnostics: dict[str, Any] = {"translation_status": status}
    error = bridge._intermediate.get("translation_error")
    if error:
        diagnostics["translation_error"] = str(error)
    return diagnostics


def _agentic_debug_trace_event(
    bridge: AgenticEventBridge,
    *,
    phase: str = "diagnostics",
) -> RuntimeEventPayload | None:
    if not bridge.full_trace_enabled:
        return None
    return _ev(
        bridge.progress,
        EventType.ARTIFACT_CREATED,
        phase,
        "Saved full agentic debug trace",
        artifact_type=ArtifactType.DEBUG_TRACE,
        artifact_name="Agentic Debug Trace",
        artifact_json=bridge.debug_trace_payload(),
    )


def _agentic_final_events(
    runtime: ResearchRuntime,
    request: RunRequest,
    final_report: str,
    bridge: AgenticEventBridge,
    *,
    report_source: str | None = None,
    fallback_reason: str | None = None,
) -> list[RuntimeEventPayload]:
    inferred_report_source = report_source
    if inferred_report_source is None:
        submitted = bridge._intermediate.get("submitted_report")
        if isinstance(submitted, str) and submitted.strip() and final_report == submitted:
            inferred_report_source = "submitted_report"
        elif bridge._result and final_report == bridge._result:
            inferred_report_source = "agent_result"
        elif bridge.search_results or bridge.ranked_studies:
            inferred_report_source = "recovered_agentic_state"
        else:
            inferred_report_source = "empty_recovery"

    source_counts = {result.source: len(result.studies) for result in bridge.search_results}
    error_message = _format_exception(bridge._error)
    completion_extra = {
        "sdk_available": runtime.sdk_available,
        "offline_mode": request.offline_mode,
        "execution_mode": "native_sdk_agentic",
        "runtime_engine": runtime.runtime_engine,
        "provider_credentials_present": _has_native_credentials(runtime.provider, request.api_keys),
        "search_credentials_present": _search_credentials_present(request.api_keys),
        "tool_calls": bridge._tool_call_count,
        "had_error": bridge._error is not None,
        "error_message": error_message,
        "search_sources_executed": list(source_counts),
        "source_counts": source_counts,
        "ranked_results": len(bridge.ranked_studies),
        "report_source": inferred_report_source,
    }
    if fallback_reason:
        completion_extra["fallback_reason"] = fallback_reason
    completion_extra.update(_agentic_failure_diagnostics(bridge))
    completion_extra.update(_translation_diagnostics(bridge))
    post_submit_error = bridge._intermediate.get("post_submit_error_message")
    if post_submit_error:
        completion_extra["post_submit_error_message"] = str(post_submit_error)
        completion_extra["post_submit_error_type"] = bridge._intermediate.get("post_submit_error_type")

    return [
        _ev(
            bridge.progress,
            EventType.REPORT_DELTA,
            "synthesizing",
            "Report assembled from agentic research workflow",
            report_markdown=final_report,
        ),
        _ev(
            bridge.progress,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved final report artifact",
            complete=True,
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        ),
        _ev(
            bridge.progress,
            EventType.RUN_COMPLETED,
            "complete",
            f"{runtime.runtime_name} agentic run completed",
            complete=True,
            report_markdown=final_report,
            extra=completion_extra,
        ),
    ]


def _select_agentic_final_report(
    request: RunRequest,
    bridge: AgenticEventBridge,
    runtime_name: str,
    agent_text: str | None,
) -> tuple[str, str]:
    submitted = bridge._intermediate.get("submitted_report")
    if isinstance(submitted, str) and submitted.strip():
        return submitted.strip(), "submitted_report"

    recovered = recover_report_from_bridge(request, bridge, runtime_name)
    candidate = (agent_text or "").strip()
    if candidate:
        quality_issues = report_quality_issues(
            candidate,
            ranked_count=len(bridge.ranked_studies),
            search_count=sum(len(result.studies) for result in bridge.search_results),
        )
        if not quality_issues:
            return candidate, "agent_result"
        bridge._intermediate["agent_final_message"] = candidate
        bridge._intermediate["agent_final_message_quality_issues"] = quality_issues

    if bridge.search_results or bridge.ranked_studies:
        return recovered, "recovered_agentic_state"
    if candidate:
        return candidate, "agent_result"
    return recovered, "empty_recovery"


# ---------------------------------------------------------------------------
# OpenAI Agents SDK — agentic runtime
# ---------------------------------------------------------------------------

_SEARCH_SOURCES = {
    "search_pubmed": "PubMed",
    "search_pmc": "PMC",
    "search_europe_pmc": "Europe PMC",
    "search_openalex": "OpenAlex",
    "search_crossref": "Crossref",
    "search_cochrane": "Cochrane",
    "search_semantic_scholar": "Semantic Scholar",
    "search_scopus": "Scopus",
    "search_clinical_trials": "ClinicalTrials.gov",
    "search_preprints": "Preprints",
}


def _build_openai_tools(request: RunRequest, bridge: AgenticEventBridge) -> list[Any]:
    """Build OpenAI ``FunctionTool`` instances wrapping shared tool functions."""
    from agents import FunctionTool

    tools: list[Any] = []

    def _wrap(name: str, schema: dict[str, Any], coro_factory: Any) -> Any:  # noqa: ANN401
        """Create a FunctionTool that emits bridge events around the call."""

        async def _invoke(_ctx: Any, args_json: str) -> str:
            args = json.loads(args_json) if args_json else {}
            await bridge.on_tool_start(name, args)
            try:
                result = await coro_factory(args)
            except Exception as exc:
                await bridge.on_tool_end(name, {"error": str(exc)})
                return json.dumps({"error": str(exc)})
            await bridge.on_tool_end(name, result)
            return json.dumps(result, default=str)

        return FunctionTool(
            name=name,
            description=TOOL_DESCRIPTIONS.get(name, name),
            params_json_schema=schema,
            on_invoke_tool=_invoke,
            strict_json_schema=False,
        )

    # Planning tools
    tools.append(_wrap("plan_search", {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "query_type": {"type": "string", "default": "free"},
        },
        "required": ["query"],
    }, lambda a: tool_plan_search(request, bridge, a["query"], a.get("query_type", "free"))))

    tools.append(_wrap("suggest_databases", {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }, lambda a: tool_suggest_databases(request, bridge, a["query"])))

    tools.append(_wrap("write_todos", {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }, lambda a: tool_write_todos(request, bridge, a.get("items", []))))

    tools.append(_wrap("update_progress", {
        "type": "object",
        "properties": {
            "phase": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["phase", "message"],
    }, lambda a: tool_update_progress(request, bridge, a["phase"], a["message"])))

    # Search tools (one per database)
    for tool_name, source in _SEARCH_SOURCES.items():
        _src = source  # capture for closure

        tools.append(_wrap(tool_name, {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": DEFAULT_SEARCH_RESULTS_PER_SOURCE},
            },
            "required": ["query"],
        }, lambda a, s=_src: tool_search(request, bridge, s, a["query"], a.get("max_results", DEFAULT_SEARCH_RESULTS_PER_SOURCE))))

    # Snowballing tools (citation-graph traversal on ranked studies)
    tools.append(_wrap("get_references", {
        "type": "object",
        "properties": {"reference_number": {"type": "integer"}},
        "required": ["reference_number"],
    }, lambda a: tool_snowball(request, bridge, a["reference_number"], "references")))

    tools.append(_wrap("get_citations", {
        "type": "object",
        "properties": {"reference_number": {"type": "integer"}},
        "required": ["reference_number"],
    }, lambda a: tool_snowball(request, bridge, a["reference_number"], "citations")))

    # Evidence tools
    tools.append(_wrap("get_studies", {
        "type": "object",
        "properties": {"context": {"type": "string", "default": "general"}},
    }, lambda a: tool_get_studies(request, bridge, a.get("context", "general"))))

    tools.append(_wrap("browse_studies", {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "default": 1},
            "evidence_level": {"type": "string"},
            "source": {"type": "string"},
            "page_size": {"type": "integer"},
        },
    }, lambda a: tool_browse_studies(
        request, bridge,
        a.get("page", 1),
        a.get("evidence_level"),
        a.get("source"),
        a.get("page_size"),
    )))

    tools.append(_wrap("screen_studies", {
        "type": "object",
        "properties": {
            "included_indices": {"type": "array", "items": {"type": "integer"}},
            "excluded_indices": {"type": "array", "items": {"type": "integer"}},
            "exclusion_reasons": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["included_indices"],
    }, lambda a: tool_screen_studies(
        request, bridge,
        a.get("included_indices", []),
        a.get("excluded_indices", []),
        a.get("exclusion_reasons", []),
    )))

    tools.append(_wrap("finalize_ranking", {
        "type": "object",
        "properties": {
            "ranked_indices": {"type": "array", "items": {"type": "integer"}},
            "rationale": {"type": "string", "default": ""},
        },
        "required": ["ranked_indices"],
    }, lambda a: tool_finalize_ranking(request, bridge, a.get("ranked_indices", []), a.get("rationale", ""))))

    tools.append(_wrap("appraise_evidence", {
        "type": "object",
        "properties": {
            "findings": {"type": "array", "items": {"type": "string"}},
            "certainties": {"type": "array", "items": {"type": "string"}},
            "rationales": {"type": "array", "items": {"type": "string"}},
            "reference_numbers_csv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["findings", "certainties"],
    }, lambda a: tool_appraise_evidence(
        request, bridge,
        a.get("findings", []),
        a.get("certainties", []),
        a.get("rationales", []),
        a.get("reference_numbers_csv", []),
    )))

    tools.append(_wrap("verify_studies", {
        "type": "object",
        "properties": {},
    }, lambda _a: tool_verify_studies(request, bridge)))

    tools.append(_wrap("synthesize_report", {
        "type": "object",
        "properties": {},
    }, lambda _a: tool_synthesize_report(request, bridge)))

    tools.append(_wrap("submit_report", {
        "type": "object",
        "properties": {"report_markdown": {"type": "string", "description": "The complete research report in markdown"}},
        "required": ["report_markdown"],
    }, lambda a: tool_submit_report(request, bridge, a.get("report_markdown", ""))))

    # Fulltext tools
    tools.append(_wrap("fetch_fulltext", {
        "type": "object",
        "properties": {},
    }, lambda _a: tool_fetch_fulltext(request, bridge)))

    tools.append(_wrap("await_user_pdfs", {
        "type": "object",
        "properties": {
            "ranks": {"type": "array", "items": {"type": "integer"}},
        },
    }, lambda a: tool_await_user_pdfs(
        request,
        bridge,
        a.get("ranks", []),
    )))

    tools.append(_wrap("parse_pdf", {
        "type": "object",
        "properties": {"rank": {"type": "integer"}},
        "required": ["rank"],
    }, lambda a: tool_parse_pdf(request, bridge, a.get("rank", 1))))

    return tools


class OpenAIRuntime(NativeSDKRuntime):
    provider = "openai"
    runtime_name = "OpenAI Agents SDK"
    sdk_module = "agents"
    runtime_engine = "openai_agents"
    planner_name = "OpenAI Planner"
    search_agent_name = "OpenAI Search Agent"
    synthesis_agent_name = "OpenAI Synthesis Agent"
    verifier_name = "OpenAI Verification Agent"
    native_agent_name = "OpenAI Agentic Research Agent"

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return

        from agents import Agent, Runner

        bridge = AgenticEventBridge()
        tools = _build_openai_tools(request, bridge)

        yield _agentic_run_started(self, request, bridge)
        yield _agentic_agent_started(self.native_agent_name, bridge)

        env_updates = _provider_api_env(self.provider, request.api_keys)
        _env_ctx = _temporary_env(env_updates)
        _env_ctx.__enter__()

        agent = Agent(
            name="openai_research_agent",
            instructions=agentic_system_prompt(request, self.runtime_name),
            model=request.model,
            tools=tools,
        )
        agent_task = asyncio.create_task(
            self._run_openai_agent(Runner, agent, request, bridge)
        )

        # Yield events from bridge queue as the agent works
        while True:
            queued: RuntimeEventPayload | None = await bridge.queue.get()
            if queued is None:
                break
            yield queued

        try:
            await agent_task
        except Exception as exc:
            _log.warning("OpenAI agentic task error: %s", exc)
            bridge.set_error(exc)
        finally:
            _env_ctx.__exit__(None, None, None)

        agent_text = bridge._result or ""
        final_report, report_source = _select_agentic_final_report(
            request, bridge, self.runtime_name, agent_text
        )

        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for evt in translate_events:
            yield evt

        for event in _agentic_final_events(self, request, final_report, bridge, report_source=report_source):
            yield event

    async def _run_openai_agent(
        self,
        Runner: Any,
        agent: Any,
        request: RunRequest,
        bridge: AgenticEventBridge,
    ) -> None:
        try:
            result = await asyncio.wait_for(
                Runner.run(
                    agent,
                    _agentic_user_prompt(request),
                    max_turns=ANTHROPIC_AGENTIC_MAX_TURNS,
                ),
                timeout=ANTHROPIC_AGENTIC_TIMEOUT_SECONDS,
            )
            final_text = str(result.final_output) if result.final_output else None
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except asyncio.TimeoutError:
            _log.warning("OpenAI agentic run timed out after %ss", ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_error(TimeoutError(f"Agent timed out after {ANTHROPIC_AGENTIC_TIMEOUT_SECONDS}s"))
        except Exception as exc:
            _log.warning("OpenAI agentic run failed: %s", exc)
            bridge.set_error(exc)
        finally:
            await bridge.queue.put(None)

    # Legacy structured checkpoint for NativeSDKRuntime fallback path
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
            result = await Runner.run(agent, prompt, max_turns=4)
        return _coerce_model_output(result.final_output, output_model)


# ---------------------------------------------------------------------------
# Legacy Anthropic Agent SDK runtime (requires Claude Code/Git Bash on some platforms)
# ---------------------------------------------------------------------------

def _build_anthropic_mcp_servers(
    request: RunRequest,
    bridge: AgenticEventBridge,
) -> dict[str, Any]:
    """Build in-process MCP servers wrapping shared tool functions.

    Returns a dict suitable for ``ClaudeAgentOptions.mcp_servers``.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    # -- Literature tools ----------------------------------------------------

    @tool("plan_search", TOOL_DESCRIPTIONS["plan_search"], {"query": str, "query_type": str})
    async def plan_search_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_plan_search(request, bridge, args["query"], args.get("query_type", request.query_type))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("suggest_databases", TOOL_DESCRIPTIONS["suggest_databases"], {"query": str})
    async def suggest_databases_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_suggest_databases(request, bridge, args["query"])
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    def _make_search_tool(source: str, name: str) -> Any:
        @tool(name, TOOL_DESCRIPTIONS[name], {"query": str, "max_results": int})
        async def _search(args: dict[str, Any]) -> dict[str, Any]:
            result = await tool_search(request, bridge, source, args["query"], args.get("max_results", DEFAULT_SEARCH_RESULTS_PER_SOURCE))
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        return _search

    literature_server = create_sdk_mcp_server("literature", tools=[
        plan_search_tool,
        suggest_databases_tool,
        *[_make_search_tool(src, name) for name, src in _SEARCH_SOURCES.items()],
    ])

    # -- Evidence tools ------------------------------------------------------

    def _make_snowball_tool(name: str, direction: str) -> Any:
        @tool(name, TOOL_DESCRIPTIONS[name], {"reference_number": int})
        async def _snowball(args: dict[str, Any]) -> dict[str, Any]:
            result = await tool_snowball(request, bridge, args["reference_number"], direction)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        return _snowball

    @tool("get_studies", TOOL_DESCRIPTIONS["get_studies"], {"context": str})
    async def get_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_get_studies(request, bridge, args.get("context", "general"))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("browse_studies", TOOL_DESCRIPTIONS["browse_studies"],
          {"page": int, "evidence_level": str, "source": str, "page_size": int})
    async def browse_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_browse_studies(
            request, bridge,
            args.get("page", 1),
            args.get("evidence_level"),
            args.get("source"),
            args.get("page_size"),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("screen_studies", TOOL_DESCRIPTIONS["screen_studies"],
          {"included_indices": list, "excluded_indices": list, "exclusion_reasons": list})
    async def screen_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_screen_studies(
            request, bridge,
            args.get("included_indices", []),
            args.get("excluded_indices", []),
            args.get("exclusion_reasons", []),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("finalize_ranking", TOOL_DESCRIPTIONS["finalize_ranking"], {"ranked_indices": list, "rationale": str})
    async def finalize_ranking_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_finalize_ranking(request, bridge, args.get("ranked_indices", []), args.get("rationale", ""))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("appraise_evidence", TOOL_DESCRIPTIONS["appraise_evidence"],
          {"findings": list, "certainties": list, "rationales": list, "reference_numbers_csv": list})
    async def appraise_evidence_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_appraise_evidence(
            request, bridge,
            args.get("findings", []),
            args.get("certainties", []),
            args.get("rationales", []),
            args.get("reference_numbers_csv", []),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("verify_studies", TOOL_DESCRIPTIONS["verify_studies"], {})
    async def verify_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_verify_studies(request, bridge)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("synthesize_report", TOOL_DESCRIPTIONS["synthesize_report"], {})
    async def synthesize_report_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_synthesize_report(request, bridge)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("submit_report", TOOL_DESCRIPTIONS["submit_report"], {"report_markdown": str})
    async def submit_report_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_submit_report(request, bridge, args.get("report_markdown", ""))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    evidence_server = create_sdk_mcp_server("evidence", tools=[
        _make_snowball_tool("get_references", "references"),
        _make_snowball_tool("get_citations", "citations"),
        get_studies_tool,
        browse_studies_tool,
        screen_studies_tool,
        finalize_ranking_tool,
        appraise_evidence_tool,
        verify_studies_tool,
        synthesize_report_tool,
        submit_report_tool,
    ])

    # -- Workspace tools -----------------------------------------------------

    @tool("write_todos", TOOL_DESCRIPTIONS["write_todos"], {"items": list})
    async def write_todos_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_write_todos(request, bridge, [str(i) for i in args.get("items", [])])
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("update_progress", TOOL_DESCRIPTIONS["update_progress"], {"phase": str, "message": str})
    async def update_progress_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_update_progress(request, bridge, args["phase"], args["message"])
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    workspace_server = create_sdk_mcp_server("workspace", tools=[
        write_todos_tool,
        update_progress_tool,
    ])

    # -- Fulltext tools ------------------------------------------------------

    @tool("fetch_fulltext", TOOL_DESCRIPTIONS["fetch_fulltext"], {})
    async def fetch_fulltext_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_fetch_fulltext(request, bridge)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("await_user_pdfs", TOOL_DESCRIPTIONS["await_user_pdfs"], {"ranks": list})
    async def await_user_pdfs_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_await_user_pdfs(
            request,
            bridge,
            args.get("ranks", []),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("parse_pdf", TOOL_DESCRIPTIONS["parse_pdf"], {"rank": int})
    async def parse_pdf_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_parse_pdf(request, bridge, args.get("rank", 1))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    fulltext_server = create_sdk_mcp_server("fulltext", tools=[
        fetch_fulltext_tool,
        await_user_pdfs_tool,
        parse_pdf_tool,
    ])

    return {
        "literature": literature_server,
        "evidence": evidence_server,
        "workspace": workspace_server,
        "fulltext": fulltext_server,
    }


class ClaudeSDKAnthropicRuntime(NativeSDKRuntime):
    provider = "anthropic"
    runtime_name = "Anthropic Agent SDK"
    sdk_module = "claude_agent_sdk"
    runtime_engine = "claude_sdk_legacy"
    planner_name = "Claude Planner"
    search_agent_name = "Claude Search Agent"
    synthesis_agent_name = "Claude Synthesis Agent"
    verifier_name = "Claude Verification Agent"
    native_agent_name = "Claude MCP Research Agent"

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return

        from claude_agent_sdk import ClaudeAgentOptions, query
        from claude_agent_sdk.types import HookMatcher

        bridge = AgenticEventBridge()
        mcp_servers = _build_anthropic_mcp_servers(request, bridge)

        # Register MCP namespaced tool names so bridge can resolve phases
        mcp_alias: dict[str, str] = {}
        for server_name in ("literature", "evidence", "workspace", "fulltext"):
            for bare in TOOL_DESCRIPTIONS:
                mcp_alias[f"mcp__{server_name}__{bare}"] = bare
        bridge.set_tool_name_map(mcp_alias)

        yield _agentic_run_started(self, request, bridge)
        yield _agentic_agent_started(self.native_agent_name, bridge)

        sdk_stderr_lines: list[str] = []

        def capture_sdk_stderr(line: str) -> None:
            cleaned = str(line).strip()
            if not cleaned:
                return
            sdk_stderr_lines.append(cleaned)
            del sdk_stderr_lines[:-20]

        options = ClaudeAgentOptions(
            tools=[],
            model=request.model,
            mcp_servers=mcp_servers,
            allowed_tools=[
                "mcp__literature__plan_search", "mcp__literature__suggest_databases",
                "mcp__literature__search_pubmed", "mcp__literature__search_openalex",
                "mcp__literature__search_cochrane", "mcp__literature__search_semantic_scholar",
                "mcp__literature__search_scopus",
                "mcp__evidence__get_studies", "mcp__evidence__browse_studies",
                "mcp__evidence__screen_studies", "mcp__evidence__finalize_ranking",
                "mcp__evidence__verify_studies", "mcp__evidence__synthesize_report",
                "mcp__evidence__submit_report",
                "mcp__fulltext__fetch_fulltext", "mcp__fulltext__await_user_pdfs",
                "mcp__fulltext__parse_pdf",
                "mcp__workspace__write_todos", "mcp__workspace__update_progress",
            ],
            hooks={
                "PreToolUse": [HookMatcher(hooks=[bridge.pre_tool_use])],   # type: ignore[list-item]
                "PostToolUse": [HookMatcher(hooks=[bridge.post_tool_use])],  # type: ignore[list-item]
            },
            system_prompt=agentic_system_prompt(request, self.runtime_name),
            max_turns=ANTHROPIC_AGENTIC_MAX_TURNS,
            permission_mode="dontAsk",
            cwd=str(REPO_ROOT),
            env=_provider_api_env(self.provider, request.api_keys),
            stderr=capture_sdk_stderr,
        )

        agent_task = asyncio.create_task(
            self._run_agent_task(query, _agentic_user_prompt(request), options, bridge)
        )

        while True:
            queued: RuntimeEventPayload | None = await bridge.queue.get()
            if queued is None:
                break
            yield queued

        try:
            await agent_task
        except Exception as exc:
            _log.warning("Anthropic agentic task error: %s", exc)
            bridge.set_error(exc)
        if sdk_stderr_lines:
            bridge._intermediate["sdk_stderr_tail"] = "\n".join(sdk_stderr_lines[-20:])

        agent_text = bridge._result or ""
        startup_fallback_reason = self._pre_search_fallback_reason(bridge)
        if startup_fallback_reason:
            failure_diagnostics = _agentic_failure_diagnostics(bridge)
            yield _ev(
                bridge.progress,
                EventType.AGENT_STARTED,
                bridge.progress.current_phase or "planning",
                f"{startup_fallback_reason} Running deterministic fallback.",
                agent_name=self.native_agent_name,
                extra={
                    "fallback_reason": startup_fallback_reason,
                    "tool_calls": bridge._tool_call_count,
                    "had_error": bridge._error is not None,
                    "error_message": _format_exception(bridge._error),
                    "execution_mode": "deterministic_fallback",
                    "source_execution_mode": "native_sdk_agentic",
                    "report_source": "deterministic_fallback",
                    **failure_diagnostics,
                },
            )
            fallback_runtime = AgenticFailureFallbackRuntime(
                self, startup_fallback_reason, failure_diagnostics, tracker=bridge.progress
            )
            async for event in fallback_runtime.stream_run(request):
                yield event
            return

        final_report, report_source = _select_agentic_final_report(
            request, bridge, self.runtime_name, agent_text
        )

        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for evt in translate_events:
            yield evt

        for event in _agentic_final_events(self, request, final_report, bridge, report_source=report_source):
            yield event

    def _pre_search_fallback_reason(self, bridge: AgenticEventBridge) -> str | None:
        submitted = bridge._intermediate.get("submitted_report")
        if isinstance(submitted, str) and submitted.strip():
            return None
        if bridge.search_results:
            return None
        if bridge._error is not None:
            stderr_tail = _trim_diagnostic_text(bridge._intermediate.get("sdk_stderr_tail"), max_chars=300)
            stderr_hint = ""
            if stderr_tail:
                last_line = stderr_tail.splitlines()[-1]
                stderr_hint = f" Last stderr: {last_line}"
            return (
                f"{self.runtime_name} failed before completing any search tools "
                f"({_format_exception(bridge._error)}).{stderr_hint}"
            )
        if bridge._tool_call_count > 0:
            return f"{self.runtime_name} completed without executing any search tools."
        return f"{self.runtime_name} completed without calling any research tools."

    async def _run_agent_task(
        self,
        query_fn: Any,
        prompt: str,
        options: Any,
        bridge: AgenticEventBridge,
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
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except asyncio.TimeoutError:
            _log.warning("Anthropic agentic run timed out after %ss", ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_error(TimeoutError(f"Agent timed out after {ANTHROPIC_AGENTIC_TIMEOUT_SECONDS}s"))
        except Exception as exc:
            _log.warning("Anthropic agentic run failed: %s", exc)
            bridge.set_error(exc)
        finally:
            await bridge.queue.put(None)

    # Legacy structured checkpoint for NativeSDKRuntime fallback path
    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        from claude_agent_sdk import ClaudeAgentOptions, query as claude_query
        from claude_agent_sdk.types import ResultMessage

        with _temporary_env(_provider_api_env(self.provider, request.api_keys)):
            options = ClaudeAgentOptions(
                tools=[],
                model=request.model,
                system_prompt=instructions,
                max_turns=4,
                permission_mode="dontAsk",
                cwd=str(REPO_ROOT),
                env=_provider_api_env(self.provider, request.api_keys),
            )
            final_text: str | None = None
            async for message in claude_query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage) and message.result:
                    final_text = message.result
        if final_text is None:
            raise RuntimeError(f"Anthropic Agent SDK did not return a {task_name} result.")
        return _coerce_model_output(final_text, output_model)


# ---------------------------------------------------------------------------
# LangChain Local LLM — agentic runtime (Ollama / LM Studio)
# ---------------------------------------------------------------------------

def _truncate_tool_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _compact_study_dict(study: Any, *, abstract_chars: int = 240) -> dict[str, Any]:
    if not isinstance(study, dict):
        return {"value": _truncate_tool_text(str(study), abstract_chars)}
    keys = (
        "idx",
        "rank",
        "source_id",
        "title",
        "year",
        "publication_year",
        "journal",
        "evidence_level",
        "citation_count",
        "pmid",
        "doi",
        "sources",
        "source",
        "pre_score",
        "score",
    )
    compact = {key: study.get(key) for key in keys if study.get(key) not in (None, "", [])}
    abstract = study.get("abstract")
    if abstract:
        compact["abstract"] = _truncate_tool_text(str(abstract).replace("\n", " "), abstract_chars)
    authors = study.get("authors")
    if isinstance(authors, list) and authors:
        compact["authors"] = authors[:3]
    return compact


def _compact_tool_result(tool_name: str, result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    if tool_name.startswith("search_"):
        studies = result.get("studies") if isinstance(result.get("studies"), list) else []
        return {
            "source": result.get("source"),
            "count": result.get("count", len(studies)),
            "error": result.get("error"),
            "skipped": result.get("skipped"),
            "studies": [_compact_study_dict(study, abstract_chars=220) for study in studies[:10]],
            "truncated_studies": max(0, len(studies) - 10),
        }

    if tool_name in ("get_studies", "browse_studies"):
        studies = result.get("studies") if isinstance(result.get("studies"), list) else []
        meta_keys = (
            "error", "total", "shown", "page", "page_size", "has_more", "context",
            "counts_by_evidence_level", "counts_by_source", "note",
            "total_in_pool", "filtered_total", "evidence_level", "source",
        )
        payload = {key: result.get(key) for key in meta_keys if result.get(key) is not None}
        payload["studies"] = [_compact_study_dict(study, abstract_chars=240) for study in studies[:STUDY_PAGE_SIZE]]
        payload["truncated_studies"] = max(0, len(studies) - STUDY_PAGE_SIZE)
        return payload

    if tool_name == "verify_studies":
        return {
            "verified": result.get("verified"),
            "missing": result.get("missing"),
            "notes": result.get("notes", [])[:5] if isinstance(result.get("notes"), list) else result.get("notes"),
        }

    if tool_name == "synthesize_report":
        compact = dict(result)
        studies = compact.get("studies") if isinstance(compact.get("studies"), list) else []
        compact["studies"] = [_compact_study_dict(study, abstract_chars=320) for study in studies[:MAX_REPORT_STUDIES]]
        compact["truncated_studies"] = max(0, len(studies) - MAX_REPORT_STUDIES)
        return compact

    if tool_name == "fetch_fulltext":
        compact = dict(result)
        for key in ("fulltext", "markdown", "text"):
            if key in compact:
                compact[key] = _truncate_tool_text(compact[key], 1200)
        return compact

    if tool_name == "parse_pdf":
        compact = dict(result)
        for key in ("fulltext", "markdown", "text"):
            if key in compact:
                compact[key] = _truncate_tool_text(compact[key], 3500)
        return compact

    return result


def _langchain_tool_json(tool_name: str, result: Any) -> str:
    return json.dumps(_compact_tool_result(tool_name, result), default=str)


def _build_langchain_tools(
    request: RunRequest,
    bridge: AgenticEventBridge,
    *,
    stop_after_submit: bool = False,
    stop_after_report_rejection: bool = False,
) -> list[Any]:
    """Build LangChain ``StructuredTool`` instances wrapping shared tool functions.

    Each tool has a properly typed async function so LangChain infers correct
    parameter schemas — no **kwargs ambiguity.
    """
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    async def plan_search(query: str, query_type: str = "free") -> str:
        """Build a search plan. Returns keywords, databases, and source queries."""
        await bridge.on_tool_start("plan_search", {"query": query})
        result = await tool_plan_search(request, bridge, query, query_type)
        await bridge.on_tool_end("plan_search", result)
        return _langchain_tool_json("plan_search", result)

    @lc_tool
    async def suggest_databases(query: str) -> str:
        """Suggest database coverage for a research query."""
        await bridge.on_tool_start("suggest_databases", {"query": query})
        result = await tool_suggest_databases(request, bridge, query)
        await bridge.on_tool_end("suggest_databases", result)
        return _langchain_tool_json("suggest_databases", result)

    @lc_tool
    async def write_todos(items: list[str]) -> str:
        """Create a research TODO list to plan the workflow."""
        await bridge.on_tool_start("write_todos", {})
        result = await tool_write_todos(request, bridge, items)
        await bridge.on_tool_end("write_todos", result)
        return _langchain_tool_json("write_todos", result)

    @lc_tool
    async def update_progress(phase: str, message: str) -> str:
        """Signal a phase transition or progress update to the user."""
        await bridge.on_tool_start("update_progress", {"phase": phase})
        result = await tool_update_progress(request, bridge, phase, message)
        await bridge.on_tool_end("update_progress", result)
        return _langchain_tool_json("update_progress", result)

    def _make_search(tool_name: str, source: str) -> Any:
        @lc_tool(tool_name)
        async def _search(query: str, max_results: int = DEFAULT_SEARCH_RESULTS_PER_SOURCE) -> str:
            """Search a medical literature database."""
            await bridge.on_tool_start(tool_name, {"query": query})
            requested = min(max(int(max_results or DEFAULT_SEARCH_RESULTS_PER_SOURCE), 1), MAX_AGENT_SEARCH_RESULTS_PER_SOURCE)
            result = await tool_search(request, bridge, source, query, requested)
            await bridge.on_tool_end(tool_name, result)
            return _langchain_tool_json(tool_name, result)
        _search.description = TOOL_DESCRIPTIONS[tool_name]
        return _search

    search_tools = [_make_search(name, src) for name, src in _SEARCH_SOURCES.items()]

    @lc_tool
    async def get_references(reference_number: int) -> str:
        """Backward snowballing: fetch the reference list of a ranked study [n]. Re-run get_studies to merge."""
        await bridge.on_tool_start("get_references", {"reference_number": reference_number})
        result = await tool_snowball(request, bridge, reference_number, "references")
        await bridge.on_tool_end("get_references", result)
        return _langchain_tool_json("get_references", result)

    @lc_tool
    async def get_citations(reference_number: int) -> str:
        """Forward snowballing: fetch papers citing a ranked study [n]. Re-run get_studies to merge."""
        await bridge.on_tool_start("get_citations", {"reference_number": reference_number})
        result = await tool_snowball(request, bridge, reference_number, "citations")
        await bridge.on_tool_end("get_citations", result)
        return _langchain_tool_json("get_citations", result)

    @lc_tool
    async def get_studies(context: str = "general") -> str:
        """Deduplicate and pre-score ALL collected studies. Returns a pre-ranked top tier grouped by evidence level I->V; use browse_studies to page for more."""
        await bridge.on_tool_start("get_studies", {"context": context})
        result = await tool_get_studies(request, bridge, context)
        await bridge.on_tool_end("get_studies", result)
        return _langchain_tool_json("get_studies", result)

    @lc_tool
    async def browse_studies(
        page: int = 1,
        evidence_level: str | None = None,
        source: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """Page or filter the already-scored study pool by page, evidence_level, or source. Does not re-rank or reset screening."""
        await bridge.on_tool_start("browse_studies", {"page": page, "evidence_level": evidence_level, "source": source})
        result = await tool_browse_studies(request, bridge, page, evidence_level, source, page_size)
        await bridge.on_tool_end("browse_studies", result)
        return _langchain_tool_json("browse_studies", result)

    @lc_tool
    async def screen_studies(
        included_indices: list[int],
        excluded_indices: list[int] | None = None,
        exclusion_reasons: list[str] | None = None,
    ) -> str:
        """Whitelist screening: ONLY included_indices survive; every other study is dropped. Pass excluded_indices (+ reasons) to name notable exclusions."""
        await bridge.on_tool_start("screen_studies", {"included": len(included_indices)})
        result = await tool_screen_studies(
            request, bridge, included_indices, excluded_indices or [], exclusion_reasons or []
        )
        await bridge.on_tool_end("screen_studies", result)
        return _langchain_tool_json("screen_studies", result)

    @lc_tool
    async def finalize_ranking(ranked_indices: list[int], rationale: str = "") -> str:
        """Submit your ranking after reviewing studies. Pass ordered indices (best first)."""
        await bridge.on_tool_start("finalize_ranking", {"count": len(ranked_indices)})
        result = await tool_finalize_ranking(request, bridge, ranked_indices, rationale)
        await bridge.on_tool_end("finalize_ranking", result)
        return _langchain_tool_json("finalize_ranking", result)

    @lc_tool
    async def appraise_evidence(
        findings: list[str],
        certainties: list[str],
        rationales: list[str] | None = None,
        reference_numbers_csv: list[str] | None = None,
    ) -> str:
        """Record GRADE certainty (High/Moderate/Low/Very Low) per major finding, with rationale and supporting [n]."""
        await bridge.on_tool_start("appraise_evidence", {"findings": len(findings)})
        result = await tool_appraise_evidence(
            request, bridge, findings, certainties, rationales or [], reference_numbers_csv or []
        )
        await bridge.on_tool_end("appraise_evidence", result)
        return _langchain_tool_json("appraise_evidence", result)

    @lc_tool
    async def verify_studies() -> str:
        """Verify PMIDs of the ranked studies against PubMed."""
        await bridge.on_tool_start("verify_studies", {})
        result = await tool_verify_studies(request, bridge)
        await bridge.on_tool_end("verify_studies", result)
        return _langchain_tool_json("verify_studies", result)

    @lc_tool
    async def synthesize_report() -> str:
        """Returns structured evidence data for writing the final report."""
        await bridge.on_tool_start("synthesize_report", {})
        result = await tool_synthesize_report(request, bridge)
        await bridge.on_tool_end("synthesize_report", result)
        return _langchain_tool_json("synthesize_report", result)

    @lc_tool
    async def submit_report(report_markdown: str) -> str:
        """Submit your completed research report (full markdown). MUST be called as the last step."""
        tool_input: dict[str, Any] = {"length": len(report_markdown)}
        if bridge.full_trace_enabled:
            tool_input["report_markdown"] = report_markdown
        await bridge.on_tool_start("submit_report", tool_input)
        result = await tool_submit_report(request, bridge, report_markdown)
        await bridge.on_tool_end("submit_report", result)
        if result.get("fatal"):
            raise _ReportRejected(str(result.get("fallback_reason") or result.get("error")))
        if stop_after_report_rejection and result.get("error") and result.get("rejection_count"):
            raise _ReportRecoveryRequested(str(result.get("error")))
        if stop_after_submit and result.get("status") == "ok":
            raise _ReportSubmitted()
        return _langchain_tool_json("submit_report", result)

    @lc_tool
    async def fetch_fulltext() -> str:
        """Look up free full-text PDFs via Unpaywall + PMC for Level I & II ranked studies."""
        await bridge.on_tool_start("fetch_fulltext", {})
        result = await tool_fetch_fulltext(request, bridge)
        await bridge.on_tool_end("fetch_fulltext", result)
        return _langchain_tool_json("fetch_fulltext", result)

    @lc_tool
    async def await_user_pdfs(ranks: list[int]) -> str:
        """Pause until the user uploads PDFs and clicks Continue, or clicks Skip."""
        await bridge.on_tool_start("await_user_pdfs", {"ranks": ranks})
        result = await tool_await_user_pdfs(request, bridge, ranks)
        await bridge.on_tool_end("await_user_pdfs", result)
        return _langchain_tool_json("await_user_pdfs", result)

    @lc_tool
    async def parse_pdf(rank: int) -> str:
        """Download and parse a full-text PDF to markdown."""
        await bridge.on_tool_start("parse_pdf", {"rank": rank})
        result = await tool_parse_pdf(request, bridge, rank)
        await bridge.on_tool_end("parse_pdf", result)
        return _langchain_tool_json("parse_pdf", result)

    return [
        plan_search, suggest_databases, write_todos, update_progress,
        *search_tools,
        get_references, get_citations,
        get_studies, browse_studies, screen_studies, finalize_ranking, appraise_evidence,
        verify_studies, synthesize_report, submit_report,
        fetch_fulltext, await_user_pdfs, parse_pdf,
    ]


# ---------------------------------------------------------------------------
# Anthropic via constrained LangChain agent
# ---------------------------------------------------------------------------

class AnthropicRuntime(NativeSDKRuntime):
    provider = "anthropic"
    runtime_name = "Anthropic LangChain Agent"
    sdk_module = "langchain_anthropic"
    runtime_engine = "langchain_anthropic"
    planner_name = "Claude Planner"
    search_agent_name = "Claude Search Agent"
    synthesis_agent_name = "Claude Synthesis Agent"
    verifier_name = "Claude Verification Agent"
    native_agent_name = "Claude Research Agent"
    agentic_timeout_seconds = _env_float("MDR_ANTHROPIC_AGENTIC_TIMEOUT_SECONDS", 600.0)
    first_tool_timeout_seconds = _env_float("MDR_ANTHROPIC_FIRST_TOOL_TIMEOUT_SECONDS", 120.0)
    max_retries = _env_int("MDR_ANTHROPIC_MAX_RETRIES", 5)

    @property
    def sdk_available(self) -> bool:
        required = ("langchain", "langchain_anthropic", "langchain_core")
        return all(importlib.util.find_spec(module) is not None for module in required)

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return

        bridge = AgenticEventBridge()
        tools = _build_langchain_tools(request, bridge, stop_after_submit=True)

        yield _agentic_run_started(self, request, bridge)
        yield _agentic_agent_started(self.native_agent_name, bridge)

        env_updates = _provider_api_env(self.provider, request.api_keys)
        _env_ctx = _temporary_env(env_updates)
        _env_ctx.__enter__()
        agent_task = asyncio.create_task(
            self._run_langchain_agent(request, bridge, tools)
        )

        while True:
            timeout = self.first_tool_timeout_seconds if bridge._tool_call_count == 0 else None
            try:
                queued: RuntimeEventPayload | None = await asyncio.wait_for(bridge.queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                if bridge._tool_call_count == 0 and not agent_task.done():
                    bridge._intermediate["startup_timeout_reason"] = (
                        f"{self.runtime_name} did not begin tool use within "
                        f"{self.first_tool_timeout_seconds:g}s; running deterministic fallback."
                    )
                    agent_task.cancel()
                    break
                continue
            if queued is None:
                break
            yield queued

        try:
            await agent_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _log.warning("Anthropic LangChain agent task error: %s", exc)
            bridge.set_error(exc)
        finally:
            _env_ctx.__exit__(None, None, None)

        debug_event = _agentic_debug_trace_event(bridge)
        if debug_event:
            yield debug_event

        fallback_reason = self._agentic_fallback_reason(bridge)
        if fallback_reason:
            failure_diagnostics = _agentic_failure_diagnostics(bridge)
            yield _ev(
                bridge.progress,
                EventType.AGENT_STARTED,
                bridge.progress.current_phase or "planning",
                f"{fallback_reason} Running deterministic fallback.",
                agent_name=self.native_agent_name,
                extra={
                    "fallback_reason": fallback_reason,
                    "tool_calls": bridge._tool_call_count,
                    "had_error": bridge._error is not None,
                    "error_message": _format_exception(bridge._error),
                    "execution_mode": "deterministic_fallback",
                    "runtime_engine": self.runtime_engine,
                    "source_execution_mode": "native_sdk_agentic",
                    "report_source": "deterministic_fallback",
                    **failure_diagnostics,
                },
            )
            fallback_runtime = AgenticFailureFallbackRuntime(
                self, fallback_reason, failure_diagnostics, tracker=bridge.progress
            )
            async for event in fallback_runtime.stream_run(request):
                yield event
            return

        agent_text = bridge._result or ""
        final_report, report_source = _select_agentic_final_report(
            request, bridge, self.runtime_name, agent_text
        )

        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for evt in translate_events:
            yield evt

        for event in _agentic_final_events(self, request, final_report, bridge, report_source=report_source):
            yield event

    def _agentic_fallback_reason(self, bridge: AgenticEventBridge) -> str | None:
        startup_timeout_reason = bridge._intermediate.get("startup_timeout_reason")
        if startup_timeout_reason:
            return str(startup_timeout_reason)
        submitted = bridge._intermediate.get("submitted_report")
        if isinstance(submitted, str) and submitted.strip():
            return None
        if bridge._error is not None:
            if isinstance(bridge._error, TimeoutError):
                return (
                    f"{self.runtime_name} timed out before submitting a final report "
                    f"({_format_exception(bridge._error)})."
                )
            if not bridge.search_results:
                return (
                    f"{self.runtime_name} failed before completing any search tools "
                    f"({_format_exception(bridge._error)})."
                )
            return (
                f"{self.runtime_name} failed before submitting a final report "
                f"({_format_exception(bridge._error)})."
            )
        if not bridge.search_results:
            if bridge._tool_call_count > 0:
                return f"{self.runtime_name} completed without executing any search tools."
            return f"{self.runtime_name} completed without calling any research tools."
        return None

    async def _run_langchain_agent(
        self,
        request: RunRequest,
        bridge: AgenticEventBridge,
        tools: list[Any],
    ) -> None:
        try:
            from langchain.agents import create_agent
            from langchain_anthropic import ChatAnthropic

            model = ChatAnthropic(
                model_name=request.model,
                max_retries=self.max_retries,
                temperature=0.1,
                timeout=60.0,
            )
            system_prompt = _anthropic_cached_system_prompt(
                agentic_system_prompt(request, self.runtime_name)
            )

            agent = create_agent(
                model=model,
                tools=tools,
                system_prompt=system_prompt,
            )

            final_text: str | None = None

            async def _inner() -> None:
                nonlocal final_text
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": _agentic_user_prompt(request)}]},
                )
                bridge.capture_agent_result(result)
                final_text = _langchain_final_text(result)

            await asyncio.wait_for(_inner(), timeout=self.agentic_timeout_seconds)
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except _ReportSubmitted:
            bridge._intermediate["agent_final_message"] = "Report accepted by submit_report."
        except _ReportRejected as exc:
            _log.warning("Anthropic LangChain agent stopped after repeated report rejection: %s", exc)
            bridge.set_error(exc)
        except asyncio.TimeoutError:
            _log.warning("Anthropic LangChain agent timed out after %ss", self.agentic_timeout_seconds)
            exc = TimeoutError(f"Agent timed out after {self.agentic_timeout_seconds}s")
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["post_submit_error_message"] = _format_exception(exc)
                bridge._intermediate["post_submit_error_type"] = type(exc).__name__
            else:
                bridge.set_error(exc)
        except Exception as exc:
            _log.warning("Anthropic LangChain agent failed: %s", exc)
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["post_submit_error_message"] = _format_exception(exc)
                bridge._intermediate["post_submit_error_type"] = type(exc).__name__
            else:
                bridge.set_error(exc)
        finally:
            await bridge.queue.put(None)

    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        from langchain.agents import create_agent

        with _temporary_env(_provider_api_env(self.provider, request.api_keys)):
            agent = create_agent(
                model=f"anthropic:{request.model}",
                tools=[],
                system_prompt=instructions,
            )
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
            )
        text = _langchain_final_text(result)
        if text is None:
            raise RuntimeError(f"Anthropic LangChain agent did not return a {task_name} result.")
        return _coerce_model_output(text, output_model)


class LangChainLocalRuntime(NativeSDKRuntime):
    provider = "local"
    runtime_name = "LangChain Local LLM"
    sdk_module = "langchain_core"
    runtime_engine = "langchain"
    planner_name = "Local Planner"
    search_agent_name = "Local Search Agent"
    synthesis_agent_name = "Local Synthesis Agent"
    verifier_name = "Local Verification Agent"
    native_agent_name = "Local LLM Research Agent"

    @property
    def sdk_available(self) -> bool:
        required = ("langchain_core", "langchain_openai")
        return all(importlib.util.find_spec(module) is not None for module in required)

    def _should_fallback(self, request: RunRequest) -> bool:
        if request.offline_mode:
            return True
        if not self.sdk_available:
            return True
        # Local LLMs don't need provider API keys — just check model config
        return False

    def _resolve_chat_model(self, request: RunRequest) -> Any:
        """Instantiate the appropriate LangChain chat model for local inference."""
        model = request.model or "llama3.1"
        base_url = local_base_url(request.api_keys)

        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=request.api_keys.get("local") or os.environ.get("MDR_LOCAL_API_KEY") or "local",
            temperature=0.1,
            disabled_params={"parallel_tool_calls": None},
        )

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return


        bridge = AgenticEventBridge()
        tools = _build_langchain_tools(
            request,
            bridge,
            stop_after_submit=True,
            stop_after_report_rejection=self.provider == "local",
        )

        yield _agentic_run_started(self, request, bridge)
        yield _agentic_agent_started(self.native_agent_name, bridge)

        agent_task = asyncio.create_task(
            self._run_langchain_agent(request, bridge, tools)
        )

        while True:
            queued: RuntimeEventPayload | None = await bridge.queue.get()
            if queued is None:
                break
            yield queued

        try:
            await agent_task
        except Exception as exc:
            _log.warning("LangChain local agent task error: %s", exc)
            bridge.set_error(exc)

        agent_text = bridge._result or ""
        final_report, report_source = _select_agentic_final_report(
            request, bridge, self.runtime_name, agent_text
        )

        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for evt in translate_events:
            yield evt

        for event in _agentic_final_events(self, request, final_report, bridge, report_source=report_source):
            yield event

    async def _run_langchain_agent(
        self,
        request: RunRequest,
        bridge: AgenticEventBridge,
        tools: list[Any],
    ) -> None:
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            from langgraph.prebuilt import create_react_agent

            llm = self._resolve_chat_model(request)
            agent = create_react_agent(
                llm,
                tools,
                prompt=SystemMessage(content=agentic_system_prompt(request, self.runtime_name)),
            )

            final_text: str | None = None

            async def _inner() -> None:
                nonlocal final_text
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=_agentic_user_prompt(request))]},
                )
                final_text = _langchain_final_text(result)

            await _inner()
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except _ReportSubmitted:
            bridge._intermediate["agent_final_message"] = "Report accepted by submit_report."
        except _ReportRecoveryRequested as exc:
            bridge._intermediate["agent_final_message"] = "Stopped after submit_report rejection; recovered from shared research state."
            bridge._intermediate["local_recovered_after_submit_rejection"] = str(exc)
        except _ReportRejected as exc:
            _log.warning("LangChain local agent stopped after repeated report rejection: %s", exc)
            bridge.set_error(exc)
        except asyncio.TimeoutError:
            _log.warning("LangChain local agent timed out after %ss", LOCAL_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_error(TimeoutError(f"Agent timed out after {LOCAL_AGENTIC_TIMEOUT_SECONDS}s"))
        except Exception as exc:
            _log.warning("LangChain local agent failed: %s", exc)
            bridge.set_error(exc)
        finally:
            await bridge.queue.put(None)

    # Legacy structured checkpoint (not used for local, but satisfies ABC)
    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type[TModel],
    ) -> TModel:
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = self._resolve_chat_model(request)
        result = await llm.ainvoke([
            SystemMessage(content=instructions),
            HumanMessage(content=prompt),
        ])
        return _coerce_model_output(result.content, output_model)


class DeepSeekRuntime(LangChainLocalRuntime):
    provider = "deepseek"
    runtime_name = "DeepSeek Chat API"
    runtime_engine = "langchain_deepseek"
    planner_name = "DeepSeek Planner"
    search_agent_name = "DeepSeek Search Agent"
    synthesis_agent_name = "DeepSeek Synthesis Agent"
    verifier_name = "DeepSeek Verification Agent"
    native_agent_name = "DeepSeek Research Agent"

    def _should_fallback(self, request: RunRequest) -> bool:
        return provider_fallback_reason(self, request) is not None

    def _resolve_chat_model(self, request: RunRequest) -> Any:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=normalize_model_id("deepseek", request.model) or "deepseek-v4-pro",
            base_url=DEEPSEEK_BASE_URL,
            api_key=deepseek_api_key(request.api_keys),
            temperature=0.1,
            reasoning_effort=deepseek_reasoning_effort(),
            extra_body=deepseek_thinking_body(),
            disabled_params={"parallel_tool_calls": None},
        )


class GoogleRuntime(LangChainLocalRuntime):
    provider = "google"
    runtime_name = "Google LangChain Agent"
    sdk_module = "langchain_google_genai"
    runtime_engine = "langchain_google_genai"
    planner_name = "Gemini Planner"
    search_agent_name = "Gemini Search Agent"
    synthesis_agent_name = "Gemini Synthesis Agent"
    verifier_name = "Gemini Verification Agent"
    native_agent_name = "Gemini Research Agent"

    @property
    def sdk_available(self) -> bool:
        required = ("langchain_core", "langchain_google_genai", "langgraph")
        return all(importlib.util.find_spec(module) is not None for module in required)

    def _should_fallback(self, request: RunRequest) -> bool:
        return provider_fallback_reason(self, request) is not None

    def _resolve_chat_model(self, request: RunRequest) -> Any:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=normalize_model_id("google", request.model) or "gemini-2.5-flash",
            api_key=request.api_keys.get("google")
            or request.api_keys.get("gemini")
            or os.environ.get("GOOGLE_API_KEY"),
            temperature=0.1,
            request_timeout=60.0,
        )


# ---------------------------------------------------------------------------
# Runtime factory
# ---------------------------------------------------------------------------

def build_runtime(provider: str) -> ResearchRuntime:
    if provider == "anthropic":
        if os.getenv("MDR_ANTHROPIC_RUNTIME", "").strip().lower() == "claude_sdk":
            return ClaudeSDKAnthropicRuntime()
        return AnthropicRuntime()
    if provider == "google":
        return GoogleRuntime()
    if provider == "deepseek":
        return DeepSeekRuntime()
    if provider == "local":
        return LangChainLocalRuntime()
    return OpenAIRuntime()


ScriptedRuntime = DeterministicRuntime
