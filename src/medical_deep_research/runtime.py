from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from contextlib import contextmanager, suppress
from json import JSONDecodeError
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, TypeVar

from pydantic import BaseModel
from sqlmodel import Field

from .codex_auth import check_codex_runtime
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
    build_audit_report,
    build_prisma_summary,
    build_query_plan,
    empty_verification_summary,
    flatten_studies,
    render_report,
    render_verification_report,
    score_and_rank_results,
    search_source,
    source_catalog,
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
OPENAI_MCP_TIMEOUT_SECONDS = 60.0
GOOGLE_MCP_TIMEOUT_SECONDS = 20.0
LITERATURE_TOOL_FILTER = ["aggregate_search"]
EVIDENCE_TOOL_FILTER = ["rank_results", "verify_results", "synthesize_report"]
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
CODEX_AGENTIC_TIMEOUT_SECONDS = 1800.0
CODEX_AGENTIC_HEARTBEAT_SECONDS = 15.0
CODEX_AGENTIC_MAX_TOOL_TURNS = 50
CODEX_FULLTEXT_PARSE_LIMIT = 8
CODEX_REQUIRED_MCP_TOOLS = {"aggregate_search", "rank_results", "verify_results", "synthesize_report"}
CODEX_PHASE1_MCP_TOOLS = {"aggregate_search", "rank_results"}
CODEX_PHASE2_MCP_TOOLS = {"verify_results", "synthesize_report"}
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


class CodexCompletionOutput(BaseModel):
    final_report: str


class CodexPhaseOutput(BaseModel):
    status: str


class CodexToolDecision(BaseModel):
    tool_name: str
    arguments_json: str


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


def _codex_auth_cache_present(codex_home_path: str | None = None) -> bool:
    home = Path(codex_home_path) if codex_home_path else Path(os.getenv("CODEX_HOME") or Path.home() / ".codex")
    home = home.expanduser().resolve()
    auth_path = home / "auth.json"
    try:
        return auth_path.is_file() and auth_path.stat().st_size > 0
    except OSError:
        return False


def _has_native_credentials(
    provider: str,
    api_keys: dict[str, str],
    *,
    codex_home_path: str | None = None,
) -> bool:
    if provider == "local":
        return True
    if provider == "codex":
        return _codex_auth_cache_present(codex_home_path)
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
        if runtime.provider == "codex":
            runtime_status = check_codex_runtime()
            return runtime_status.error or f"{runtime.runtime_name} is not installed."
        return f"{runtime.runtime_name} is not installed."
    if runtime.runtime_engine == "claude_sdk_legacy":
        dependency_reason = _legacy_claude_sdk_dependency_reason()
        if dependency_reason:
            return dependency_reason
    if not _has_native_credentials(runtime.provider, request.api_keys, codex_home_path=request.codex_home_path):
        if runtime.provider == "codex":
            return "Codex ChatGPT OAuth is not configured."
        return f"{runtime.provider} API key is not configured."
    return None


def describe_provider_runtime(
    provider: str,
    *,
    api_keys: dict[str, str],
    offline_mode: bool,
    default_model: str | None = None,
    codex_home_path: str | None = None,
) -> ProviderDiagnostics:
    runtime = build_runtime(provider)
    provider_credentials_present = _has_native_credentials(
        provider,
        api_keys,
        codex_home_path=codex_home_path,
    )
    request = RunRequest(
        run_id="diagnostics",
        query="diagnostics",
        query_type="free",
        mode="detailed",
        provider=provider,
        model=default_model or "",
        api_keys=api_keys,
        offline_mode=offline_mode,
        codex_home_path=codex_home_path,
    )
    fallback_reason = provider_fallback_reason(runtime, request)
    if provider == "codex":
        active_execution_path = "codex_unavailable" if fallback_reason else "codex_sdk"
    else:
        active_execution_path = "deterministic_fallback" if fallback_reason else "native_sdk"
    return ProviderDiagnostics(
        provider=provider,
        runtime_name=runtime.runtime_name,
        runtime_engine=runtime.runtime_engine,
        default_model=default_model,
        sdk_available=runtime.sdk_available,
        offline_mode=offline_mode,
        provider_credentials_present=provider_credentials_present,
        search_credentials_present=_search_credentials_present(api_keys),
        active_execution_path=active_execution_path,
        fallback_reason=fallback_reason,
    )


def _python_executable() -> str:
    preferred = REPO_ROOT / ".venv" / "bin" / "python"
    if preferred.exists():
        return str(preferred)
    return str(Path(sys.executable).resolve())


def _mcp_stdio_command(server_name: str) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return (
            str(Path(sys.executable).resolve()),
            ["--mdr-mcp-server", server_name, "--transport", "stdio"],
        )
    return (
        _python_executable(),
        ["-m", "medical_deep_research.mcp.servers", server_name, "--transport", "stdio"],
    )


def _build_mcp_server_env(request: RunRequest) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{pythonpath}" if pythonpath else str(SRC_ROOT)
    env.update(_search_api_env(request.api_keys))
    env["MDR_OFFLINE_MODE"] = "1" if request.offline_mode else "0"
    return env


def _openai_mcp_stdio_params(server_name: str, request: RunRequest) -> dict[str, object]:
    command, args = _mcp_stdio_command(server_name)
    return {
        "command": command,
        "args": args,
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
            "The app will run this in phases. Follow the current phase prompt exactly.",
            f"When asked to search, call `aggregate_search` with query_type=`{request.query_type}`, provider=`{request.provider}`, max_results_per_source=25, min_unique_studies=24, max_search_rounds=3, and offline_mode={offline}.",
            "The search tool reports focused/broadened search rounds and only broadens after sparse retrieval.",
            "When asked to synthesize, call `verify_results` and `synthesize_report`, then write the final markdown report yourself from the structured synthesis packet.",
            "The final report must follow the report-format instructions from `synthesize_report`; do not output the deterministic template, runtime metadata bullets, or a database hit table.",
            f"The requested report language is: {request.language}.",
            "Return only valid JSON matching the structured schema. Do not wrap the JSON in markdown fences or prose.",
        ]
    )


def _native_search_rank_prompt(request: RunRequest) -> str:
    return "\n".join(
        [
            "Phase 1: search and rank only.",
            "Call `aggregate_search` for the research query.",
            "Then call `rank_results` with the aggregated `studies`; use context `clinical` when the plan domain is clinical, otherwise `general`.",
            "Do not call `verify_results` or `synthesize_report` in this phase.",
            "Return JSON only: {\"status\":\"ranked\"}.",
            "",
            _native_user_prompt(request),
        ]
    )


def _native_synthesis_prompt(
    request: RunRequest,
    *,
    aggregate_payload: dict[str, Any],
    ranked_payload: dict[str, Any],
    fulltext_payload: dict[str, Any] | None,
) -> str:
    compact_aggregate = {
        "results": aggregate_payload.get("results"),
        "counts": aggregate_payload.get("counts"),
        "errors": aggregate_payload.get("errors"),
        "iterations": aggregate_payload.get("iterations"),
    }
    return "\n".join(
        [
            "Phase 2: verify, synthesize, and write the final report.",
            "Call `verify_results` with `studies_json` set to the ranked studies JSON below.",
            "Then call `synthesize_report` with these exact arguments:",
            "- query, query_type, provider from the request",
            "- search_results_json set to the aggregate `results` JSON below",
            "- ranked_studies_json set to the ranked `studies` JSON below",
            "- verification_json set to the `summary` returned by `verify_results`",
            "- fulltext_json set to the full-text JSON below",
            "After `synthesize_report` returns, write the final markdown report yourself using its structured evidence data, full-text excerpts, and instructions.",
            "The final report must start with a level-1 markdown title and use numbered sections exactly: "
            "## 1. Executive Summary, ## 2. Background, ## 3. Methods, ## 4. Results/Findings, "
            "## 5. Discussion, ## 6. Conclusions, ## 7. References.",
            "Do not include runtime metadata bullets, provider/tool status, raw database hit tables, or the phrase 'Study screening and GRADE certainty appraisal were not performed by this report renderer.'",
            "Return JSON only: {\"final_report\":\"...markdown report...\"}.",
            "",
            _native_user_prompt(request),
            "",
            "Aggregate payload JSON:",
            json.dumps(compact_aggregate, ensure_ascii=False),
            "",
            "Ranked payload JSON:",
            json.dumps({"studies": ranked_payload.get("studies")}, ensure_ascii=False),
            "",
            "Full-text payload JSON:",
            json.dumps(fulltext_payload or {}, ensure_ascii=False),
        ]
    )


def _native_user_prompt(request: RunRequest) -> str:
    return "\n".join(
        [
            f"Research query: {request.query}",
            f"Query type: {request.query_type}",
            f"Provider: {request.provider}",
            f"Preferred model: {request.model}",
            f"Report language: {request.language}",
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


def _strict_json_schema_for_model(output_model: type[BaseModel]) -> dict[str, Any]:
    schema = output_model.model_json_schema()

    def is_map_schema(node: Any) -> bool:
        return (
            isinstance(node, dict)
            and node.get("type") == "object"
            and "additionalProperties" in node
            and not isinstance(node.get("properties"), dict)
        )

    def tighten(node: Any) -> Any:
        if isinstance(node, list):
            for item in node:
                tighten(item)
            return node
        if not isinstance(node, dict):
            return node

        node.pop("default", None)

        properties = node.get("properties")
        if isinstance(properties, dict):
            for key, value in list(properties.items()):
                if is_map_schema(value):
                    properties.pop(key)
                else:
                    tighten(value)
            for key, value in list(node.items()):
                if key != "properties":
                    tighten(value)
            node["required"] = list(properties)
            node["additionalProperties"] = False
        elif node.get("type") == "object":
            for value in list(node.values()):
                tighten(value)
            node["additionalProperties"] = False
        else:
            for value in list(node.values()):
                tighten(value)
        return node

    return tighten(schema)


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
            "provider_credentials_present": _has_native_credentials(
                self.provider,
                request.api_keys,
                codex_home_path=request.codex_home_path,
            ),
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
            EventType.ARTIFACT_CREATED,
            "planning",
            "Saved literature source catalog",
            artifact_type=ArtifactType.SOURCE_CATALOG,
            artifact_name="Literature Source Catalog",
            artifact_json={
                "sources": [
                    entry.model_dump()
                    for entry in source_catalog(
                        request.api_keys,
                        offline_mode=request.offline_mode,
                    )
                ]
            },
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
        prisma = build_prisma_summary(
            provider_results,
            ranked,
            final_synthesis_limit=MAX_REPORT_STUDIES,
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "ranking",
            "Saved PRISMA flow summary",
            artifact_type=ArtifactType.PRISMA_FLOW,
            artifact_name="PRISMA Flow Summary",
            artifact_json=prisma.model_dump(),
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
        audit = build_audit_report(
            final_report,
            provider_results,
            ranked,
            verification,
            final_synthesis_limit=MAX_REPORT_STUDIES,
        )
        yield _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "verifying",
            "Saved deterministic audit report",
            artifact_type=ArtifactType.AUDIT_REPORT,
            artifact_name="Audit Report",
            artifact_json=audit.model_dump(),
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
                    "provider_credentials_present": _has_native_credentials(
                        self.provider,
                        request.api_keys,
                        codex_home_path=request.codex_home_path,
                    ),
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
                "or when no High/Moderate-certainty evidence exists for the core outcome (target RCTs or systematic reviews).",
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
                "provider_credentials_present": _has_native_credentials(
                    self.provider,
                    request.api_keys,
                    codex_home_path=request.codex_home_path,
                ),
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
            "provider_credentials_present": _has_native_credentials(
                runtime.provider,
                request.api_keys,
                codex_home_path=request.codex_home_path,
            ),
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
    if request.provider == "codex":
        return report, []
    if request.provider != "local" and not _has_native_credentials(
        request.provider,
        request.api_keys,
        codex_home_path=request.codex_home_path,
    ):
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


def _fulltext_excerpts_from_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    fulltext = payload.get("fulltext")
    if isinstance(fulltext, dict):
        excerpts = fulltext.get("excerpts")
        if isinstance(excerpts, list):
            return [item for item in excerpts if isinstance(item, dict)]
    parsed_fulltext = payload.get("parsed_fulltext")
    if isinstance(parsed_fulltext, list):
        return [item for item in parsed_fulltext if isinstance(item, dict)]
    return []


def _fulltext_assessed_count(*payloads: Any) -> int:
    for payload in payloads:
        excerpts = _fulltext_excerpts_from_payload(payload)
        if excerpts:
            return len(excerpts)
        if not isinstance(payload, dict):
            continue
        for key in ("parsed_fulltext", "available", "available_ranks"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        parsed_count = payload.get("fulltext_parsed_count")
        if isinstance(parsed_count, int):
            return parsed_count
    return 0


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
        "provider_credentials_present": _has_native_credentials(
            runtime.provider,
            request.api_keys,
            codex_home_path=request.codex_home_path,
        ),
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

    synthesis_payload = bridge._intermediate.get("synthesize_report")
    fetch_payload = bridge._intermediate.get("fetch_fulltext")
    fulltext_excerpts = _fulltext_excerpts_from_payload(synthesis_payload)
    fulltext_count = _fulltext_assessed_count(synthesis_payload, fetch_payload)
    verification = bridge.verification or empty_verification_summary("Verification was not run.")
    prisma = build_prisma_summary(
        bridge.search_results,
        bridge.ranked_studies,
        screening=bridge.screening,
        full_text_assessed=fulltext_count,
        final_synthesis_limit=MAX_REPORT_STUDIES,
    )
    audit = build_audit_report(
        final_report,
        bridge.search_results,
        bridge.ranked_studies,
        verification,
        screening=bridge.screening,
        appraisal=bridge.appraisal,
        fulltext_excerpts=fulltext_excerpts,
        final_synthesis_limit=MAX_REPORT_STUDIES,
    )

    return [
        _ev(
            bridge.progress,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved literature source catalog",
            artifact_type=ArtifactType.SOURCE_CATALOG,
            artifact_name="Literature Source Catalog",
            artifact_json={
                "sources": [
                    entry.model_dump()
                    for entry in source_catalog(
                        request.api_keys,
                        offline_mode=request.offline_mode,
                    )
                ]
            },
        ),
        _ev(
            bridge.progress,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved PRISMA flow summary",
            artifact_type=ArtifactType.PRISMA_FLOW,
            artifact_name="PRISMA Flow Summary",
            artifact_json=prisma.model_dump(),
        ),
        _ev(
            bridge.progress,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved deterministic audit report",
            artifact_type=ArtifactType.AUDIT_REPORT,
            artifact_name="Audit Report",
            artifact_json=audit.model_dump(),
        ),
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
# OpenAI Codex SDK — ChatGPT OAuth-backed runtime
# ---------------------------------------------------------------------------

def _codex_home_for_request(request: RunRequest) -> Path:
    home = Path(request.codex_home_path) if request.codex_home_path else Path(os.getenv("CODEX_HOME") or Path.home() / ".codex")
    home = home.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home


def _codex_mcp_server_config(server_name: str, request: RunRequest, *, enabled_tools: list[str]) -> dict[str, Any]:
    command, args = _mcp_stdio_command(server_name)
    return {
        "command": command,
        "args": args,
        "env": _build_mcp_server_env(request),
        "cwd": str(REPO_ROOT),
        "startup_timeout_sec": OPENAI_MCP_TIMEOUT_SECONDS,
        "tool_timeout_sec": 180.0,
        "required": True,
        "enabled_tools": enabled_tools,
    }


def _codex_thread_config(request: RunRequest) -> dict[str, Any]:
    reasoning_effort = os.getenv("MDR_CODEX_REASONING_EFFORT", "high").strip().lower() or "high"
    return {
        "model_reasoning_effort": reasoning_effort,
        "mcp_servers.medical_literature": _codex_mcp_server_config(
            "literature",
            request,
            enabled_tools=["aggregate_search"],
        ),
        "mcp_servers.medical_evidence": _codex_mcp_server_config(
            "evidence",
            request,
            enabled_tools=["rank_results", "verify_results", "synthesize_report"],
        ),
    }


def _codex_local_thread_config(_request: RunRequest) -> dict[str, Any]:
    reasoning_effort = os.getenv("MDR_CODEX_REASONING_EFFORT", "high").strip().lower() or "high"
    return {"model_reasoning_effort": reasoning_effort}


def _codex_usage_payload(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return {"token_usage": usage.model_dump(mode="json")}
    return {"token_usage": str(usage)}


def _codex_tool_phase(tool_name: str) -> str:
    return {
        "aggregate_search": "searching",
        "rank_results": "ranking",
        "verify_results": "verifying",
        "synthesize_report": "synthesizing",
    }.get(tool_name, "searching")


def _codex_display_tool(server: str | None, tool_name: str) -> str:
    server_label = (server or "").removeprefix("medical_")
    return f"{server_label}.{tool_name}" if server_label else tool_name


def _codex_item_root(item: Any) -> Any:
    return getattr(item, "root", item)


def _codex_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _codex_tool_result_payload(tool_item: Any) -> Any:
    result = getattr(tool_item, "result", None)
    if result is None:
        return None
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    text = _codex_content_text(getattr(result, "content", None))
    if not text:
        return None
    try:
        return json.loads(text)
    except JSONDecodeError:
        return text


def _codex_tool_status_failed(status: str | None) -> bool:
    lowered = str(status or "").lower()
    return "fail" in lowered or "error" in lowered


def _codex_tool_error_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("error", "message", "detail", "reason"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        content = _codex_content_text(payload.get("content"))
        if content:
            return content
        try:
            return json.dumps(payload, ensure_ascii=False)
        except TypeError:
            return str(payload)
    if payload is None:
        return ""
    return str(payload)


def _codex_tool_result_summary(tool_name: str, payload: Any) -> str | None:
    if tool_name == "aggregate_search" and isinstance(payload, dict):
        studies = payload.get("studies")
        counts = payload.get("counts")
        study_count = len(studies) if isinstance(studies, list) else None
        if isinstance(counts, dict):
            source_count = sum(1 for value in counts.values() if isinstance(value, int) and value > 0)
            total = study_count if study_count is not None else sum(
                value for value in counts.values() if isinstance(value, int)
            )
            return f"{total} studies from {source_count} sources"
        if study_count is not None:
            return f"{study_count} studies"
    if tool_name == "rank_results" and isinstance(payload, dict):
        studies = payload.get("studies")
        if isinstance(studies, list):
            return f"{len(studies)} ranked studies"
    if tool_name == "verify_results" and isinstance(payload, dict):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            total = summary.get("total_considered")
            verified = summary.get("verified_pmids")
            missing = summary.get("missing_pmids")
            return f"{verified} verified PMIDs, {missing} missing PMIDs across {total} studies"
    if tool_name == "synthesize_report":
        report_text = _codex_report_text_from_payload(payload)
        if report_text:
            return f"{len(report_text)} report characters"
        if isinstance(payload, dict):
            studies = payload.get("studies")
            total = payload.get("total_ranked")
            if isinstance(total, int):
                return f"synthesis packet for {total} ranked studies"
            if isinstance(studies, list):
                return f"synthesis packet for {len(studies)} studies"
        return "synthesis packet returned"
    return None


def _codex_report_text_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("result", "final_report", "report", "markdown", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        content = payload.get("content")
        text = _codex_content_text(content)
        if text:
            return text
    return ""


def _codex_completion_report_text(final_response: Any) -> str:
    if final_response is None:
        return ""
    try:
        completion = _coerce_model_output(final_response, CodexCompletionOutput)
    except Exception:
        try:
            output = _coerce_native_output(final_response)
        except Exception:
            return ""
        return output.final_report.strip()
    return completion.final_report.strip()


def _codex_tool_payload_dict(payloads: dict[str, Any], tool_name: str) -> dict[str, Any]:
    payload = payloads.get(tool_name)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Codex MCP tool `{tool_name}` returned no structured payload.")
    return payload


def _codex_output_from_mcp_payloads(
    request: RunRequest,
    runtime_name: str,
    payloads: dict[str, Any],
    *,
    final_response: Any = None,
) -> AgentResearchOutput:
    aggregate = _codex_tool_payload_dict(payloads, "aggregate_search")
    ranked = _codex_tool_payload_dict(payloads, "rank_results")
    verified = _codex_tool_payload_dict(payloads, "verify_results")

    plan_payload = aggregate.get("plan")
    plan = (
        QueryPlan.model_validate(plan_payload)
        if isinstance(plan_payload, dict)
        else build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
    )

    raw_results = aggregate.get("results")
    search_results = [
        SearchProviderResult.model_validate(result)
        for result in raw_results
        if isinstance(result, dict)
    ] if isinstance(raw_results, list) else []

    raw_ranked = ranked.get("studies")
    ranked_studies = [
        ScoredStudy.model_validate(study)
        for study in raw_ranked
        if isinstance(study, dict)
    ] if isinstance(raw_ranked, list) else []

    verification_payload = verified.get("summary")
    if not isinstance(verification_payload, dict):
        raise RuntimeError("Codex MCP tool `verify_results` returned no verification summary.")
    verification = VerificationSummary.model_validate(verification_payload)

    final_report = _codex_completion_report_text(final_response)
    if not final_report:
        final_report = _codex_report_text_from_payload(payloads.get("synthesize_report"))
    if not final_report:
        raise RuntimeError("Codex final response returned no report text.")

    return AgentResearchOutput(
        plan=plan,
        search_results=search_results,
        ranked_studies=ranked_studies,
        verification=verification,
        final_report=final_report,
    )


def _codex_mcp_completion_extra(
    output: AgentResearchOutput,
    completed_tool_calls: list[str],
    aggregate_payload: dict[str, Any] | None = None,
    fulltext_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = {
        "tool_calls": len(completed_tool_calls),
        "mcp_tools_completed": completed_tool_calls,
        "source_execution_mode": "codex_sdk_mcp",
        "report_source": "codex.final_report",
        "search_sources_executed": [result.source for result in output.search_results],
        "source_counts": {result.source: len(result.studies) for result in output.search_results},
        "source_errors": {
            result.source: result.error
            for result in output.search_results
            if result.error
        },
    }
    if aggregate_payload:
        extra.update(
            {
                "search_iterations": aggregate_payload.get("iterations"),
                "search_credentials_present": aggregate_payload.get("credentials_present"),
                "search_min_unique_studies": aggregate_payload.get("min_unique_studies"),
                "search_max_results_per_source": aggregate_payload.get("max_results_per_source"),
                "search_unique_studies": len(aggregate_payload.get("studies") or []),
            }
        )
    if fulltext_payload:
        extra.update(
            {
                "fulltext_attempted": True,
                "fulltext_pdfs_found": fulltext_payload.get("pdfs_found"),
                "fulltext_parsed_count": len(fulltext_payload.get("parsed_fulltext") or []),
                "fulltext_requested_upload_ranks": fulltext_payload.get("requested_upload_ranks"),
                "fulltext_unavailable_pdf_ranks": fulltext_payload.get("unavailable_pdf_ranks"),
                "fulltext_error": fulltext_payload.get("error"),
            }
        )
    return extra


def _codex_progress_update_from_item(item: Any, *, completed: bool) -> dict[str, Any] | None:
    root = _codex_item_root(item)
    item_type = getattr(root, "type", None)
    if item_type == "mcpToolCall":
        tool_name = str(getattr(root, "tool", "") or "tool")
        server = getattr(root, "server", None)
        display_tool = _codex_display_tool(str(server) if server else None, tool_name)
        phase = _codex_tool_phase(tool_name)
        status = str(getattr(root, "status", "") or "")
        extra: dict[str, Any] = {
            "codex_tool": tool_name,
            "codex_server": server,
            "codex_tool_status": status,
        }
        duration_ms = getattr(root, "duration_ms", None)
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        if completed:
            payload = _codex_tool_result_payload(root)
            if _codex_tool_status_failed(status):
                error_text = _trim_diagnostic_text(_codex_tool_error_text(payload), max_chars=1200)
                if error_text:
                    extra["error"] = error_text
                message = f"Codex failed {display_tool}"
                if error_text:
                    message = f"{message}: {error_text[:240]}"
                return {
                    "event_type": EventType.TOOL_RESULT,
                    "phase": phase,
                    "message": message,
                    "tool_name": display_tool,
                    "extra": extra,
                }
            summary = _codex_tool_result_summary(tool_name, payload)
            if summary:
                extra["summary"] = summary
            message = f"Codex completed {display_tool}"
            if summary:
                message = f"{message}: {summary}"
            return {
                "event_type": EventType.TOOL_RESULT,
                "phase": phase,
                "message": message,
                "tool_name": display_tool,
                "extra": extra,
            }
        return {
            "event_type": EventType.TOOL_CALLED,
            "phase": phase,
            "message": f"Codex called {display_tool}",
            "tool_name": display_tool,
            "extra": extra,
        }
    if item_type == "agentMessage":
        text = getattr(root, "text", "") or ""
        return {
            "event_type": EventType.TOOL_RESULT,
            "phase": "synthesizing",
            "message": f"Codex completed final structured output ({len(text)} characters)",
            "tool_name": "codex.thread_run",
            "extra": {"output_characters": len(text)},
        }
    return None


def _codex_progress_event(
    tracker: ProgressTracker,
    update: dict[str, Any],
    *,
    elapsed_seconds: float | None = None,
) -> RuntimeEventPayload:
    extra = dict(update.get("extra") or {})
    if elapsed_seconds is not None:
        extra["elapsed_seconds"] = round(elapsed_seconds, 1)
    return _ev(
        tracker,
        update.get("event_type", EventType.TOOL_RESULT),
        str(update.get("phase") or "searching"),
        str(update.get("message") or "Codex native MCP workflow is still running"),
        tool_name=update.get("tool_name") or "codex.thread_run",
        extra=extra,
    )


async def _forward_bridge_events_until(
    bridge: AgenticEventBridge,
    task: asyncio.Task[Any],
    progress_queue: asyncio.Queue[Any] | None,
) -> Any:
    get_task: asyncio.Task[RuntimeEventPayload | None] | None = asyncio.create_task(bridge.queue.get())
    try:
        while True:
            wait_set: set[asyncio.Task[Any]] = {task}
            if get_task is not None:
                wait_set.add(get_task)
            done, _pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
            if get_task is not None and get_task in done:
                event = get_task.result()
                if event is not None and progress_queue is not None:
                    await progress_queue.put(event)
                get_task = asyncio.create_task(bridge.queue.get())
                continue
            if task in done:
                if get_task is not None and not get_task.done():
                    get_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await get_task
                return task.result()
    finally:
        if get_task is not None and not get_task.done():
            get_task.cancel()
            with suppress(asyncio.CancelledError):
                await get_task


async def _drain_bridge_events(
    bridge: AgenticEventBridge,
    progress_queue: asyncio.Queue[Any] | None,
) -> None:
    if progress_queue is None:
        return
    while True:
        try:
            event = bridge.queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        if event is not None:
            await progress_queue.put(event)


async def _codex_fetch_fulltext_for_ranked_studies(
    request: RunRequest,
    *,
    plan: QueryPlan,
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    progress_queue: asyncio.Queue[Any] | None,
) -> dict[str, Any]:
    bridge = AgenticEventBridge()
    bridge.plan = plan
    bridge.search_results = search_results
    bridge.ranked_studies = ranked_studies
    await bridge.on_tool_start("fetch_fulltext", {})
    fetch_task = asyncio.create_task(tool_fetch_fulltext(request, bridge, allow_user_checkpoint=True))
    try:
        result = await _forward_bridge_events_until(bridge, fetch_task, progress_queue)
    except Exception as exc:
        result = {"error": _format_exception(exc) or str(exc)}
    await bridge.on_tool_end("fetch_fulltext", result)
    await _drain_bridge_events(bridge, progress_queue)
    if not isinstance(result, dict):
        return {"result": result}

    available = result.get("available")
    parse_ranks = [
        int(item["rank"])
        for item in available
        if isinstance(item, dict) and str(item.get("rank") or "").isdigit()
    ] if isinstance(available, list) else []
    parsed_fulltext: list[dict[str, Any]] = []
    for rank in parse_ranks[:CODEX_FULLTEXT_PARSE_LIMIT]:
        await bridge.on_tool_start("parse_pdf", {"rank": rank})
        parse_result = await tool_parse_pdf(request, bridge, rank, allow_user_checkpoint=False)
        await bridge.on_tool_end("parse_pdf", parse_result)
        await _drain_bridge_events(bridge, progress_queue)
        if isinstance(parse_result, dict) and isinstance(parse_result.get("fulltext"), str):
            fulltext = parse_result["fulltext"]
            parsed_fulltext.append(
                {
                    "rank": rank,
                    "source": parse_result.get("source"),
                    "text_length": parse_result.get("text_length"),
                    "excerpt": fulltext[:2500],
                }
            )
    if parsed_fulltext:
        result["parsed_fulltext"] = parsed_fulltext
    return result


def _codex_local_tool_catalog() -> str:
    rows = [
        "plan_search {\"query\": string, \"query_type\": string}",
        "suggest_databases {\"query\": string}",
        "write_todos {\"items\": string[]}",
        "update_progress {\"phase\": string, \"message\": string}",
        "search_pubmed/search_pmc/search_europe_pmc/search_openalex/search_crossref/"
        "search_cochrane/search_semantic_scholar/search_scopus/search_preprints "
        "{\"query\": string, \"max_results\": integer}",
        "get_studies {\"context\": string}",
        "browse_studies {\"page\": integer, \"evidence_level\": string|null, \"source\": string|null, "
        "\"page_size\": integer|null}",
        "screen_studies {\"included_indices\": integer[], \"excluded_indices\": integer[], "
        "\"exclusion_reasons\": string[]}",
        "finalize_ranking {\"ranked_indices\": integer[], \"rationale\": string}",
        "get_references/get_citations {\"reference_number\": integer}",
        "fetch_fulltext {}",
        "await_user_pdfs {\"ranks\": integer[]}",
        "parse_pdf {\"rank\": integer}",
        "appraise_evidence {\"findings\": string[], \"certainties\": string[], \"rationales\": string[], "
        "\"reference_numbers_csv\": string[]}",
        "verify_studies {}",
        "synthesize_report {}",
        "submit_report {\"report_markdown\": string}",
    ]
    return "\n".join(f"- {row}" for row in rows)


def _codex_agentic_instructions(request: RunRequest, runtime_name: str) -> str:
    return (
        agentic_system_prompt(request, runtime_name)
        + "\n\n## Codex SDK Adapter\n"
        "You are running inside the Codex SDK, but the application executes tools locally. "
        "For every turn, return exactly one JSON object with two fields: "
        "`tool_name` and `arguments_json`. `arguments_json` must be a JSON string containing "
        "the arguments for that one tool. Do not answer with prose and do not invent tool outputs.\n"
        "Completion requires the app to accept `submit_report`; stopping without accepted "
        "`submit_report` is a runtime failure.\n"
        "Use the app's existing workflow and shared state. Search broadly first. If the first "
        "search pool is sparse or off-topic, widen incrementally by adding a focused synonym, "
        "adjacent database, or snowball step based on the returned results, then call "
        "`get_studies` again. Do not merely loosen screening criteria to inflate counts.\n"
        f"You have at most {CODEX_AGENTIC_MAX_TOOL_TURNS} local tool-decision turns. "
        "Do not spend extra turns on optional browsing once the evidence base is sufficient; "
        "move to ranking, appraisal, synthesis, and submit_report.\n"
        f"`submit_report.report_markdown` must be written in {request.language}. "
        "When writing non-English prose, preserve citation numbers, PMID/DOI values, "
        "journal names, and reference formatting.\n"
        "After `fetch_fulltext`, if the result asks for user PDFs, wait for that tool to return; "
        "then parse the uploaded/available full texts before appraisal when possible.\n\n"
        "Available local tools and argument JSON shapes:\n"
        f"{_codex_local_tool_catalog()}"
    )


def _codex_state_summary(bridge: AgenticEventBridge) -> dict[str, Any]:
    source_counts = {result.source: len(result.studies) for result in bridge.search_results}
    return {
        "planned": bridge.plan is not None,
        "search_batches": len(bridge.search_results),
        "source_counts": source_counts,
        "pre_scored_studies": len(bridge._pre_scored),
        "ranked_studies": len(bridge.ranked_studies),
        "screening_done": bridge.screening is not None,
        "appraisal_done": bridge.appraisal is not None,
        "verification_done": bridge.verification is not None,
        "submitted_report": bool(bridge._intermediate.get("submitted_report")),
        "tool_calls": bridge._tool_call_count,
    }


def _codex_decision_prompt(request: RunRequest, bridge: AgenticEventBridge, observations: list[str], turn_index: int) -> str:
    recent_observations = "\n\n".join(observations[-8:]) if observations else "No tool observations yet."
    remaining_turns = max(CODEX_AGENTIC_MAX_TOOL_TURNS - turn_index + 1, 0)
    urgency = (
        "You are near the tool-turn limit: stop optional exploration and call synthesize_report or submit_report next."
        if remaining_turns <= 5
        else "Continue the workflow without repeating completed steps."
    )
    return (
        f"Research question:\n{request.query}\n\n"
        f"Query type: {request.query_type}\n"
        f"Target language: {request.language}\n\n"
        f"Current app state:\n{json.dumps(_codex_state_summary(bridge), ensure_ascii=False, default=str)}\n\n"
        f"Recent tool observations:\n{recent_observations}\n\n"
        f"Turn {turn_index} of {CODEX_AGENTIC_MAX_TOOL_TURNS} "
        f"({remaining_turns} remaining): choose the next single local app tool to call. {urgency} "
        "Return only the structured JSON object. Use an empty JSON object string \"{}\" for no-argument tools."
    )


def _codex_parse_arguments_json(arguments_json: str) -> dict[str, Any]:
    text = (arguments_json or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except JSONDecodeError as exc:
        raise RuntimeError(f"Codex returned invalid tool arguments_json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Codex tool arguments_json must decode to a JSON object.")
    return parsed


def _codex_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _codex_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _codex_bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _build_codex_local_tool_executors(request: RunRequest, bridge: AgenticEventBridge) -> dict[str, Any]:
    executors: dict[str, Any] = {}

    executors["plan_search"] = lambda a: tool_plan_search(
        request,
        bridge,
        str(a.get("query") or request.query),
        str(a.get("query_type") or request.query_type),
    )
    executors["suggest_databases"] = lambda a: tool_suggest_databases(
        request,
        bridge,
        str(a.get("query") or request.query),
    )
    executors["write_todos"] = lambda a: tool_write_todos(request, bridge, _codex_str_list(a.get("items")))
    executors["update_progress"] = lambda a: tool_update_progress(
        request,
        bridge,
        str(a.get("phase") or bridge.progress.current_phase or "planning"),
        str(a.get("message") or "Codex research workflow update"),
    )

    for tool_name, source in _SEARCH_SOURCES.items():
        _source = source
        executors[tool_name] = lambda a, src=_source: tool_search(
            request,
            bridge,
            src,
            str(a.get("query") or request.query),
            _codex_bounded_int(
                a.get("max_results"),
                DEFAULT_SEARCH_RESULTS_PER_SOURCE,
                minimum=1,
                maximum=MAX_AGENT_SEARCH_RESULTS_PER_SOURCE,
            ),
        )

    executors["get_references"] = lambda a: tool_snowball(
        request,
        bridge,
        _codex_bounded_int(a.get("reference_number"), 1, minimum=1, maximum=9999),
        "references",
    )
    executors["get_citations"] = lambda a: tool_snowball(
        request,
        bridge,
        _codex_bounded_int(a.get("reference_number"), 1, minimum=1, maximum=9999),
        "citations",
    )
    executors["get_studies"] = lambda a: tool_get_studies(
        request,
        bridge,
        str(a.get("context") or "general"),
    )
    executors["browse_studies"] = lambda a: tool_browse_studies(
        request,
        bridge,
        _codex_bounded_int(a.get("page"), 1, minimum=1, maximum=999),
        str(a["evidence_level"]) if a.get("evidence_level") is not None else None,
        str(a["source"]) if a.get("source") is not None else None,
        _codex_bounded_int(a.get("page_size"), STUDY_PAGE_SIZE, minimum=1, maximum=50)
        if a.get("page_size") is not None
        else None,
    )
    executors["screen_studies"] = lambda a: tool_screen_studies(
        request,
        bridge,
        _codex_int_list(a.get("included_indices")),
        _codex_int_list(a.get("excluded_indices")),
        _codex_str_list(a.get("exclusion_reasons")),
    )
    executors["finalize_ranking"] = lambda a: tool_finalize_ranking(
        request,
        bridge,
        _codex_int_list(a.get("ranked_indices")),
        str(a.get("rationale") or ""),
    )
    executors["appraise_evidence"] = lambda a: tool_appraise_evidence(
        request,
        bridge,
        _codex_str_list(a.get("findings")),
        _codex_str_list(a.get("certainties")),
        _codex_str_list(a.get("rationales")),
        _codex_str_list(a.get("reference_numbers_csv")),
    )
    executors["verify_studies"] = lambda _a: tool_verify_studies(request, bridge)
    executors["synthesize_report"] = lambda _a: tool_synthesize_report(request, bridge)
    executors["submit_report"] = lambda a: tool_submit_report(
        request,
        bridge,
        str(a.get("report_markdown") or ""),
    )
    executors["fetch_fulltext"] = lambda _a: tool_fetch_fulltext(request, bridge, allow_user_checkpoint=True)
    executors["await_user_pdfs"] = lambda a: tool_await_user_pdfs(
        request,
        bridge,
        _codex_int_list(a.get("ranks")),
    )
    executors["parse_pdf"] = lambda a: tool_parse_pdf(
        request,
        bridge,
        _codex_bounded_int(a.get("rank"), 1, minimum=1, maximum=9999),
    )
    return executors


async def _invoke_codex_local_tool(
    request: RunRequest,
    bridge: AgenticEventBridge,
    executors: dict[str, Any],
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    del request
    if tool_name not in executors:
        raise RuntimeError(f"Codex requested unknown local tool `{tool_name}`.")
    tool_input = args
    if tool_name == "submit_report":
        report = str(args.get("report_markdown") or "")
        tool_input = {"length": len(report)}
        if bridge.full_trace_enabled:
            tool_input["report_markdown"] = report
    await bridge.on_tool_start(tool_name, tool_input)
    try:
        result = await executors[tool_name](args)
    except Exception as exc:
        await bridge.on_tool_end(tool_name, {"error": _format_exception(exc) or str(exc)})
        raise
    await bridge.on_tool_end(tool_name, result)
    if tool_name == "submit_report":
        if isinstance(result, dict) and result.get("fatal"):
            raise _ReportRejected(str(result.get("fallback_reason") or result.get("error")))
        if isinstance(result, dict) and result.get("status") == "ok":
            raise _ReportSubmitted()
    if isinstance(result, dict):
        return result
    return {"result": result}


def _codex_tool_observation(tool_name: str, result: dict[str, Any]) -> str:
    text = _langchain_tool_json(tool_name, result)
    if len(text) > 7000:
        text = text[:7000] + "\n...[truncated]"
    return f"{tool_name} -> {text}"


def _native_output_artifact_events(
    runtime: ResearchRuntime,
    request: RunRequest,
    output: AgentResearchOutput,
    tracker: ProgressTracker,
    *,
    completion_extra: dict[str, Any] | None = None,
) -> list[RuntimeEventPayload]:
    events: list[RuntimeEventPayload] = []
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Saved provider search plan artifact",
            artifact_type=ArtifactType.SEARCH_PLAN,
            artifact_name="Search Plan",
            artifact_json=output.plan.model_dump(),
        )
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "planning",
            "Saved literature source catalog",
            artifact_type=ArtifactType.SOURCE_CATALOG,
            artifact_name="Literature Source Catalog",
            artifact_json={
                "sources": [
                    entry.model_dump()
                    for entry in source_catalog(
                        request.api_keys,
                        offline_mode=request.offline_mode,
                    )
                ]
            },
        )
    )
    if output.plan.todos:
        events.append(
            _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "planning",
                "Created provider todo list",
                artifact_type=ArtifactType.TODO_LIST,
                artifact_name="Research TODOs",
                artifact_text="\n".join(f"- {todo}" for todo in output.plan.todos),
            )
        )
    for result in output.search_results:
        events.append(
            _ev(
                tracker,
                EventType.ARTIFACT_CREATED,
                "searching",
                f"Captured {result.source} search results",
                artifact_type=ArtifactType.SEARCH_RESULTS,
                artifact_name=f"{result.source} Results",
                artifact_json=result.model_dump(),
            )
        )
    source_summary = {
        "sources": [result.source for result in output.search_results],
        "counts": {result.source: len(result.studies) for result in output.search_results},
        "errors": {result.source: result.error for result in output.search_results if result.error},
    }
    if completion_extra:
        for key in (
            "search_iterations",
            "search_credentials_present",
            "search_min_unique_studies",
            "search_max_results_per_source",
            "search_unique_studies",
            "fulltext_attempted",
            "fulltext_pdfs_found",
            "fulltext_parsed_count",
            "fulltext_requested_upload_ranks",
            "fulltext_unavailable_pdf_ranks",
            "fulltext_error",
        ):
            if key in completion_extra:
                source_summary[key] = completion_extra[key]
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "searching",
            "Captured source execution summary",
            artifact_type=ArtifactType.SOURCE_PLAN,
            artifact_name="Source Execution Summary",
            artifact_json=source_summary,
        )
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "ranking",
            "Saved ranked evidence artifact",
            artifact_type=ArtifactType.RANKED_RESULTS,
            artifact_name="Ranked Results",
            artifact_json={"studies": [study.model_dump() for study in output.ranked_studies[:MAX_REPORT_STUDIES]]},
        )
    )
    fulltext_count = 0
    if completion_extra:
        try:
            fulltext_count = int(completion_extra.get("fulltext_parsed_count") or 0)
        except (TypeError, ValueError):
            fulltext_count = 0
    prisma = build_prisma_summary(
        output.search_results,
        output.ranked_studies,
        full_text_assessed=fulltext_count,
        final_synthesis_limit=MAX_REPORT_STUDIES,
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "ranking",
            "Saved PRISMA flow summary",
            artifact_type=ArtifactType.PRISMA_FLOW,
            artifact_name="PRISMA Flow Summary",
            artifact_json=prisma.model_dump(),
        )
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "verifying",
            "Saved verification artifact",
            artifact_type=ArtifactType.VERIFICATION_REPORT,
            artifact_name="Verification Report",
            artifact_text=render_verification_report(output.verification),
        )
    )
    audit = build_audit_report(
        output.final_report,
        output.search_results,
        output.ranked_studies,
        output.verification,
        final_synthesis_limit=MAX_REPORT_STUDIES,
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "verifying",
            "Saved deterministic audit report",
            artifact_type=ArtifactType.AUDIT_REPORT,
            artifact_name="Audit Report",
            artifact_json=audit.model_dump(),
        )
    )
    events.append(
        _ev(
            tracker,
            EventType.REPORT_DELTA,
            "synthesizing",
            "Report assembled from provider-native research workflow",
            report_markdown=output.final_report,
        )
    )
    events.append(
        _ev(
            tracker,
            EventType.ARTIFACT_CREATED,
            "complete",
            "Saved final report artifact",
            complete=True,
            artifact_type=ArtifactType.FINAL_REPORT,
            artifact_name="Final Report",
            artifact_text=output.final_report,
        )
    )
    completed_extra = {
        "sdk_available": runtime.sdk_available,
        "offline_mode": request.offline_mode,
        "execution_mode": "codex_sdk" if runtime.provider == "codex" else "native_sdk",
        "runtime_engine": runtime.runtime_engine,
        "provider_credentials_present": _has_native_credentials(
            runtime.provider,
            request.api_keys,
            codex_home_path=request.codex_home_path,
        ),
        "search_credentials_present": _search_credentials_present(request.api_keys),
        "ranked_results": len(output.ranked_studies),
        **(completion_extra or {}),
    }
    events.append(
        _ev(
            tracker,
            EventType.RUN_COMPLETED,
            "complete",
            f"{runtime.runtime_name} run completed",
            complete=True,
            report_markdown=output.final_report,
            extra=completed_extra,
        )
    )
    return events


class CodexRuntime(DeterministicRuntime):
    provider = "codex"
    runtime_name = "OpenAI Codex SDK"
    sdk_module = "openai_codex"
    runtime_engine = "openai_codex"
    planner_name = "Codex Planner"
    search_agent_name = "Codex Search Agent"
    synthesis_agent_name = "Codex Synthesis Agent"
    verifier_name = "Codex Verification Agent"
    native_agent_name = "Codex Research Agent"

    @property
    def sdk_available(self) -> bool:
        return check_codex_runtime().available

    def _execution_mode(self, request: RunRequest) -> str:
        del request
        return "codex_sdk"

    def _run_start_extra(self, request: RunRequest) -> dict[str, Any]:
        extra = super()._run_start_extra(request)
        startup_error = provider_fallback_reason(self, request)
        if startup_error:
            extra["startup_error"] = startup_error
        return extra

    async def stream_run(self, request: RunRequest) -> AsyncIterator[RuntimeEventPayload]:
        bridge = AgenticEventBridge()
        yield _agentic_run_started(self, request, bridge)
        yield _agentic_agent_started(self.native_agent_name, bridge)
        yield _ev(
            bridge.progress,
            EventType.TOOL_CALLED,
            "planning",
            "Starting Codex thread for local app tool workflow",
            tool_name="codex.thread_start",
            extra={"tool_execution": "app_local", "mcp_servers": []},
        )

        startup_error = provider_fallback_reason(self, request)
        if startup_error:
            yield _ev(
                bridge.progress,
                EventType.TOOL_RESULT,
                "failed",
                f"Codex startup failed: {startup_error}",
                tool_name="codex.thread_start",
                extra={
                    "error": startup_error,
                    "sdk_error_type": "CodexStartupError",
                    "execution_mode": "codex_sdk",
                },
            )
            raise RuntimeError(startup_error)

        task = asyncio.create_task(self._run_codex_tool_agent(request, bridge))
        started = time.monotonic()
        heartbeat_count = 0
        try:
            while True:
                elapsed = time.monotonic() - started
                remaining = CODEX_AGENTIC_TIMEOUT_SECONDS - elapsed
                if remaining <= 0:
                    timeout = TimeoutError(f"Codex run timed out after {CODEX_AGENTIC_TIMEOUT_SECONDS:g}s")
                    bridge.set_error(timeout)
                    if not task.done():
                        task.cancel()
                    break
                try:
                    queued = await asyncio.wait_for(
                        bridge.queue.get(),
                        timeout=min(CODEX_AGENTIC_HEARTBEAT_SECONDS, remaining),
                    )
                except asyncio.TimeoutError:
                    heartbeat_count += 1
                    yield _ev(
                        bridge.progress,
                        EventType.TOOL_RESULT,
                        bridge.progress.current_phase or "searching",
                        "Codex local app-tool workflow is still running",
                        tool_name="codex.thread_run",
                        extra={
                            "elapsed_seconds": round(time.monotonic() - started, 1),
                            "heartbeat": heartbeat_count,
                            "timeout_seconds": CODEX_AGENTIC_TIMEOUT_SECONDS,
                            "tool_calls": bridge._tool_call_count,
                            "state": _codex_state_summary(bridge),
                        },
                    )
                    continue
                if queued is None:
                    break
                yield queued
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            raise
        except Exception as exc:
            bridge.set_error(exc)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        try:
            await task
        except asyncio.CancelledError:
            if bridge._error is None:
                raise
        except Exception as exc:
            bridge.set_error(exc)

        debug_event = _agentic_debug_trace_event(bridge)
        if debug_event:
            yield debug_event

        submitted = bridge._intermediate.get("submitted_report")
        if bridge._error is not None or not (isinstance(submitted, str) and submitted.strip()):
            err = bridge._error
            if err is None:
                err = RuntimeError("Codex completed without an accepted submit_report call.")
                bridge.set_error(err)
            formatted = _format_exception(err) or "Codex runtime failed."
            yield _ev(
                bridge.progress,
                EventType.TOOL_RESULT,
                "failed",
                f"Codex runtime failed: {formatted}",
                tool_name="codex.thread_start",
                extra={
                    "error": formatted,
                    "execution_mode": "codex_sdk",
                    "runtime_engine": self.runtime_engine,
                    "fallback_disabled": True,
                    "tool_calls": bridge._tool_call_count,
                    **_agentic_failure_diagnostics(bridge),
                },
            )
            raise RuntimeError(formatted) from err

        final_report = submitted.strip()
        final_report, translate_events = await _maybe_translate_report(request, bridge, final_report)
        for event in translate_events:
            yield event

        for event in _agentic_final_events(self, request, final_report, bridge, report_source="submitted_report"):
            yield event

    async def _run_codex_tool_agent(
        self,
        request: RunRequest,
        bridge: AgenticEventBridge,
    ) -> None:
        from openai_codex import AsyncCodex, CodexConfig, Sandbox

        observations: list[str] = []
        executors = _build_codex_local_tool_executors(request, bridge)
        try:
            codex_home = _codex_home_for_request(request)
            config = CodexConfig(
                env={"CODEX_HOME": str(codex_home)},
                config_overrides=('cli_auth_credentials_store="file"',),
                cwd=str(REPO_ROOT),
                client_name="medical_deep_research",
                client_title="Medical Deep Research",
            )
            async with AsyncCodex(config=config) as codex:
                thread = await codex.thread_start(
                    base_instructions=_codex_agentic_instructions(request, self.runtime_name),
                    config=_codex_local_thread_config(request),
                    cwd=str(REPO_ROOT),
                    ephemeral=True,
                    model=request.model,
                    sandbox=Sandbox.read_only,
                    service_name="medical_deep_research",
                )
                await bridge.queue.put(
                    _ev(
                        bridge.progress,
                        EventType.TOOL_RESULT,
                        "planning",
                        "Codex thread started",
                        tool_name="codex.thread_start",
                        extra={"codex_thread_id": thread.id, "tool_execution": "app_local"},
                    )
                )
                for turn_index in range(1, CODEX_AGENTIC_MAX_TOOL_TURNS + 1):
                    decision, turn_result = await self._run_codex_decision_turn(
                        thread,
                        request,
                        bridge,
                        _codex_decision_prompt(request, bridge, observations, turn_index),
                        turn_index,
                    )
                    usage_payload = _codex_usage_payload(turn_result)
                    if usage_payload:
                        bridge._intermediate.setdefault("codex_turn_usage", []).append(
                            {"turn": turn_index, **usage_payload}
                        )
                    args = _codex_parse_arguments_json(decision.arguments_json)
                    try:
                        result = await _invoke_codex_local_tool(
                            request,
                            bridge,
                            executors,
                            decision.tool_name,
                            args,
                        )
                    except _ReportSubmitted:
                        bridge._intermediate["agent_final_message"] = "Codex submitted an accepted final report."
                        return
                    observations.append(_codex_tool_observation(decision.tool_name, result))
                raise RuntimeError(
                    f"Codex exceeded {CODEX_AGENTIC_MAX_TOOL_TURNS} tool-decision turns before submit_report."
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            bridge.set_error(exc)
            raise
        finally:
            await bridge.queue.put(None)

    async def _run_codex_decision_turn(
        self,
        thread: Any,
        request: RunRequest,
        bridge: AgenticEventBridge,
        prompt: str,
        turn_index: int,
    ) -> tuple[CodexToolDecision, Any]:
        from openai_codex import Sandbox, TurnResult
        from openai_codex._run import _final_assistant_response_from_items, _raise_for_failed_turn
        from openai_codex.models import (
            AgentMessageDeltaNotification,
            ItemCompletedNotification,
            ThreadTokenUsageUpdatedNotification,
            TurnCompletedNotification,
        )

        turn = await thread.turn(
            prompt,
            model=request.model,
            output_schema=_strict_json_schema_for_model(CodexToolDecision),
            sandbox=Sandbox.read_only,
        )
        await bridge.queue.put(
            _ev(
                bridge.progress,
                EventType.TOOL_RESULT,
                bridge.progress.current_phase or "planning",
                f"Codex selecting next app tool (turn {turn_index})",
                tool_name="codex.thread_run",
                extra={"codex_thread_id": thread.id, "codex_turn_id": turn.id, "turn": turn_index},
            )
        )

        completed = None
        items: list[Any] = []
        usage = None
        streamed_output_chars = 0
        streamed_output_bucket = 0
        stream = turn.stream()
        try:
            async for event in stream:
                payload = event.payload
                if isinstance(payload, AgentMessageDeltaNotification) and payload.turn_id == turn.id:
                    streamed_output_chars += len(payload.delta or "")
                    next_bucket = streamed_output_chars // 1000
                    if streamed_output_chars and (
                        streamed_output_bucket == 0 or next_bucket > streamed_output_bucket
                    ):
                        streamed_output_bucket = max(1, next_bucket)
                        await bridge.queue.put(
                            _ev(
                                bridge.progress,
                                EventType.TOOL_RESULT,
                                bridge.progress.current_phase or "planning",
                                f"Codex is preparing a tool decision ({streamed_output_chars} characters)",
                                tool_name="codex.thread_run",
                                extra={"output_characters": streamed_output_chars, "turn": turn_index},
                            )
                        )
                    continue
                if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn.id:
                    items.append(payload.item)
                    continue
                if isinstance(payload, ThreadTokenUsageUpdatedNotification) and payload.turn_id == turn.id:
                    usage = payload.token_usage
                    continue
                if isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn.id:
                    completed = payload
        finally:
            await stream.aclose()

        if completed is None:
            raise RuntimeError("Codex turn completed event was not received.")
        _raise_for_failed_turn(completed.turn)
        turn_result = completed.turn
        result = TurnResult(
            id=turn_result.id,
            status=turn_result.status,
            error=turn_result.error,
            started_at=turn_result.started_at,
            completed_at=turn_result.completed_at,
            duration_ms=turn_result.duration_ms,
            final_response=_final_assistant_response_from_items(items),
            items=items,
            usage=usage,
        )
        try:
            decision = _coerce_model_output(result.final_response, CodexToolDecision)
        except Exception as exc:
            raise RuntimeError(f"Codex returned an invalid app tool decision: {result.final_response!r}") from exc
        return decision, result

    async def _run_codex_research(
        self,
        request: RunRequest,
        *,
        progress_queue: asyncio.Queue[Any] | None = None,
    ) -> tuple[AgentResearchOutput, Any, dict[str, Any]]:
        from openai_codex import AsyncCodex, CodexConfig, Sandbox, TurnResult
        from openai_codex._run import _final_assistant_response_from_items, _raise_for_failed_turn
        from openai_codex.models import (
            AgentMessageDeltaNotification,
            ItemCompletedNotification,
            ItemStartedNotification,
            McpToolCallProgressNotification,
            ThreadTokenUsageUpdatedNotification,
            TurnCompletedNotification,
        )

        async def emit(update: dict[str, Any]) -> None:
            if progress_queue is not None:
                await progress_queue.put(update)

        codex_home = _codex_home_for_request(request)
        config = CodexConfig(
            env={"CODEX_HOME": str(codex_home)},
            config_overrides=('cli_auth_credentials_store="file"',),
            cwd=str(REPO_ROOT),
            client_name="medical_deep_research",
            client_title="Medical Deep Research",
        )
        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(
                base_instructions=_native_agent_instructions(request, self.runtime_name),
                config=_codex_thread_config(request),
                cwd=str(REPO_ROOT),
                ephemeral=True,
                model=request.model,
                sandbox=Sandbox.read_only,
                service_name="medical_deep_research",
            )
            await emit(
                {
                    "event_type": EventType.TOOL_RESULT,
                    "phase": "planning",
                    "message": "Codex thread started",
                    "tool_name": "codex.thread_start",
                    "extra": {"codex_thread_id": thread.id},
                }
            )
            async def run_turn(
                prompt: str,
                *,
                output_model: type[BaseModel],
                required_tools: set[str],
                label: str,
            ) -> tuple[Any, list[str], dict[str, Any]]:
                turn = await thread.turn(
                    prompt,
                    model=request.model,
                    output_schema=_strict_json_schema_for_model(output_model),
                    sandbox=Sandbox.read_only,
                )
                await emit(
                    {
                        "event_type": EventType.TOOL_RESULT,
                        "phase": "planning",
                        "message": f"Codex {label} turn started",
                        "tool_name": "codex.thread_run",
                        "extra": {"codex_thread_id": thread.id, "codex_turn_id": turn.id, "codex_phase": label},
                    }
                )

                completed = None
                completed_tools: set[str] = set()
                completed_tool_calls: list[str] = []
                completed_tool_payloads: dict[str, Any] = {}
                items: list[Any] = []
                usage = None
                streamed_output_chars = 0
                streamed_output_bucket = 0
                stream = turn.stream()
                try:
                    async for event in stream:
                        payload = event.payload
                        if isinstance(payload, ItemStartedNotification) and payload.turn_id == turn.id:
                            update = _codex_progress_update_from_item(payload.item, completed=False)
                            if update:
                                await emit(update)
                            continue
                        if isinstance(payload, McpToolCallProgressNotification) and payload.turn_id == turn.id:
                            await emit(
                                {
                                    "event_type": EventType.TOOL_RESULT,
                                    "phase": "searching",
                                    "message": f"Codex MCP tool progress: {payload.message}",
                                    "tool_name": "codex.thread_run",
                                    "extra": {
                                        "codex_thread_id": payload.thread_id,
                                        "codex_turn_id": payload.turn_id,
                                        "codex_item_id": payload.item_id,
                                        "codex_phase": label,
                                    },
                                }
                            )
                            continue
                        if isinstance(payload, AgentMessageDeltaNotification) and payload.turn_id == turn.id:
                            streamed_output_chars += len(payload.delta or "")
                            next_bucket = streamed_output_chars // 2000
                            if streamed_output_chars and (
                                streamed_output_bucket == 0 or next_bucket > streamed_output_bucket
                            ):
                                streamed_output_bucket = max(1, next_bucket)
                                await emit(
                                    {
                                        "event_type": EventType.TOOL_RESULT,
                                        "phase": "synthesizing",
                                        "message": (
                                            "Codex is streaming final structured output "
                                            f"({streamed_output_chars} characters)"
                                        ),
                                        "tool_name": "codex.thread_run",
                                        "extra": {"output_characters": streamed_output_chars, "codex_phase": label},
                                    }
                                )
                            continue
                        if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn.id:
                            items.append(payload.item)
                            root = _codex_item_root(payload.item)
                            if getattr(root, "type", None) == "mcpToolCall":
                                tool_name = str(getattr(root, "tool", "") or "")
                                status = str(getattr(root, "status", "") or "")
                                tool_payload = _codex_tool_result_payload(root)
                                if tool_name and not _codex_tool_status_failed(status):
                                    completed_tools.add(tool_name)
                                    completed_tool_calls.append(tool_name)
                                    completed_tool_payloads[tool_name] = tool_payload
                            update = _codex_progress_update_from_item(payload.item, completed=True)
                            if update:
                                update["extra"] = {**dict(update.get("extra") or {}), "codex_phase": label}
                                await emit(update)
                            if getattr(root, "type", None) == "mcpToolCall":
                                tool_name = str(getattr(root, "tool", "") or "")
                                status = str(getattr(root, "status", "") or "")
                                if _codex_tool_status_failed(status):
                                    tool_payload = _codex_tool_result_payload(root)
                                    error_text = _trim_diagnostic_text(
                                        _codex_tool_error_text(tool_payload),
                                        max_chars=2000,
                                    )
                                    if not error_text:
                                        error_text = status or "MCP tool failed."
                                    raise RuntimeError(f"Codex MCP tool `{tool_name}` failed: {error_text}")
                            continue
                        if isinstance(payload, ThreadTokenUsageUpdatedNotification) and payload.turn_id == turn.id:
                            usage = payload.token_usage
                            continue
                        if isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn.id:
                            completed = payload
                finally:
                    await stream.aclose()

                if completed is None:
                    raise RuntimeError("Codex turn completed event was not received.")
                _raise_for_failed_turn(completed.turn)
                missing_tools = sorted(required_tools - completed_tools)
                if missing_tools:
                    raise RuntimeError(
                        f"Codex {label} turn completed without required MCP tool calls: "
                        + ", ".join(missing_tools)
                    )
                turn_result = completed.turn
                result = TurnResult(
                    id=turn_result.id,
                    status=turn_result.status,
                    error=turn_result.error,
                    started_at=turn_result.started_at,
                    completed_at=turn_result.completed_at,
                    duration_ms=turn_result.duration_ms,
                    final_response=_final_assistant_response_from_items(items),
                    items=items,
                    usage=usage,
                )
                return result, completed_tool_calls, completed_tool_payloads

            _phase1_result, phase1_tool_calls, phase1_payloads = await run_turn(
                _native_search_rank_prompt(request),
                output_model=CodexPhaseOutput,
                required_tools=CODEX_PHASE1_MCP_TOOLS,
                label="search_rank",
            )
            aggregate_payload = _codex_tool_payload_dict(phase1_payloads, "aggregate_search")
            ranked_payload = _codex_tool_payload_dict(phase1_payloads, "rank_results")
            plan_payload = aggregate_payload.get("plan")
            plan = (
                QueryPlan.model_validate(plan_payload)
                if isinstance(plan_payload, dict)
                else build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
            )
            raw_results = aggregate_payload.get("results")
            search_results = [
                SearchProviderResult.model_validate(result)
                for result in raw_results
                if isinstance(result, dict)
            ] if isinstance(raw_results, list) else []
            raw_ranked = ranked_payload.get("studies")
            ranked_studies = [
                ScoredStudy.model_validate(study)
                for study in raw_ranked
                if isinstance(study, dict)
            ] if isinstance(raw_ranked, list) else []

            fulltext_payload = await _codex_fetch_fulltext_for_ranked_studies(
                request,
                plan=plan,
                search_results=search_results,
                ranked_studies=ranked_studies,
                progress_queue=progress_queue,
            )

            result, phase2_tool_calls, phase2_payloads = await run_turn(
                _native_synthesis_prompt(
                    request,
                    aggregate_payload=aggregate_payload,
                    ranked_payload=ranked_payload,
                    fulltext_payload=fulltext_payload,
                ),
                output_model=CodexCompletionOutput,
                required_tools=CODEX_PHASE2_MCP_TOOLS,
                label="synthesis",
            )
            completed_tool_calls = phase1_tool_calls + ["fetch_fulltext"] + phase2_tool_calls
            completed_tool_payloads = {**phase1_payloads, **phase2_payloads, "fetch_fulltext": fulltext_payload}
        output = _codex_output_from_mcp_payloads(
            request,
            self.runtime_name,
            completed_tool_payloads,
            final_response=result.final_response,
        )
        aggregate_payload = completed_tool_payloads.get("aggregate_search")
        fulltext_payload = completed_tool_payloads.get("fetch_fulltext")
        completion_extra = _codex_mcp_completion_extra(
            output,
            completed_tool_calls,
            aggregate_payload if isinstance(aggregate_payload, dict) else None,
            fulltext_payload if isinstance(fulltext_payload, dict) else None,
        )
        return output, result, completion_extra


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
        """Look up free full text for ranked studies and request user PDFs when needed."""
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
    if provider == "codex":
        return CodexRuntime()
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
