from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sys
from abc import ABC, abstractmethod
from contextlib import contextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, TypeVar

from pydantic import BaseModel
from sqlmodel import Field

from .models import ArtifactType, EventType, RunRequest, RuntimeEventPayload
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
from .agentic_tools import (
    AgenticEventBridge,
    TOOL_DESCRIPTIONS,
    agentic_system_prompt,
    recover_report_from_bridge,
    report_quality_issues,
    tool_fetch_fulltext,
    tool_finalize_ranking,
    tool_get_studies,
    tool_parse_pdf,
    tool_plan_search,
    tool_search,
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
SEARCH_GUIDANCE_TIMEOUT_SECONDS = 20.0
REWIND_DECISION_TIMEOUT_SECONDS = 15.0
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


def _google_text_from_event(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = [part.text for part in parts if getattr(part, "text", None)]
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
        plan = build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
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
                start_year=request.search_start_year,
                scopus_view=request.scopus_view,
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
        translation_bridge = AgenticEventBridge()
        final_report, translate_events = await _maybe_translate_report(request, translation_bridge, final_report)
        for evt in translate_events:
            yield evt
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
    ) -> None:
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
                    "runtime_engine": self.runtime_engine,
                    "provider_credentials_present": _has_native_credentials(self.provider, request.api_keys),
                    "search_credentials_present": _search_credentials_present(request.api_keys),
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
                start_year=request.search_start_year,
                scopus_view=request.scopus_view,
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

        base_plan = build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
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

def _agentic_run_started(runtime: ResearchRuntime, request: RunRequest) -> RuntimeEventPayload:
    return RuntimeEventPayload(
        event_type=EventType.RUN_STARTED,
        phase="planning",
        progress=5,
        message=f"Starting agentic {runtime.runtime_name} research run",
        extra={
            "sdk_available": runtime.sdk_available,
            "offline_mode": request.offline_mode,
            "execution_mode": "native_sdk_agentic",
            "runtime_engine": runtime.runtime_engine,
            "provider_credentials_present": _has_native_credentials(runtime.provider, request.api_keys),
            "search_credentials_present": _search_credentials_present(request.api_keys),
        },
    )


def _agentic_agent_started(agent_name: str) -> RuntimeEventPayload:
    return RuntimeEventPayload(
        event_type=EventType.AGENT_STARTED,
        phase="planning",
        progress=7,
        message=f"{agent_name} is autonomously driving the research workflow",
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
    events.append(RuntimeEventPayload(
        event_type=EventType.ARTIFACT_CREATED,
        phase="translating",
        progress=96,
        message="Saved original English report",
        artifact_type=ArtifactType.FINAL_REPORT,
        artifact_name="Report (English)",
        artifact_text=report,
    ))
    events.append(RuntimeEventPayload(
        event_type=EventType.AGENT_STARTED,
        phase="translating",
        progress=97,
        message=f"Translating report to {request.language}",
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
        RuntimeEventPayload(
            event_type=EventType.REPORT_DELTA,
            phase="synthesizing",
            progress=97,
            message="Report assembled from agentic research workflow",
            report_markdown=final_report,
        ),
        RuntimeEventPayload(
            event_type=EventType.ARTIFACT_CREATED,
            phase="complete",
            progress=100,
            message="Saved final report artifact",
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=final_report,
        ),
        RuntimeEventPayload(
            event_type=EventType.RUN_COMPLETED,
            phase="complete",
            progress=100,
            message=f"{runtime.runtime_name} agentic run completed",
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
    "search_openalex": "OpenAlex",
    "search_cochrane": "Cochrane",
    "search_semantic_scholar": "Semantic Scholar",
    "search_scopus": "Scopus",
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
                "max_results": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        }, lambda a, s=_src: tool_search(request, bridge, s, a["query"], a.get("max_results", 8))))

    # Evidence tools
    tools.append(_wrap("get_studies", {
        "type": "object",
        "properties": {"context": {"type": "string", "default": "general"}},
    }, lambda a: tool_get_studies(request, bridge, a.get("context", "general"))))

    tools.append(_wrap("finalize_ranking", {
        "type": "object",
        "properties": {
            "ranked_indices": {"type": "array", "items": {"type": "integer"}},
            "rationale": {"type": "string", "default": ""},
        },
        "required": ["ranked_indices"],
    }, lambda a: tool_finalize_ranking(request, bridge, a.get("ranked_indices", []), a.get("rationale", ""))))

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

        yield _agentic_run_started(self, request)
        yield _agentic_agent_started(self.native_agent_name)

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
            result = await tool_search(request, bridge, source, args["query"], args.get("max_results", 8))
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        return _search

    literature_server = create_sdk_mcp_server("literature", tools=[
        plan_search_tool,
        suggest_databases_tool,
        *[_make_search_tool(src, name) for name, src in _SEARCH_SOURCES.items()],
    ])

    # -- Evidence tools ------------------------------------------------------

    @tool("get_studies", TOOL_DESCRIPTIONS["get_studies"], {"context": str})
    async def get_studies_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_get_studies(request, bridge, args.get("context", "general"))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("finalize_ranking", TOOL_DESCRIPTIONS["finalize_ranking"], {"ranked_indices": list, "rationale": str})
    async def finalize_ranking_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_finalize_ranking(request, bridge, args.get("ranked_indices", []), args.get("rationale", ""))
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
        get_studies_tool,
        finalize_ranking_tool,
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

    @tool("parse_pdf", TOOL_DESCRIPTIONS["parse_pdf"], {"rank": int})
    async def parse_pdf_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = await tool_parse_pdf(request, bridge, args.get("rank", 1))
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

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

        yield _agentic_run_started(self, request)
        yield _agentic_agent_started(self.native_agent_name)

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
                "mcp__evidence__get_studies", "mcp__evidence__finalize_ranking",
                "mcp__evidence__verify_studies", "mcp__evidence__synthesize_report",
                "mcp__evidence__submit_report",
                "mcp__fulltext__fetch_fulltext", "mcp__fulltext__parse_pdf",
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
            yield RuntimeEventPayload(
                event_type=EventType.AGENT_STARTED,
                phase="searching",
                progress=12,
                message=f"{startup_fallback_reason} Running deterministic fallback.",
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
            fallback_runtime = AgenticFailureFallbackRuntime(self, startup_fallback_reason, failure_diagnostics)
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
# Google ADK — agentic runtime (using shared tools)
# ---------------------------------------------------------------------------

def _build_google_tools(request: RunRequest, bridge: AgenticEventBridge) -> list[Any]:
    """Build plain async callables with type annotations for Google ADK."""

    async def plan_search(query: str, query_type: str = "free") -> dict:
        """Build a search plan. Returns keywords, databases, and source queries."""
        return await tool_plan_search(request, bridge, query, query_type)

    async def suggest_databases(query: str) -> dict:
        """Suggest database coverage for a research query."""
        return await tool_suggest_databases(request, bridge, query)

    async def write_todos(items: list[str]) -> dict:
        """Create a research TODO list to plan the workflow."""
        return await tool_write_todos(request, bridge, items)

    async def update_progress(phase: str, message: str) -> dict:
        """Signal a phase transition or progress update to the user."""
        return await tool_update_progress(request, bridge, phase, message)

    async def search_pubmed(query: str, max_results: int = 8) -> dict:
        """Search PubMed for medical literature."""
        return await tool_search(request, bridge, "PubMed", query, max_results)

    async def search_openalex(query: str, max_results: int = 8) -> dict:
        """Search OpenAlex for open-access academic papers."""
        return await tool_search(request, bridge, "OpenAlex", query, max_results)

    async def search_cochrane(query: str, max_results: int = 8) -> dict:
        """Search Cochrane for systematic reviews."""
        return await tool_search(request, bridge, "Cochrane", query, max_results)

    async def search_semantic_scholar(query: str, max_results: int = 8) -> dict:
        """Search Semantic Scholar for academic papers."""
        return await tool_search(request, bridge, "Semantic Scholar", query, max_results)

    async def search_scopus(query: str, max_results: int = 8) -> dict:
        """Search Scopus for academic citations."""
        return await tool_search(request, bridge, "Scopus", query, max_results)

    async def get_studies(context: str = "general") -> dict:
        """Deduplicate and pre-score ALL collected studies. Returns full details for your review."""
        return await tool_get_studies(request, bridge, context)

    async def finalize_ranking(ranked_indices: list[int], rationale: str = "") -> dict:
        """Submit your ranking after reviewing studies. Pass ordered indices (best first)."""
        return await tool_finalize_ranking(request, bridge, ranked_indices, rationale)

    async def verify_studies_fn() -> dict:
        """Verify PMIDs of the ranked studies against PubMed."""
        return await tool_verify_studies(request, bridge)

    async def synthesize_report() -> dict:
        """Returns structured evidence data for writing the final report."""
        return await tool_synthesize_report(request, bridge)

    async def submit_report(report_markdown: str) -> dict:
        """Submit your completed research report (full markdown). MUST be called as the last step."""
        return await tool_submit_report(request, bridge, report_markdown)

    async def fetch_fulltext() -> dict:
        """Look up free full-text PDFs via Unpaywall + PMC for Level I and II ranked studies."""
        return await tool_fetch_fulltext(request, bridge)

    async def parse_pdf(rank: int) -> dict:
        """Download and parse a full-text PDF to markdown."""
        return await tool_parse_pdf(request, bridge, rank)

    # Google ADK requires the function name attribute; rename verify wrapper
    verify_studies_fn.__name__ = "verify_studies"
    verify_studies_fn.__qualname__ = "verify_studies"

    return [
        plan_search, suggest_databases, write_todos, update_progress,
        search_pubmed, search_openalex, search_cochrane,
        search_semantic_scholar, search_scopus,
        get_studies, finalize_ranking, verify_studies_fn,
        synthesize_report, submit_report, fetch_fulltext, parse_pdf,
    ]


class GoogleRuntime(NativeSDKRuntime):
    provider = "google"
    runtime_name = "Google ADK"
    sdk_module = "google.adk"
    runtime_engine = "google_adk"
    planner_name = "ADK Planner"
    search_agent_name = "ADK Search Workflow"
    synthesis_agent_name = "ADK Synthesis Workflow"
    verifier_name = "ADK Verification Workflow"
    native_agent_name = "Google ADK Research Agent"

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return

        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types as genai_types

        bridge = AgenticEventBridge()
        tools = _build_google_tools(request, bridge)

        yield _agentic_run_started(self, request)
        yield _agentic_agent_started(self.native_agent_name)

        async def _before_tool(tool: Any, args: dict[str, Any], **kwargs: Any) -> None:
            name = str(getattr(tool, "name", None) or getattr(tool, "__name__", "tool"))
            await bridge.on_tool_start(name, args)

        async def _after_tool(tool: Any, args: dict[str, Any], result: Any = None, **kwargs: Any) -> None:
            name = str(getattr(tool, "name", None) or getattr(tool, "__name__", "tool"))
            await bridge.on_tool_end(name, result)

        # Set env vars for the entire agent run — they must persist until the task finishes
        _env_ctx = _temporary_env(_provider_api_env(self.provider, request.api_keys))
        _env_ctx.__enter__()

        agent = Agent(
            name="google_research_agent",
            description=f"{self.runtime_name} medical literature research agent",
            model=request.model,
            instruction=agentic_system_prompt(request, self.runtime_name),
            tools=tools,
            before_tool_callback=_before_tool,  # type: ignore[arg-type]
            after_tool_callback=_after_tool,  # type: ignore[arg-type]
        )
        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            app_name="MedicalDeepResearch",
            session_service=session_service,
            auto_create_session=True,
        )

        agent_task = asyncio.create_task(
            self._run_google_agent(runner, request, bridge, genai_types)
        )

        while True:
            queued: RuntimeEventPayload | None = await bridge.queue.get()
            if queued is None:
                break
            yield queued

        try:
            await agent_task
        except Exception as exc:
            _log.warning("Google ADK agentic task error: %s", exc)
            bridge.set_error(exc)
        finally:
            _env_ctx.__exit__(None, None, None)

        agent_text = bridge._result or ""
        final_report, report_source = _select_agentic_final_report(
            request, bridge, self.runtime_name, agent_text
        )

        # Translate if non-English
        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for evt in translate_events:
            yield evt

        for event in _agentic_final_events(self, request, final_report, bridge, report_source=report_source):
            yield event

    async def _run_google_agent(
        self,
        runner: Any,
        request: RunRequest,
        bridge: AgenticEventBridge,
        genai_types: Any,
    ) -> None:
        try:
            final_text: str | None = None

            async def _inner() -> None:
                nonlocal final_text
                async for event in runner.run_async(
                    user_id=request.run_id,
                    session_id=f"{request.run_id}-agentic",
                    new_message=genai_types.UserContent(
                        parts=[genai_types.Part(text=_agentic_user_prompt(request))]
                    ),
                ):
                    if event.is_final_response():
                        text = _google_text_from_event(event)
                        if text:
                            final_text = text

            await asyncio.wait_for(_inner(), timeout=ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except asyncio.TimeoutError:
            _log.warning("Google ADK agentic run timed out after %ss", ANTHROPIC_AGENTIC_TIMEOUT_SECONDS)
            bridge.set_error(TimeoutError(f"Agent timed out after {ANTHROPIC_AGENTIC_TIMEOUT_SECONDS}s"))
        except Exception as exc:
            _log.warning("Google ADK agentic run failed: %s", exc)
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
            "studies": [_compact_study_dict(study, abstract_chars=220) for study in studies[:6]],
            "truncated_studies": max(0, len(studies) - 6),
        }

    if tool_name == "get_studies":
        studies = result.get("studies") if isinstance(result.get("studies"), list) else []
        payload = {key: result.get(key) for key in ("error", "total", "context") if result.get(key) is not None}
        payload["studies"] = [_compact_study_dict(study, abstract_chars=240) for study in studies[:20]]
        payload["truncated_studies"] = max(0, len(studies) - 20)
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
        compact["studies"] = [_compact_study_dict(study, abstract_chars=320) for study in studies[:12]]
        compact["truncated_studies"] = max(0, len(studies) - 12)
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
        async def _search(query: str, max_results: int = 8) -> str:
            """Search a medical literature database."""
            await bridge.on_tool_start(tool_name, {"query": query})
            result = await tool_search(request, bridge, source, query, min(max(int(max_results or 1), 1), 6))
            await bridge.on_tool_end(tool_name, result)
            return _langchain_tool_json(tool_name, result)
        _search.description = TOOL_DESCRIPTIONS[tool_name]
        return _search

    search_tools = [_make_search(name, src) for name, src in _SEARCH_SOURCES.items()]

    @lc_tool
    async def get_studies(context: str = "general") -> str:
        """Deduplicate and pre-score ALL collected studies. Returns full details for your review."""
        await bridge.on_tool_start("get_studies", {"context": context})
        result = await tool_get_studies(request, bridge, context)
        await bridge.on_tool_end("get_studies", result)
        return _langchain_tool_json("get_studies", result)

    @lc_tool
    async def finalize_ranking(ranked_indices: list[int], rationale: str = "") -> str:
        """Submit your ranking after reviewing studies. Pass ordered indices (best first)."""
        await bridge.on_tool_start("finalize_ranking", {"count": len(ranked_indices)})
        result = await tool_finalize_ranking(request, bridge, ranked_indices, rationale)
        await bridge.on_tool_end("finalize_ranking", result)
        return _langchain_tool_json("finalize_ranking", result)

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
        await bridge.on_tool_start("submit_report", {"length": len(report_markdown)})
        result = await tool_submit_report(request, bridge, report_markdown)
        await bridge.on_tool_end("submit_report", result)
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
    async def parse_pdf(rank: int) -> str:
        """Download and parse a full-text PDF to markdown."""
        await bridge.on_tool_start("parse_pdf", {"rank": rank})
        result = await tool_parse_pdf(request, bridge, rank)
        await bridge.on_tool_end("parse_pdf", result)
        return _langchain_tool_json("parse_pdf", result)

    return [
        plan_search, suggest_databases, write_todos, update_progress,
        *search_tools,
        get_studies, finalize_ranking, verify_studies, synthesize_report, submit_report,
        fetch_fulltext, parse_pdf,
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

        yield _agentic_run_started(self, request)
        yield _agentic_agent_started(self.native_agent_name)

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

        fallback_reason = self._agentic_fallback_reason(bridge)
        if fallback_reason:
            failure_diagnostics = _agentic_failure_diagnostics(bridge)
            yield RuntimeEventPayload(
                event_type=EventType.AGENT_STARTED,
                phase="searching",
                progress=12,
                message=f"{fallback_reason} Running deterministic fallback.",
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
            fallback_runtime = AgenticFailureFallbackRuntime(self, fallback_reason, failure_diagnostics)
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
                final_text = _langchain_final_text(result)

            await asyncio.wait_for(_inner(), timeout=self.agentic_timeout_seconds)
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
        except _ReportSubmitted:
            bridge._intermediate["agent_final_message"] = "Report accepted by submit_report."
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
        return importlib.util.find_spec("langchain_core") is not None

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
        base_url = (
            request.api_keys.get("local_base_url")
            or os.environ.get("MDR_LOCAL_BASE_URL")
        )

        # If base_url is explicitly set, use OpenAI-compatible endpoint (LM Studio, vLLM, etc.)
        if base_url:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key=request.api_keys.get("local") or "not-needed",  # type: ignore[arg-type]
                temperature=0.1,
            )

        # Default: Ollama
        from langchain_ollama import ChatOllama
        ollama_base = (
            request.api_keys.get("ollama_base_url")
            or os.environ.get("MDR_OLLAMA_BASE_URL")
            or "http://localhost:11434"
        )
        return ChatOllama(
            model=model,
            base_url=ollama_base,
            temperature=0.1,
        )

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        if self._should_fallback(request):
            async for event in DeterministicRuntime.stream_run(self, request):
                yield event
            return


        bridge = AgenticEventBridge()
        tools = _build_langchain_tools(request, bridge)

        yield _agentic_run_started(self, request)
        yield _agentic_agent_started(self.native_agent_name)

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

            await asyncio.wait_for(_inner(), timeout=LOCAL_AGENTIC_TIMEOUT_SECONDS)
            if "submitted_report" in bridge._intermediate:
                bridge._intermediate["agent_final_message"] = final_text
            else:
                bridge.set_result(final_text)
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
    if provider == "local":
        return LangChainLocalRuntime()
    return OpenAIRuntime()


ScriptedRuntime = DeterministicRuntime
