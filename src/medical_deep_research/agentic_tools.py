"""Shared tool logic and event bridge for all agentic runtimes.

Provider-specific builders (Anthropic, OpenAI, Google, LangChain) wrap these
functions in their SDK's tool format.  The functions operate on a shared
``AgenticEventBridge`` that holds per-run state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from .models import (
    ApprovalRequest,
    ApprovalStatus,
    ArtifactType,
    EventType,
    ResearchArtifact,
    ResearchRun,
    ResearchStatus,
    RuntimeEventPayload,
)
from .provider_config import (
    DEEPSEEK_BASE_URL,
    deepseek_api_key,
    deepseek_reasoning_effort,
    deepseek_thinking_body,
    local_base_url,
)
from .research import (
    MAX_REPORT_STUDIES,
    build_query_plan,
    empty_verification_summary,
    enrich_report_citations,
    flatten_studies,
    render_reference_entries,
    render_report,
    render_verification_report,
    score_and_rank_results,
    search_source,
    snowball,
    verify_studies,
)
from .progress import ProgressTracker
from .research.models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary
from .research.fulltext import fetch_europe_pmc_fulltext_xml
from .research.planning import (
    is_ai_communication_education_query,
    suggest_databases as _suggest_databases,
)
from .research.search import POLITE_EMAIL, USER_AGENT
from .models import RunRequest

_log = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    ResearchStatus.CANCELLED.value,
    ResearchStatus.INTERRUPTED.value,
    ResearchStatus.FAILED.value,
    ResearchStatus.COMPLETED.value,
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _debug_jsonable(value: Any, *, _depth: int = 0) -> Any:
    """Convert SDK/tool objects into JSON-compatible debug payloads."""
    if _depth > 8:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _debug_jsonable(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_debug_jsonable(item, _depth=_depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _debug_jsonable(value.model_dump(), _depth=_depth + 1)
        except Exception:
            pass

    message_payload: dict[str, Any] = {"_class": type(value).__name__}
    for attr in (
        "type",
        "role",
        "name",
        "content",
        "tool_call_id",
        "tool_calls",
        "additional_kwargs",
        "response_metadata",
    ):
        if hasattr(value, attr):
            try:
                message_payload[attr] = _debug_jsonable(getattr(value, attr), _depth=_depth + 1)
            except Exception:
                message_payload[attr] = "<unserializable>"
    if len(message_payload) > 1:
        return message_payload

    return str(value)

# ---------------------------------------------------------------------------
# Event bridge — provider-agnostic shared state + event queue
# ---------------------------------------------------------------------------

# Canonical (bare) tool names used in the phase map.
# Provider-specific builders may namespace them (e.g. ``mcp__literature__plan_search``)
# and should call ``bridge.set_tool_name_map`` if the runtime tool names differ.

_BARE_PHASE_MAP: dict[str, str] = {
    "plan_search": "planning",
    "suggest_databases": "planning",
    "search_pubmed": "searching",
    "search_pmc": "searching",
    "search_europe_pmc": "searching",
    "search_openalex": "searching",
    "search_crossref": "searching",
    "search_cochrane": "searching",
    "search_semantic_scholar": "searching",
    "search_scopus": "searching",
    "search_clinical_trials": "searching",
    "search_preprints": "searching",
    "get_references": "searching",
    "get_citations": "searching",
    "get_studies": "ranking",
    "browse_studies": "ranking",
    "screen_studies": "screening",
    "finalize_ranking": "ranking",
    "appraise_evidence": "appraising",
    "verify_studies": "verifying",
    "synthesize_report": "synthesizing",
    "fetch_fulltext": "fulltext",
    "await_user_pdfs": "fulltext",
    "parse_pdf": "fulltext",
}

# Bookkeeping tools follow whatever phase the run is currently in instead of
# flipping the trace back to "planning" on every call.
_CURRENT_PHASE_TOOLS = {"write_todos", "update_progress"}


class AgenticEventBridge:
    """Shared state + async event queue for agentic runtimes.

    Tool functions mutate this object (append search results, store rankings,
    etc.).  Hook / callback adapters push ``RuntimeEventPayload`` events onto
    ``self.queue`` so the ``stream_run`` coroutine can yield them to the
    service layer.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[RuntimeEventPayload | None] = asyncio.Queue()
        self.progress = ProgressTracker()
        self._intermediate: dict[str, Any] = {}
        self._todos: list[str] = []
        self._tool_call_count = 0
        self._result: str | None = None
        self._error: Exception | None = None
        self.full_trace_enabled = _env_flag("MDR_SAVE_FULL_TRACE", default=True)

        # Shared state written by tools, read by evidence tools
        self.search_results: list[SearchProviderResult] = []
        self.ranked_studies: list[ScoredStudy] = []
        self.verification: VerificationSummary | None = None
        self.screening: dict[str, Any] | None = None
        self.appraisal: dict[str, Any] | None = None
        self.plan: QueryPlan | None = None
        self._pre_scored: list[ScoredStudy] = []
        self._pdf_urls: dict[int, str] = {}
        self._pdf_url_alternatives: dict[int, list[str]] = {}
        self._pdf_bytes: dict[int, bytes] = {}
        self._pdf_sources: dict[int, str] = {}

        # Tool name mapping: runtime-specific name → bare name.
        # Populated by provider builder if it uses namespaced names.
        self._tool_alias: dict[str, str] = {}

    def set_tool_name_map(self, mapping: dict[str, str]) -> None:
        """Register a mapping from runtime tool names to bare tool names."""
        self._tool_alias = mapping

    def _bare_name(self, tool_name: str) -> str:
        """Resolve a runtime-specific tool name to the canonical bare name."""
        if tool_name in self._tool_alias:
            return self._tool_alias[tool_name]
        # Strip common prefixes (e.g. mcp__literature__plan_search → plan_search)
        if "__" in tool_name:
            return tool_name.rsplit("__", 1)[-1]
        return tool_name

    def _phase_for(self, tool_name: str) -> str:
        bare = self._bare_name(tool_name)
        if bare in _CURRENT_PHASE_TOOLS:
            return self.progress.current_phase or "planning"
        if bare in _BARE_PHASE_MAP:
            return _BARE_PHASE_MAP[bare]
        if bare.startswith("search_"):
            return "searching"
        return "searching"

    # -- Generic event helpers (called by provider-specific hooks/callbacks) --

    async def on_tool_start(self, tool_name: str, tool_input: dict[str, Any] | None = None) -> None:
        phase, _ = self.progress.enter(self._phase_for(tool_name))
        self._tool_call_count += 1
        input_summary = {}
        if tool_input:
            input_summary = {k: (str(v)[:120] + "..." if len(str(v)) > 120 else v) for k, v in tool_input.items()}
        _log.info("[AGENT CALL #%d] %s  input=%s", self._tool_call_count, tool_name, json.dumps(input_summary, default=str))
        extra: dict[str, Any] = {"tool_input": input_summary}
        if self.full_trace_enabled and tool_input is not None:
            extra["full_tool_input"] = _debug_jsonable(tool_input)
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.TOOL_CALLED,
                phase=phase,
                progress=self.progress.advance(),
                message=f"Agent calling {tool_name}",
                tool_name=tool_name,
                extra=extra,
            )
        )

    async def on_tool_end(self, tool_name: str, response: Any = None) -> None:
        phase, _ = self.progress.enter(self._phase_for(tool_name))
        resp_str = str(response) if response else "<empty>"
        resp_preview = resp_str[:300] + "..." if len(resp_str) > 300 else resp_str
        _log.info("[AGENT RESULT #%d] %s  response_len=%d  preview=%s", self._tool_call_count, tool_name, len(resp_str), resp_preview)
        bare = self._bare_name(tool_name)
        if bare in (
            "get_studies",
            "browse_studies",
            "screen_studies",
            "finalize_ranking",
            "appraise_evidence",
            "verify_studies",
            "synthesize_report",
            "plan_search",
            "fetch_fulltext",
            "await_user_pdfs",
        ):
            self._intermediate[bare] = response
        extra: dict[str, Any] = {"response_length": len(resp_str)}
        if isinstance(response, dict):
            for key in ("error", "issues", "warnings", "fatal", "fallback_reason", "rejection_count"):
                if key in response:
                    extra[key] = _debug_jsonable(response[key])
        if self.full_trace_enabled:
            extra["full_tool_output"] = _debug_jsonable(response)
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.TOOL_RESULT,
                phase=phase,
                progress=self.progress.advance(),
                message=self._tool_result_message(bare, tool_name, response),
                tool_name=tool_name,
                extra=extra,
            )
        )
        if bare == "fetch_fulltext" and isinstance(response, dict):
            await self.queue.put(
                RuntimeEventPayload(
                    event_type=EventType.ARTIFACT_CREATED,
                    phase=self.progress.phase_label("fulltext"),
                    progress=self.progress.advance(),
                    message="Saved full-text PDF status",
                    artifact_type=ArtifactType.FULLTEXT_STATUS,
                    artifact_name="Full Text PDF Status",
                    artifact_json=_debug_jsonable(response),
                )
            )
        if bare == "finalize_ranking" and self.ranked_studies:
            await self.queue.put(
                RuntimeEventPayload(
                    event_type=EventType.ARTIFACT_CREATED,
                    phase=self.progress.phase_label("ranking"),
                    progress=self.progress.advance(),
                    message="Saved ranked evidence artifact",
                    artifact_type=ArtifactType.RANKED_RESULTS,
                    artifact_name="Ranked Results",
                    artifact_json={"studies": [study.model_dump() for study in self.ranked_studies]},
                )
            )
        if bare == "screen_studies" and self.screening is not None:
            await self.queue.put(
                RuntimeEventPayload(
                    event_type=EventType.ARTIFACT_CREATED,
                    phase=self.progress.phase_label("screening"),
                    progress=self.progress.advance(),
                    message="Saved screening decisions",
                    artifact_type=ArtifactType.SCREENING_DECISIONS,
                    artifact_name="Screening Decisions",
                    artifact_json=_debug_jsonable(self.screening),
                )
            )
        if bare == "appraise_evidence" and self.appraisal is not None:
            await self.queue.put(
                RuntimeEventPayload(
                    event_type=EventType.ARTIFACT_CREATED,
                    phase=self.progress.phase_label("appraising"),
                    progress=self.progress.advance(),
                    message="Saved GRADE appraisal summary",
                    artifact_type=ArtifactType.APPRAISAL_SUMMARY,
                    artifact_name="GRADE Appraisal",
                    artifact_json=_debug_jsonable(self.appraisal),
                )
            )

    def _tool_result_message(self, bare: str, tool_name: str, response: Any) -> str:
        if not isinstance(response, dict):
            return f"Agent received result from {tool_name}"
        if bare == "fetch_fulltext":
            found = int(response.get("pdfs_found") or 0)
            requested = response.get("requested_upload_ranks") or []
            unavailable = response.get("unavailable_pdf_ranks") or response.get("missing_pdf_ranks") or []
            checkpoint = response.get("user_pdf_checkpoint")
            if isinstance(checkpoint, dict):
                status = checkpoint.get("status", "resolved")
                return (
                    f"Full-text PDFs: {found} available; requested user uploads for "
                    f"{len(requested)} studies; checkpoint {status}; {len(unavailable)} unavailable"
                )
            if response.get("error"):
                return f"Full-text PDF lookup failed: {response['error']}"
            xml_hits = int(response.get("europe_pmc_xml_hits") or 0)
            xml_note = f" ({xml_hits} via Europe PMC XML)" if xml_hits else ""
            return f"Full text: {found} available{xml_note}; {len(unavailable)} need user upload"
        if bare == "await_user_pdfs":
            uploaded = response.get("uploaded_ranks") or []
            missing = response.get("missing_ranks") or []
            status = response.get("status", "resolved")
            return f"User PDF checkpoint {status}: {len(uploaded)} uploaded, {len(missing)} still missing"
        if bare == "parse_pdf":
            rank = response.get("rank", "?")
            if response.get("error"):
                return f"PDF parse failed for rank {rank}: {response['error']}"
            source = response.get("source") or "pdf"
            length = int(response.get("text_length") or 0)
            return f"Parsed PDF for rank {rank} from {source} ({length} characters)"
        return f"Agent received result from {tool_name}"

    def capture_agent_result(self, result: Any) -> None:
        if self.full_trace_enabled:
            self._intermediate["agent_result_payload"] = _debug_jsonable(result)

    def debug_trace_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool_call_count": self._tool_call_count,
            "had_error": self._error is not None,
            "error": str(self._error) if self._error is not None else None,
            "intermediate": _debug_jsonable(self._intermediate),
            "todos": list(self._todos),
            "search_results": _debug_jsonable([result.model_dump() for result in self.search_results]),
            "ranked_studies": _debug_jsonable([study.model_dump() for study in self.ranked_studies]),
            "verification": _debug_jsonable(self.verification.model_dump()) if self.verification else None,
            "screening": _debug_jsonable(self.screening) if self.screening else None,
            "appraisal": _debug_jsonable(self.appraisal) if self.appraisal else None,
            "plan": _debug_jsonable(self.plan.model_dump()) if self.plan else None,
        }
        return payload

    # -- Direct calls from workspace tools -----------------------------------

    async def emit_todos(self, items: list[str]) -> None:
        self._todos = list(items)
        phase, _ = self.progress.enter(self.progress.current_phase or "planning")
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.ARTIFACT_CREATED,
                phase=phase,
                progress=self.progress.advance(),
                message="Agent created research TODO list",
                artifact_type=ArtifactType.TODO_LIST,
                artifact_name="Research TODOs",
                artifact_text="\n".join(f"- {item}" for item in items),
            )
        )

    async def emit_progress(self, phase: str, message: str) -> None:
        label, _ = self.progress.enter(phase)
        await self.queue.put(
            RuntimeEventPayload(
                event_type=EventType.AGENT_STARTED,
                phase=label,
                progress=self.progress.advance(),
                message=message,
                agent_name="Research Agent",
            )
        )

    # -- Claude Agent SDK hook callbacks (HookCallback signature) -------------

    async def pre_tool_use(  # type: ignore[return]
        self,
        hook_input: Any,
        tool_use_id: str | None,
        context: Any,
    ) -> Any:
        tool_name = hook_input.get("tool_name", "unknown")
        tool_input = hook_input.get("tool_input", {})
        await self.on_tool_start(tool_name, tool_input)
        return {"hookEventName": "PreToolUse"}

    async def post_tool_use(  # type: ignore[return]
        self,
        hook_input: Any,
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        tool_name = hook_input.get("tool_name", "unknown")
        response = hook_input.get("tool_response")
        await self.on_tool_end(tool_name, response)
        return {"hookEventName": "PostToolUse"}

    # -- Completion ----------------------------------------------------------

    def set_result(self, text: str | None) -> None:
        self._result = text

    def set_error(self, exc: Exception | Any) -> None:
        if isinstance(exc, Exception):
            self._error = exc
        else:
            self._error = RuntimeError(str(exc))


# ---------------------------------------------------------------------------
# Shared tool logic — plain async functions returning dict
# ---------------------------------------------------------------------------

async def tool_plan_search(request: RunRequest, bridge: AgenticEventBridge, query: str, query_type: str) -> dict[str, Any]:
    payload = request.query_payload if query == request.query else None
    plan = build_query_plan(query, query_type or request.query_type, request.provider, payload)
    bridge.plan = plan
    return plan.model_dump()


async def tool_suggest_databases(request: RunRequest, bridge: AgenticEventBridge, query: str) -> dict[str, Any]:
    dbs = _suggest_databases(query, request.provider)
    return {"databases": dbs}


async def tool_search(request: RunRequest, bridge: AgenticEventBridge, source: str, query: str, max_results: int = 15) -> dict[str, Any]:
    result = await search_source(
        source, query,
        api_keys=request.api_keys,
        max_results=max_results,
        offline_mode=request.offline_mode,
        domain="clinical",
        start_year=request.search_start_year,
        scopus_view=request.scopus_view,
    )
    bridge.search_results.append(result)
    studies_summary = []
    for s in result.studies:
        abstract = (s.abstract or "").replace("\n", " ").strip()
        title = s.title or ""
        studies_summary.append({
            "title": title[:200] + "..." if len(title) > 200 else title,
            "journal": s.journal,
            "year": s.publication_year,
            "pmid": s.pmid,
            "pmcid": s.pmcid,
            "doi": s.doi,
            "evidence_level": s.evidence_level,
            "citation_count": s.citation_count,
            "abstract": abstract[:300] + "..." if len(abstract) > 300 else abstract,
        })
    return {"source": result.source, "count": len(result.studies), "error": result.error, "studies": studies_summary}


# Tier/page size for the agent's study triage: get_studies returns the top tier
# of this many cards; browse_studies pages the rest of the scored pool.
STUDY_PAGE_SIZE = 15
FULLTEXT_CANDIDATE_LIMIT = 10
FULLTEXT_SYNTHESIS_EXCERPT_CHARS = 3000
PMC_ID_CONVERTER_URLS = (
    "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
    "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
)

_EVIDENCE_ORDER = ("Level I", "Level II", "Level III", "Level IV", "Level V")
_PCC_AI_COMMUNICATION_REQUIRED_SOURCES = (
    "PubMed",
    "PMC",
    "Europe PMC",
    "OpenAlex",
    "Crossref",
    "ClinicalTrials.gov",
)


def _evidence_level_rank(level: str | None) -> int:
    """Map "Level I".."Level V" to 1..5 (unknown -> 6).

    Check the longer substrings (iii/iv/v) before the shorter (ii/i) so that a
    Level III study is not matched as "level i".
    """
    if not level:
        return 6
    lo = level.lower()
    if "level iii" in lo:
        return 3
    if "level iv" in lo:
        return 4
    if "level v" in lo:
        return 5
    if "level ii" in lo:
        return 2
    if "level i" in lo:
        return 1
    return 6


def _study_card(s: ScoredStudy) -> dict[str, Any]:
    abstract = (s.abstract or "").replace("\n", " ").strip()
    return {
        "idx": s.reference_number,  # stable composite-rank index across pages
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
        "source_count": len(s.sources),
        "pre_score": s.composite_score,
    }


def _facets(pool: list[ScoredStudy]) -> dict[str, Any]:
    by_level: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for s in pool:
        key = s.evidence_level or "Unknown"
        by_level[key] = by_level.get(key, 0) + 1
        for src in (s.sources or [s.source]):
            by_source[src] = by_source.get(src, 0) + 1
    ordered = {lvl: by_level[lvl] for lvl in _EVIDENCE_ORDER if lvl in by_level}
    if "Unknown" in by_level:
        ordered["Unknown"] = by_level["Unknown"]
    return {"counts_by_evidence_level": ordered, "counts_by_source": by_source}


def _tier_ordered(pool: list[ScoredStudy]) -> list[ScoredStudy]:
    """Group by evidence level I->V, then by composite score (desc) within a level."""
    return sorted(pool, key=lambda s: (_evidence_level_rank(s.evidence_level), -s.composite_score))


def _source_attempts(bridge: AgenticEventBridge) -> set[str]:
    return {result.source for result in bridge.search_results}


def _missing_required_source_attempts(request: RunRequest, bridge: AgenticEventBridge) -> list[str]:
    if request.provider != "codex" or request.query_type.lower() != "pcc":
        return []
    plan = bridge.plan or build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
    if not is_ai_communication_education_query(request.query, request.query_type, request.query_payload or {}):
        return []
    required = [
        source for source in _PCC_AI_COMMUNICATION_REQUIRED_SOURCES
        if source in plan.databases or source == "ClinicalTrials.gov"
    ]
    attempted = _source_attempts(bridge)
    return [source for source in required if source not in attempted]


async def tool_get_studies(request: RunRequest, bridge: AgenticEventBridge, context: str = "general") -> dict[str, Any]:
    missing_sources = _missing_required_source_attempts(request, bridge)
    if missing_sources:
        return {
            "error": (
                "Search coverage is incomplete for this PCC AI communication/SDM education query. "
                "Attempt these sources before triage: " + ", ".join(missing_sources) + ". "
                "Source attempts count even if the source returns zero records or an API error."
            ),
            "missing_sources": missing_sources,
            "attempted_sources": sorted(_source_attempts(bridge)),
        }

    all_studies = flatten_studies(bridge.search_results)
    if not all_studies:
        return {"error": "No studies collected yet. Run search tools first.", "studies": []}
    pre_scored = score_and_rank_results(
        all_studies,
        context=context,
        query=request.query,
        query_payload=request.query_payload,
    )
    bridge._pre_scored = pre_scored
    # Re-deriving the pool invalidates any prior screening decision.
    bridge.screening = None
    display = _tier_ordered(pre_scored)
    page = display[:STUDY_PAGE_SIZE]
    return {
        "total": len(pre_scored),
        "shown": len(page),
        "page": 1,
        "page_size": STUDY_PAGE_SIZE,
        "has_more": len(pre_scored) > STUDY_PAGE_SIZE,
        "context": context,
        **_facets(pre_scored),
        "studies": [_study_card(s) for s in page],
        "note": (
            "Top tier shown, grouped by evidence level I->V. Indices (idx) are stable "
            "across pages. Call browse_studies(page=2) for the next tier, or "
            "browse_studies(evidence_level='Level III') / browse_studies(source='PubMed') "
            "to expand a slice before screening."
        ),
    }


async def tool_browse_studies(
    request: RunRequest,
    bridge: AgenticEventBridge,
    page: int = 1,
    evidence_level: str | None = None,
    source: str | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    """Page/expand the already-scored study pool without re-scoring or resetting screening.

    Reads ``bridge._pre_scored`` only — it never writes screening, the pool, or the
    ranking, so paging cannot clobber an in-progress screening decision.
    """
    pool = bridge._pre_scored
    if not pool:
        return {"error": "Call get_studies first.", "studies": []}
    display = _tier_ordered(pool)
    if evidence_level:
        want = _evidence_level_rank(evidence_level)
        display = [s for s in display if _evidence_level_rank(s.evidence_level) == want]
    if source:
        src_lo = source.strip().lower()
        display = [
            s for s in display
            if any(src_lo in (x or "").lower() for x in (s.sources or [s.source]))
        ]
    ps = max(1, int(page_size or STUDY_PAGE_SIZE))
    page = max(1, int(page))
    offset = (page - 1) * ps
    window = display[offset:offset + ps]
    return {
        "total_in_pool": len(pool),
        "filtered_total": len(display),
        "page": page,
        "page_size": ps,
        "shown": len(window),
        "has_more": offset + ps < len(display),
        "evidence_level": evidence_level,
        "source": source,
        **_facets(pool),
        "studies": [_study_card(s) for s in window],
    }


async def tool_finalize_ranking(request: RunRequest, bridge: AgenticEventBridge, ranked_indices: list[int], rationale: str = "") -> dict[str, Any]:
    pre_scored = bridge._pre_scored
    if not pre_scored:
        return {"error": "Call get_studies first."}
    idx_map = {s.reference_number: s for s in pre_scored}
    ranked: list[ScoredStudy] = []
    seen: set[int] = set()
    for i, idx in enumerate(ranked_indices, start=1):
        idx = int(idx)
        if idx in idx_map and idx not in seen:
            study = idx_map[idx].model_copy(deep=True)
            study.reference_number = i
            ranked.append(study)
            seen.add(idx)
    for s in pre_scored:
        if s.reference_number not in seen:
            study = s.model_copy(deep=True)
            study.reference_number = len(ranked) + 1
            ranked.append(study)
    bridge.ranked_studies = ranked
    return {
        "status": "ok", "total_ranked": len(ranked),
        "top_5": [{"rank": s.reference_number, "title": s.title} for s in ranked[:5]],
        "rationale": rationale,
    }


_GRADE_LEVELS = {"high": "High", "moderate": "Moderate", "low": "Low", "very low": "Very Low"}


def _normalize_certainty(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in _GRADE_LEVELS:
        return _GRADE_LEVELS[text]
    if "very" in text and "low" in text:
        return "Very Low"
    for key, label in _GRADE_LEVELS.items():
        if key in text:
            return label
    return "Low"


async def tool_snowball(
    request: RunRequest,
    bridge: AgenticEventBridge,
    reference_number: int,
    direction: str,
) -> dict[str, Any]:
    """Fetch the reference list or citing papers of a ranked study (snowballing)."""
    direction = "references" if str(direction).lower().startswith("ref") else "citations"
    pool = bridge.ranked_studies or bridge._pre_scored
    if not pool:
        return {"error": "Rank studies first (get_studies/finalize_ranking) before snowballing."}
    target = next((s for s in pool if s.reference_number == int(reference_number)), None)
    if target is None:
        return {"error": f"No ranked study [{reference_number}] found."}
    result = await snowball(target, direction)  # type: ignore[arg-type]
    bridge.search_results.append(result)
    summary = []
    for s in result.studies[:10]:
        abstract = (s.abstract or "").replace("\n", " ").strip()
        summary.append({
            "title": s.title[:200],
            "journal": s.journal,
            "year": s.publication_year,
            "pmid": s.pmid,
            "doi": s.doi,
            "evidence_level": s.evidence_level,
            "abstract": abstract[:300] + "..." if len(abstract) > 300 else abstract,
        })
    return {
        "direction": direction,
        "seed_reference": int(reference_number),
        "new_candidates": len(result.studies),
        "error": result.error,
        "studies": summary,
        "note": "Call get_studies again to merge and re-rank these candidates.",
    }


async def tool_screen_studies(
    request: RunRequest,
    bridge: AgenticEventBridge,
    included_indices: list[int],
    excluded_indices: list[int] | None = None,
    exclusion_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Apply explicit PICO-based screening to the deduped study pool (whitelist).

    The agent is the screening judge: ONLY the studies whose indices appear in
    ``included_indices`` survive. Every other study is dropped — recorded as an
    itemized exclusion when the agent supplied an ``excluded_indices`` reason, or
    bucketed into ``not_selected`` otherwise (so Methods can report how many were
    screened out). Passing an empty include-list is rejected rather than nuking
    the pool.
    """
    pre_scored = bridge._pre_scored
    if not pre_scored:
        return {"error": "Call get_studies first."}
    included_set = {int(i) for i in included_indices}
    excluded_indices = [int(i) for i in (excluded_indices or [])]
    reasons = list(exclusion_reasons or [])
    reason_map = {
        idx: (reasons[i] if i < len(reasons) else "No reason given")
        for i, idx in enumerate(excluded_indices)
    }

    if not included_set:
        return {
            "error": (
                "Whitelist screening: pass at least one included index. Studies not in "
                "included_indices are dropped."
            ),
            "screened": len(pre_scored),
            "included": 0,
        }

    kept: list[ScoredStudy] = []
    excluded_records: list[dict[str, Any]] = []
    not_selected: list[dict[str, Any]] = []
    for study in pre_scored:
        ref = study.reference_number
        if ref in included_set:
            kept.append(study)
        elif ref in reason_map:
            excluded_records.append({
                "reference_number": ref,
                "title": study.title,
                "reason": reason_map[ref],
            })
        else:
            not_selected.append({"reference_number": ref, "title": study.title})

    # Keep only the survivors so a later get_studies (e.g. after snowballing) rebuilds.
    bridge._pre_scored = kept
    bridge.screening = {
        "screened_count": len(pre_scored),
        "included": len(kept),
        "excluded": excluded_records,
        "not_selected_count": len(not_selected),
        "not_selected": not_selected,
    }
    warning = None
    if len(kept) < 3:
        warning = "Fewer than 3 studies passed screening — consider broadening searches or snowballing before ranking."
    return {
        "status": "ok",
        "screened": len(pre_scored),
        "included": len(kept),
        "excluded": len(excluded_records),
        "not_selected": len(not_selected),
        "warning": warning,
    }


async def tool_appraise_evidence(
    request: RunRequest,
    bridge: AgenticEventBridge,
    findings: list[str],
    certainties: list[str],
    rationales: list[str] | None = None,
    reference_numbers_csv: list[str] | None = None,
) -> dict[str, Any]:
    """Record GRADE-style certainty of evidence for each major finding.

    Parallel arrays keep the tool schema simple for weak models. Certainty is
    normalized to High/Moderate/Low/Very Low. Findings backed only by studies
    with no retrieved full text are flagged as abstract-only assessments.
    """
    if not bridge.ranked_studies:
        return {"error": "No ranked studies. Call finalize_ranking first."}
    rationales = list(rationales or [])
    refs_csv = list(reference_numbers_csv or [])

    fulltext_ranks = {
        rank for rank in range(1, len(bridge.ranked_studies) + 1)
        if _stored_fulltext_for_rank(request, rank)
    }

    appraised: list[dict[str, Any]] = []
    for i, finding in enumerate(findings):
        refs: list[int] = []
        if i < len(refs_csv):
            for token in re.split(r"[,\s]+", str(refs_csv[i])):
                token = token.strip().lstrip("[").rstrip("]")
                if token.isdigit():
                    refs.append(int(token))
        abstract_only = bool(refs) and not any(r in fulltext_ranks for r in refs)
        appraised.append({
            "finding": finding,
            "certainty": _normalize_certainty(certainties[i] if i < len(certainties) else None),
            "rationale": rationales[i] if i < len(rationales) else "",
            "reference_numbers": refs,
            "abstract_only_assessment": abstract_only,
        })

    any_abstract_only = any(item["abstract_only_assessment"] for item in appraised)
    bridge.appraisal = {
        "findings": appraised,
        "abstract_only_any": any_abstract_only,
    }
    return {
        "status": "ok",
        "appraised": len(appraised),
        "certainties": [item["certainty"] for item in appraised],
        "abstract_only_any": any_abstract_only,
    }


async def tool_verify_studies(request: RunRequest, bridge: AgenticEventBridge) -> dict[str, Any]:
    if not bridge.ranked_studies:
        return {"error": "No ranked studies. Call finalize_ranking first."}
    summary = await verify_studies(
        bridge.ranked_studies,
        api_keys=request.api_keys,
        offline_mode=request.offline_mode,
        limit=8,
    )
    bridge.verification = summary
    return {"verified": summary.verified_pmids, "missing": summary.missing_pmids, "markdown": render_verification_report(summary)}


async def tool_synthesize_report(request: RunRequest, bridge: AgenticEventBridge) -> dict[str, Any]:
    plan = bridge.plan or build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
    verification = bridge.verification or empty_verification_summary("Verification was not run.")

    # Return structured data so the LLM writes a real synthesis — NOT a pre-formatted template
    report_studies = bridge.ranked_studies[:MAX_REPORT_STUDIES]

    # Re-fetch canonical bibliographic metadata (volume/issue/pages/year/journal abbrev/authors)
    # for the cited studies so the deterministic References section is complete and correct.
    # Guarded so retries of synthesize_report do not repeat the network calls.
    if not bridge._intermediate.get("_citation_metadata_enriched"):
        try:
            await enrich_report_citations(
                report_studies,
                api_keys=request.api_keys,
                offline_mode=request.offline_mode,
            )
        except Exception:  # pragma: no cover - defensive network path
            pass
        bridge._intermediate["_citation_metadata_enriched"] = True

    studies_data = []
    for s in report_studies:
        entry: dict[str, Any] = {
            "rank": s.reference_number,
            "title": s.title,
            "authors": s.authors[:3] if s.authors else [],
            "year": s.publication_year,
            "journal": s.journal_abbrev or s.journal,
            "volume": s.volume,
            "issue": s.issue,
            "pages": s.pages,
            "source": s.source,
            "doi": s.doi,
            "pmid": s.pmid,
            "pmcid": s.pmcid,
            "evidence_level": s.evidence_level,
            "citation_count": s.citation_count,
            "score": s.composite_score,
        }
        if s.abstract:
            entry["abstract"] = s.abstract[:500]
        studies_data.append(entry)

    search_summary = {}
    for r in bridge.search_results:
        search_summary[r.source] = {
            "hits": len(r.studies),
            "error": r.error,
            "skipped": r.skipped,
        }

    registry_trials = [
        {
            "rank": s.reference_number,
            "title": s.title,
            "nct_id": s.source_id,
            "status": s.trial_status,
            "phase": s.trial_phase,
            "has_published_results": s.has_published_results,
        }
        for s in bridge.ranked_studies
        if s.source == "clinicaltrials"
    ]

    data: dict[str, Any] = {
        "query": request.query,
        "query_type": request.query_type,
        "language": request.language,
        "plan": {
            "domain": plan.domain,
            "keywords": plan.keywords,
            "databases": plan.databases,
        },
        "search_summary": search_summary,
        "total_ranked": len(bridge.ranked_studies),
        "report_reference_numbers": [
            s.reference_number for s in report_studies if s.reference_number is not None
        ],
        "omitted_ranked": max(0, len(bridge.ranked_studies) - len(report_studies)),
        "studies": studies_data,
        "verification": {
            "verified_pmids": verification.verified_pmids,
            "missing_pmids": verification.missing_pmids,
            "notes": verification.notes,
        },
    }
    if bridge.screening:
        data["screening"] = bridge.screening
    if bridge.appraisal:
        data["appraisal"] = bridge.appraisal
    if registry_trials:
        data["registry_trials"] = registry_trials

    fulltext_excerpts: list[dict[str, Any]] = []
    for s in bridge.ranked_studies[:MAX_REPORT_STUDIES]:
        rank = s.reference_number
        if rank is None:
            continue
        stored = _stored_fulltext_for_rank(request, int(rank))
        if not stored:
            continue
        text, source = stored
        fulltext_excerpts.append({
            "rank": rank,
            "title": s.title,
            "source": source,
            "text_length": len(text),
            "excerpt": text[:FULLTEXT_SYNTHESIS_EXCERPT_CHARS],
        })
    if fulltext_excerpts:
        data["fulltext"] = {
            "available_ranks": [item["rank"] for item in fulltext_excerpts],
            "excerpts": fulltext_excerpts,
            "excerpt_chars_per_study": FULLTEXT_SYNTHESIS_EXCERPT_CHARS,
        }

    instructions = (
        "Write a comprehensive research synthesis report in markdown. "
        "Submit the report itself, not a completion/status message. "
        "For non-empty evidence, target 1,800-2,600 words when at least 10 studies are ranked, otherwise 1,200-2,000 words. "
        "The first non-empty line MUST be a level-1 markdown title beginning with '# '. "
        "The top-level section headings MUST be numbered exactly as: "
        "## 1. Executive Summary, ## 2. Background, ## 3. Methods, "
        "## 4. Results/Findings, ## 5. Discussion, ## 6. Conclusions, ## 7. References. "
        "The report MUST include: "
        "(1) An executive summary that directly answers the research question; "
        "(2) A methods section describing the search strategy"
        + (" and the number of studies screened out (itemized exclusions plus the bulk not_selected_count) with the dominant exclusion reasons" if bridge.screening else "")
        + "; "
        "(3) A findings section that synthesizes evidence across studies — do NOT just list studies, "
        "compare and contrast findings, identify patterns, agreements and contradictions; "
        "(4) A discussion section interpreting the evidence, noting limitations, gaps, and quality of evidence; "
        "(4b) State the GRADE certainty of evidence (High/Moderate/Low/Very Low) for each major finding using the appraisal data; "
        "(4c) Use available full-text excerpts to add specific detail for key studies; "
        "(4d) If appraisal was based on abstracts only, say so under Limitations and distinguish it from full-text-appraised findings; "
        "(5) A conclusion with clear takeaways; "
        "(6) A '## 7. References' section listing each cited study by [number]. "
        "IMPORTANT: the system finalizes the References section from verified bibliographic "
        "metadata after you submit — do NOT invent or guess authors, journal names, year, "
        "volume, issue, or page numbers. List references by their [number] using only the "
        "title and identifiers from the studies array; the system replaces them with the "
        "canonical citation. Never fabricate citation details not present in the studies array. "
        "Cite studies by [number] throughout the text. "
        "Use only rank values present in the studies array as citable reference numbers; "
        "do not cite numbers from screening exclusions, not_selected items, browse_studies output, "
        "or ranking rationale unless that same number appears in the studies array. "
        "If omitted_ranked is greater than 0, mention the omitted lower-priority count in Methods "
        "without citing omitted studies. "
        "In Results/Findings, present evidence levels from highest to lowest: Level I, Level II, Level III, Level IV, Level V. "
        "For PCC communication/SDM education topics, synthesize direct AI communication/SDM training evidence first, "
        "then adjacent virtual-patient/interview/empathy/breaking-bad-news evidence, then broader AI-health-professions education context. "
        "Number references sequentially as [1], [2], [3] with no gaps, and use only those same numbers in text citations. "
        "Write in the language specified by the query language setting."
    )
    if registry_trials:
        instructions += (
            " In the Discussion, compare the registered trials against the published evidence and explicitly "
            "flag any completed-but-unpublished trials (has_published_results = false) as potential publication bias."
        )
    data["instructions"] = instructions
    bridge._intermediate["synthesize_report"] = data
    return data


_REPORT_META_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bperfect[!.]",
        r"\bi have successfully completed\b",
        r"\bsuccessfully completed\b",
        r"\bcompleted (the )?(literature review|research task)\b",
        r"\bthe complete (markdown )?report (is )?(above|below)\b",
        r"\bfull report (is )?(above|below)\b",
        r"\bhere is (a|the) summary\b",
        r"완료했습니다",
        r"완료하였습니다",
    )
]

_REPORT_SECTION_GROUPS: dict[str, tuple[str, ...]] = {
    "executive_summary": (
        "executive summary",
        "summary",
        "요약",
        "핵심 요약",
    ),
    "background": (
        "background",
        "background & context",
        "background and context",
        "context",
        "배경",
    ),
    "methods": (
        "methods",
        "search strategy",
        "방법",
        "검색 전략",
    ),
    "results": (
        "results",
        "findings",
        "결과",
        "근거",
    ),
    "discussion": (
        "discussion",
        "논의",
        "고찰",
    ),
    "conclusions": (
        "conclusion",
        "conclusions",
        "결론",
    ),
    "references": (
        "references",
        "bibliography",
        "참고문헌",
        "참고 문헌",
    ),
}

_NUMBERED_REPORT_SECTIONS: tuple[tuple[int, str], ...] = (
    (1, "executive_summary"),
    (2, "background"),
    (3, "methods"),
    (4, "results"),
    (5, "discussion"),
    (6, "conclusions"),
    (7, "references"),
)


def _report_word_count(text: str) -> int:
    """Approximate report length across English and common CJK report text."""
    tokens = re.findall(
        r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?|[\uac00-\ud7af]+|[\u3040-\u30ff]+|[\u4e00-\u9fff]",
        text,
    )
    return len(tokens)


def _has_report_section(text_lower: str, aliases: tuple[str, ...]) -> bool:
    for alias in aliases:
        escaped = re.escape(alias.lower())
        if re.search(rf"(^|\n)\s*#+\s*(?:\d+[.)]?\s*)?{escaped}\b", text_lower):
            return True
        if re.search(rf"(^|\n)\s*(?:\d+[.)]\s*)?{escaped}\s*$", text_lower):
            return True
    return False


def _has_report_title(report_markdown: str) -> bool:
    for line in report_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith("# ") and not stripped.startswith("##")
    return False


def _has_numbered_report_section(report_markdown: str, number: int, aliases: tuple[str, ...]) -> bool:
    for line in report_markdown.splitlines():
        stripped = line.strip().lower()
        if not stripped:
            continue
        heading = re.sub(r"^#{1,6}\s*", "", stripped)
        match = re.match(rf"^{number}[.)]\s*(.+)$", heading)
        if not match:
            continue
        stripped = match.group(1).strip()
        if any(re.search(rf"^{re.escape(alias.lower())}\b", stripped) for alias in aliases):
            return True
    return False


def _numbered_report_section_issues(report_markdown: str) -> list[str]:
    missing = [
        f"{number}. {section.replace('_', ' ')}"
        for number, section in _NUMBERED_REPORT_SECTIONS
        if not _has_numbered_report_section(report_markdown, number, _REPORT_SECTION_GROUPS[section])
    ]
    if not missing:
        return []
    return [
        "Report must use numbered top-level sections: "
        + ", ".join(missing)
        + "."
    ]


def _heading_matches(line: str, aliases: tuple[str, ...]) -> bool:
    lowered = line.strip().lower()
    lowered = re.sub(r"^#{1,6}\s*", "", lowered)
    lowered = re.sub(r"^\d+[.)]\s*", "", lowered)
    return any(re.search(rf"^{re.escape(alias.lower())}\b", lowered) for alias in aliases)


def _extract_section(
    report_markdown: str,
    start_aliases: tuple[str, ...],
    end_aliases: tuple[str, ...],
) -> str:
    lines = report_markdown.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if _heading_matches(line, start_aliases):
            start_index = index + 1
            break
    if start_index is None:
        return ""
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if re.match(r"^\s*#{1,6}\s+", lines[index]) and _heading_matches(lines[index], end_aliases):
            end_index = index
            break
        if _heading_matches(lines[index], end_aliases):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]).strip()


def _extract_references_section(report_markdown: str) -> tuple[str, str]:
    start_aliases = _REPORT_SECTION_GROUPS["references"]
    lines = report_markdown.splitlines()
    for index, line in enumerate(lines):
        if _heading_matches(line, start_aliases):
            return "\n".join(lines[:index]).strip(), "\n".join(lines[index + 1:]).strip()
    return report_markdown, ""


def _inject_reference_list(report_markdown: str, studies: list[ScoredStudy]) -> str:
    """Replace the model-written References section with a deterministic one rendered from
    verified structured metadata, preserving the original heading style when present."""
    entries = render_reference_entries(studies)
    if not entries:
        return report_markdown
    lines = report_markdown.splitlines()
    references_aliases = _REPORT_SECTION_GROUPS["references"]
    for index, line in enumerate(lines):
        if _heading_matches(line, references_aliases):
            heading = line.rstrip()
            body = "\n".join(lines[:index]).rstrip()
            return f"{body}\n\n{heading}\n\n{entries}".strip()
    body = report_markdown.rstrip()
    return f"{body}\n\n## 7. References\n\n{entries}".strip()


def _reference_number_issues(report_markdown: str) -> list[str]:
    body, references = _extract_references_section(report_markdown)
    ref_numbers = [
        int(match.group(1))
        for match in re.finditer(r"(?m)^\s*(?:[-*]\s*)?\[(\d{1,3})\]\s+", references)
    ]
    if not ref_numbers:
        return ["References must be numbered as [1], [2], [3], etc."]

    issues: list[str] = []
    expected = list(range(1, len(ref_numbers) + 1))
    if ref_numbers != expected:
        issues.append("References must be ordered sequentially from [1] with no gaps.")

    ref_set = set(ref_numbers)
    citation_numbers = {int(match.group(1)) for match in re.finditer(r"\[(\d{1,3})\]", body)}
    missing = sorted(number for number in citation_numbers if number not in ref_set)
    if missing:
        issues.append(
            "Text citations reference missing bibliography entries: "
            + ", ".join(f"[{number}]" for number in missing)
            + "."
        )
    return issues


EVIDENCE_LEVEL_ORDER_ISSUE = (
    "Results/Findings must present evidence levels from Level I to Level V, "
    "not lower levels before higher levels."
)
GRADE_CERTAINTY_ISSUE = (
    "Report should state the GRADE certainty of evidence (High/Moderate/Low/Very Low) "
    "for major findings."
)
MAX_SUBMIT_REPORT_REJECTIONS = 3

_EVIDENCE_LEVEL_RE = re.compile(r"\bLevel\s+(IV|III|II|I|V)\b", re.IGNORECASE)
_EVIDENCE_LEVEL_ORDER = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
_CERTAINTY_RE = re.compile(r"certaint|grade|확실성", re.IGNORECASE)
# Soft issues let weak local models pass after the 3rd attempt (see soft-accept path).
_SOFT_REPORT_QUALITY_ISSUES = {EVIDENCE_LEVEL_ORDER_ISSUE, GRADE_CERTAINTY_ISSUE}


def _evidence_level_order_issues(report_markdown: str) -> list[str]:
    findings = _extract_section(
        report_markdown,
        _REPORT_SECTION_GROUPS["results"],
        (
            *_REPORT_SECTION_GROUPS["discussion"],
            *_REPORT_SECTION_GROUPS["conclusions"],
            *_REPORT_SECTION_GROUPS["references"],
            "limitations",
            "implications",
            "recommendations",
        ),
    )
    if not findings:
        return []

    ordered_levels: list[int] = []
    for line in findings.splitlines():
        if not re.match(r"^\s*#{1,6}\s+", line):
            continue
        match = _EVIDENCE_LEVEL_RE.search(line)
        if match:
            ordered_levels.append(_EVIDENCE_LEVEL_ORDER[match.group(1).upper()])
    if len(set(ordered_levels)) < 2:
        return []

    highest_seen = ordered_levels[0]
    for level in ordered_levels[1:]:
        if level < highest_seen:
            return [EVIDENCE_LEVEL_ORDER_ISSUE]
        highest_seen = max(highest_seen, level)
    return []


def _only_soft_report_quality_issues(issues: list[str]) -> bool:
    return bool(issues) and all(issue in _SOFT_REPORT_QUALITY_ISSUES for issue in issues)


def _record_submit_report_rejection(
    bridge: AgenticEventBridge,
    report_markdown: str,
    quality_issues: list[str],
) -> int:
    history = bridge._intermediate.setdefault("submit_report_rejection_history", [])
    if not isinstance(history, list):
        history = []
        bridge._intermediate["submit_report_rejection_history"] = history

    record = {
        "attempt": len(history) + 1,
        "report_length": len(report_markdown),
        "issues": list(quality_issues),
    }
    history.append(record)
    bridge._intermediate["submit_report_rejection_count"] = len(history)
    bridge._intermediate["rejected_report"] = report_markdown
    bridge._intermediate["rejected_report_issues"] = list(quality_issues)
    return len(history)


def report_quality_issues(report_markdown: str, ranked_count: int = 0, search_count: int = 0) -> list[str]:
    """Return quality issues that should make an agent rewrite its final report."""
    report_markdown = str(report_markdown).strip()
    if not report_markdown:
        return ["Report is empty."]

    issues: list[str] = []
    text_lower = report_markdown.lower()
    word_count = _report_word_count(report_markdown)
    has_evidence = ranked_count > 0 or search_count > 0
    min_words = 750 if ranked_count > 0 else 450 if search_count > 0 else 180

    if word_count < min_words:
        issues.append(f"Report is too short ({word_count} words; minimum {min_words}).")

    report_head = report_markdown[:600]
    for pattern in _REPORT_META_PATTERNS:
        if pattern.search(report_head):
            issues.append("Report appears to be a completion/status message rather than the report itself.")
            break

    if has_evidence:
        if not _has_report_title(report_markdown):
            issues.append("Report must start with a level-1 markdown title like '# <report title>'.")
        issues.extend(_numbered_report_section_issues(report_markdown))
        missing_sections = [
            section
            for section, aliases in _REPORT_SECTION_GROUPS.items()
            if not _has_report_section(text_lower, aliases)
        ]
        if missing_sections:
            issues.append("Report is missing required sections: " + ", ".join(missing_sections) + ".")

    if ranked_count > 0:
        if not re.search(r"\[\d+\]", report_markdown):
            issues.append("Report must cite searched studies with numbered citations like [1].")
        if not _has_report_section(text_lower, _REPORT_SECTION_GROUPS["references"]):
            issues.append("Report must include a References section.")
        else:
            issues.extend(_reference_number_issues(report_markdown))
        issues.extend(_evidence_level_order_issues(report_markdown))
        if not _CERTAINTY_RE.search(report_markdown):
            issues.append(GRADE_CERTAINTY_ISSUE)

    return issues


async def tool_submit_report(request: RunRequest, bridge: AgenticEventBridge, report_markdown: str) -> dict[str, Any]:
    """Store the agent-written final report."""
    report_markdown = str(report_markdown).strip()
    if not report_markdown:
        return {"error": "Report is empty. Write the full report and submit again."}

    # Finalize the bibliography deterministically: replace whatever the model wrote in its
    # References section with verified citations rendered from structured metadata (enriched
    # during synthesize_report). This makes fabricated/incomplete citations structurally
    # impossible — the model can no longer invent authors/journal/year/volume/issue/pages.
    # The model's original text is kept for rejection traces; the finalized text is what we
    # validate and store on acceptance.
    report_studies = bridge.ranked_studies[:MAX_REPORT_STUDIES]
    finalized_report = (
        _inject_reference_list(report_markdown, report_studies) if report_studies else report_markdown
    )

    quality_issues = report_quality_issues(
        finalized_report,
        ranked_count=len(bridge.ranked_studies),
        search_count=sum(len(result.studies) for result in bridge.search_results),
    )
    if quality_issues:
        rejection_count = _record_submit_report_rejection(bridge, report_markdown, quality_issues)
        if rejection_count >= MAX_SUBMIT_REPORT_REJECTIONS:
            if _only_soft_report_quality_issues(quality_issues):
                bridge._intermediate["submitted_report"] = finalized_report
                bridge._intermediate["submitted_report_warnings"] = list(quality_issues)
                bridge._intermediate["submitted_report_accepted_after_rejections"] = rejection_count
                bridge.set_result(finalized_report)
                return {
                    "status": "ok",
                    "length": len(finalized_report),
                    "warnings": quality_issues,
                    "accepted_after_rejections": rejection_count,
                }

            fallback_reason = (
                f"submit_report failed {rejection_count} times with blocking quality issues; "
                "running deterministic fallback."
            )
            bridge._intermediate["submit_report_fatal_rejection"] = {
                "rejection_count": rejection_count,
                "issues": list(quality_issues),
                "fallback_reason": fallback_reason,
            }
            return {
                "error": "Report quality gate failed repeatedly. Falling back instead of retrying indefinitely.",
                "issues": quality_issues,
                "rejection_count": rejection_count,
                "fatal": True,
                "fallback_reason": fallback_reason,
            }
        return {
            "error": "Report quality gate failed. Rewrite and submit the full report.",
            "issues": quality_issues,
            "rejection_count": rejection_count,
            "instructions": (
                "Submit the complete markdown report itself, not a status update. "
                "Use the required sections, synthesize the evidence, cite searched studies as [n], "
                "include numbered references in strict [1], [2], [3] order, and organize evidence levels from Level I to Level V."
            ),
        }
    bridge._intermediate["submitted_report"] = finalized_report
    bridge.set_result(finalized_report)
    return {"status": "ok", "length": len(finalized_report)}


async def tool_translate_report(
    request: RunRequest,
    bridge: AgenticEventBridge,
    report_markdown: str,
    target_language: str = "ko",
) -> dict[str, Any]:
    """Translate a report using the same LLM provider/model that ran the research."""
    import logging
    _log = logging.getLogger(__name__)

    report_markdown = str(report_markdown).strip()
    if not report_markdown:
        return {"error": "No report to translate."}

    translation_prompt = _build_translation_prompt(target_language)

    api_keys = request.api_keys
    provider = request.provider
    model = request.model

    try:
        _log.info("Calling LLM for translation: provider=%s model=%s", provider, model)
        translated = await _call_llm_for_translation(
            provider, model, api_keys, translation_prompt, report_markdown,
        )
        _log.info("Translation returned %d chars", len(translated))
        bridge._intermediate["submitted_report"] = translated
        bridge.set_result(translated)
        return {"status": "ok", "length": len(translated)}
    except Exception as exc:
        _log.warning("Translation failed: %s", exc, exc_info=True)
        return {"error": f"Translation failed: {exc}"}


def _build_translation_prompt(target_language: str) -> str:
    lang_name = {"ko": "Korean (한국어)", "ja": "Japanese (日本語)", "zh": "Chinese (中文)"}.get(
        target_language, target_language,
    )

    return f"""\
You are a medical research translator specializing in accurate, professional translation.
Translate the research report to {lang_name}.

## CRITICAL: Preserve in English
The following MUST remain in English without translation:
- Medical acronyms: PICO, PCC, MeSH, PMID, DOI, LVEF, HR, CI, RCT, OR, RR, NNT, NNH, eGFR, HbA1c, BMI
- Evidence levels: Level I, Level II, Level III, Level IV, Level V
- Author names (e.g., "Smith AB, Jones CD")
- Journal names (e.g., "New England Journal of Medicine", "JAMA", "Lancet")
- Database names: PubMed, Scopus, Cochrane, MEDLINE, OpenAlex, Semantic Scholar
- Statistical values and confidence intervals (e.g., "HR 0.87, 95% CI 0.73-1.04")
- P-values (e.g., "p < 0.001")
- Citation numbers: [1], [2], [3], etc.
- DOI and PMID identifiers
- Study names/acronyms (e.g., "EMPEROR-Preserved trial", "DAPA-HF")
- Drug/compound names when commonly used in English form

## Formatting Rules
- Maintain all markdown formatting exactly (headers, lists, bold, italics)
- Keep the same paragraph structure
- Preserve all line breaks and spacing
- Keep reference formatting intact in the References section

## Translation Style
- Use formal academic style
- Use appropriate medical terminology in the target language where standard terms exist
- Maintain scientific precision and objectivity
- Keep sentences clear and concise"""


async def _call_llm_for_translation(
    provider: str,
    model: str,
    api_keys: dict[str, str],
    system_prompt: str,
    report: str,
) -> str:
    """Call the LLM to translate the report."""
    import os

    if provider == "google":
        api_key = api_keys.get("google") or api_keys.get("gemini") or os.getenv("GOOGLE_API_KEY", "")
        from google import genai
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=f"{system_prompt}\n\nTranslate the following research report:\n\n{report}",
        )
        # response.text may raise ValueError on blocked content
        try:
            return response.text or ""
        except (ValueError, AttributeError):
            parts = getattr(response, "candidates", [])
            if parts:
                return str(parts[0])
            return ""

    if provider == "anthropic":
        api_key = api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY", "")
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Translate the following research report:\n\n{report}"}],
        )
        return response.content[0].text if response.content else ""

    if provider == "deepseek":
        api_key = deepseek_api_key(api_keys)
        from openai import AsyncOpenAI
        deepseek_client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        deepseek_resp = await deepseek_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Translate the following research report:\n\n{report}"},
            ],
            reasoning_effort=deepseek_reasoning_effort(),
            extra_body=deepseek_thinking_body(),
        )
        return deepseek_resp.choices[0].message.content or ""

    if provider == "openai":
        api_key = api_keys.get("openai") or os.getenv("OPENAI_API_KEY", "")
        from openai import AsyncOpenAI
        oai_client = AsyncOpenAI(api_key=api_key)
        oai_resp = await oai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Translate the following research report:\n\n{report}"},
            ],
        )
        return oai_resp.choices[0].message.content or ""

    # Local / fallback — use OpenAI-compatible endpoint
    from openai import AsyncOpenAI
    local_client = AsyncOpenAI(
        api_key=api_keys.get("local") or os.getenv("MDR_LOCAL_API_KEY", "local"),
        base_url=local_base_url(api_keys),
    )
    local_resp = await local_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate the following research report:\n\n{report}"},
        ],
    )
    return local_resp.choices[0].message.content or ""


async def tool_write_todos(request: RunRequest, bridge: AgenticEventBridge, items: list[str]) -> dict[str, Any]:
    items = [str(item) for item in items]
    await bridge.emit_todos(items)
    return {"status": "ok", "count": len(items)}


async def tool_update_progress(request: RunRequest, bridge: AgenticEventBridge, phase: str, message: str) -> dict[str, Any]:
    await bridge.emit_progress(phase, message)
    return {"status": "ok"}


_EBM_HIGH_EVIDENCE = {"Level I", "Level II"}


def _run_db_session(request: RunRequest):
    if not request.database_path:
        return None
    from sqlmodel import Session, create_engine

    engine = create_engine(
        f"sqlite:///{request.database_path}",
        connect_args={"check_same_thread": False},
    )
    return Session(engine)


def _fulltext_artifact_name(rank: int) -> str:
    return f"fulltext_study_{rank}"


def _stored_fulltext_for_rank(request: RunRequest, rank: int) -> tuple[str, str] | None:
    session = _run_db_session(request)
    if session is None:
        return None
    from sqlmodel import select

    try:
        artifact = session.exec(
            select(ResearchArtifact).where(
                ResearchArtifact.run_id == request.run_id,
                ResearchArtifact.artifact_type == ArtifactType.FULLTEXT_UPLOAD.value,
                ResearchArtifact.name == _fulltext_artifact_name(rank),
            ).order_by(ResearchArtifact.created_at.desc())
        ).first()
        if not artifact or not artifact.content_text:
            return None
        source = "user_upload"
        if artifact.content_json:
            try:
                payload = json.loads(artifact.content_json)
                if isinstance(payload, dict) and payload.get("source"):
                    source = str(payload["source"])
            except json.JSONDecodeError:
                pass
        return artifact.content_text, source
    finally:
        session.close()


def _manual_fulltext_for_rank(request: RunRequest, rank: int) -> str | None:
    stored = _stored_fulltext_for_rank(request, rank)
    return stored[0] if stored else None


def _manual_fulltext_uploaded_ranks(request: RunRequest, ranks: list[int]) -> list[int]:
    uploaded: list[int] = []
    for rank in ranks:
        stored = _stored_fulltext_for_rank(request, rank)
        if stored and stored[1] == "user_upload":
            uploaded.append(rank)
    return uploaded


def _store_fulltext_for_rank(
    request: RunRequest,
    rank: int,
    text: str,
    *,
    source: str,
    pdf_source: str | None = None,
    pdf_url: str | None = None,
) -> None:
    if not text:
        return
    session = _run_db_session(request)
    if session is None:
        return
    from sqlmodel import select

    metadata = {
        "source": source,
        "pdf_source": pdf_source,
        "pdf_url": pdf_url,
    }
    try:
        existing = session.exec(
            select(ResearchArtifact).where(
                ResearchArtifact.run_id == request.run_id,
                ResearchArtifact.artifact_type == ArtifactType.FULLTEXT_UPLOAD.value,
                ResearchArtifact.name == _fulltext_artifact_name(rank),
            ).order_by(ResearchArtifact.created_at.desc())
        ).first()
        if existing:
            existing.content_text = text
            existing.content_json = json.dumps(metadata, ensure_ascii=False)
        else:
            session.add(
                ResearchArtifact(
                    run_id=request.run_id,
                    artifact_type=ArtifactType.FULLTEXT_UPLOAD.value,
                    name=_fulltext_artifact_name(rank),
                    content_text=text,
                    content_json=json.dumps(metadata, ensure_ascii=False),
                )
            )
        session.commit()
    finally:
        session.close()


def _pdf_checkpoint_details(
    studies: list[ScoredStudy],
    *,
    missing_ranks: list[int],
    found_ranks: list[int],
) -> dict[str, Any]:
    wanted = set(missing_ranks)
    study_rows: list[dict[str, Any]] = []
    for study in studies:
        rank = study.reference_number
        if rank is None or (wanted and rank not in wanted):
            continue
        study_rows.append({
            "rank": rank,
            "title": study.title,
            "journal": study.journal,
            "year": study.publication_year,
            "doi": study.doi,
            "pmid": study.pmid,
            "pmcid": study.pmcid,
            "url": study.url,
            "evidence_level": study.evidence_level,
        })
    return {
        "type": "pdf_upload",
        "ranks": missing_ranks,
        "missing_ranks": missing_ranks,
        "found_pdf_ranks": found_ranks,
        "studies": study_rows,
    }


def _create_or_update_pdf_approval(
    request: RunRequest,
    studies: list[ScoredStudy],
    *,
    missing_ranks: list[int],
    found_ranks: list[int],
) -> str | None:
    session = _run_db_session(request)
    if session is None:
        return None
    from sqlmodel import select

    details = _pdf_checkpoint_details(studies, missing_ranks=missing_ranks, found_ranks=found_ranks)
    details_json = json.dumps(details)
    try:
        approvals = session.exec(
            select(ApprovalRequest).where(
                ApprovalRequest.run_id == request.run_id,
                ApprovalRequest.status == ApprovalStatus.PENDING.value,
            )
        ).all()
        for approval in approvals:
            try:
                existing = json.loads(approval.details_json or "{}")
            except json.JSONDecodeError:
                existing = {}
            if isinstance(existing, dict) and existing.get("type") == "pdf_upload":
                approval.summary = f"Upload PDFs for {len(missing_ranks)} ranked studies"
                approval.details_json = details_json
                session.add(approval)
                session.commit()
                return approval.id

        approval = ApprovalRequest(
            run_id=request.run_id,
            summary=f"Upload PDFs for {len(missing_ranks)} ranked studies",
            details_json=details_json,
            status=ApprovalStatus.PENDING.value,
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        return approval.id
    finally:
        session.close()


def _approval_status(request: RunRequest, approval_id: str) -> str | None:
    session = _run_db_session(request)
    if session is None:
        return None
    try:
        approval = session.get(ApprovalRequest, approval_id)
        return approval.status if approval else None
    finally:
        session.close()


def _run_status(request: RunRequest) -> str | None:
    session = _run_db_session(request)
    if session is None:
        return None
    try:
        run = session.get(ResearchRun, request.run_id)
        return run.status if run else None
    finally:
        session.close()


async def _download_pdf_bytes(rank: int, urls: list[str]) -> tuple[bytes | None, str]:
    import io
    import tarfile

    for url in urls:
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
                                _log.info("[PDF_DOWNLOAD] Extracted %d bytes from PMC tgz for rank %d", len(pdf_bytes), rank)
                                return pdf_bytes, "pmc_tgz"
                            break
            except Exception as exc:
                _log.info("[PDF_DOWNLOAD] PMC tgz failed for rank %d: %s", rank, exc)
        else:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=5.0),
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; MedicalDeepResearch/2.9.7; academic-research)"},
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if resp.content[:5] == b"%PDF-":
                        _log.info("[PDF_DOWNLOAD] Downloaded %d bytes via direct URL for rank %d", len(resp.content), rank)
                        return resp.content, "direct_url"
            except Exception as exc:
                _log.info("[PDF_DOWNLOAD] Direct URL failed for rank %d: %s", rank, exc)
    return None, "none"


async def _extract_pdf_text_from_bytes(rank: int, pdf_bytes: bytes, source: str) -> tuple[str, str | None]:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        pdf_path = f.name

    try:
        from .pdf_text import extract_pdf_text

        text = await asyncio.to_thread(extract_pdf_text, pdf_path)
        if text:
            _log.info("[PARSE_PDF] Parsed %d chars for rank %d (source=%s)", len(text), rank, source)
            return text, None
        return "", "No text extracted from PDF"
    except Exception as exc:
        _log.info("[PARSE_PDF] pdfminer failed for rank %d: %s", rank, exc)
        return "", str(exc)
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass


async def tool_fetch_fulltext(
    request: RunRequest,
    bridge: AgenticEventBridge,
    *,
    allow_user_checkpoint: bool = True,
) -> dict[str, Any]:
    ranked_candidates = [
        s for s in bridge.ranked_studies
        if s.reference_number is not None
    ]
    high_evidence_candidates = [
        s for s in bridge.ranked_studies
        if (
            s.evidence_level in _EBM_HIGH_EVIDENCE
            and s.reference_number is not None
        )
    ]
    candidate_pool: list[ScoredStudy] = []
    seen_candidate_ranks: set[int] = set()

    def _add_candidate(study: ScoredStudy) -> None:
        rank = study.reference_number
        if rank is None or int(rank) in seen_candidate_ranks:
            return
        seen_candidate_ranks.add(int(rank))
        candidate_pool.append(study)

    for s in ranked_candidates[:FULLTEXT_CANDIDATE_LIMIT]:
        _add_candidate(s)
    for s in high_evidence_candidates[:FULLTEXT_CANDIDATE_LIMIT]:
        _add_candidate(s)

    candidate_pool = candidate_pool[:FULLTEXT_CANDIDATE_LIMIT]
    relevance_scores_present = any(s.relevance_score > 0 for s in candidate_pool)
    candidates = [
        s for s in candidate_pool
        if not relevance_scores_present or s.relevance_score >= 0.35
    ][:10]
    if not candidates:
        candidates = candidate_pool[:10]
    if not candidates:
        return {"error": "No ranked studies available for full-text lookup or PDF upload."}

    auto_fetch_candidates = [
        s for s in candidates
        if s.doi or s.pmid or s.pmcid
    ]

    try:
        from unpywall.utils import UnpywallCredentials
        from unpywall import Unpywall
        UnpywallCredentials(POLITE_EMAIL)
        has_unpywall = True
    except ImportError:
        has_unpywall = False

    found_ranks: dict[int, dict[str, Any]] = {}
    manual_ranks: set[int] = set()
    unpywall_hits = 0
    pmc_hits = 0
    europe_pmc_xml_hits = 0

    for s in candidates:
        rank = s.reference_number
        stored = _stored_fulltext_for_rank(request, rank) if rank is not None else None
        if rank is not None and stored:
            if stored[1] == "user_upload":
                manual_ranks.add(rank)
            found_ranks[rank] = {
                "rank": rank,
                "title": s.title,
                "doi": s.doi,
                "pmid": s.pmid,
                "pmcid": s.pmcid,
                "evidence_level": s.evidence_level,
                "source": stored[1],
            }

    # Resolve PMIDs to PMCIDs once, up front, so both the Europe PMC XML pass
    # and the PMC OA pass can reuse it.
    pmid_to_pmcid: dict[str, str] = {}
    ids_param = ",".join(s.pmid for s in auto_fetch_candidates if s.pmid and s.reference_number is not None)
    if ids_param:
        try:
            records: list[dict[str, Any]] = []
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                for converter_url in PMC_ID_CONVERTER_URLS:
                    resp = await client.get(
                        converter_url,
                        params={
                            "ids": ids_param,
                            "format": "json",
                            "tool": "medical-deep-research",
                            "email": POLITE_EMAIL,
                        },
                    )
                    resp.raise_for_status()
                    records = resp.json().get("records", [])
                    if records:
                        break
            for r in records:
                pmid = str(r.get("pmid") or "").strip()
                pmcid = str(r.get("pmcid") or "").strip()
                if pmcid and pmid:
                    pmid_to_pmcid[pmid] = pmcid
        except Exception as exc:
            _log.info("[FULLTEXT] PMC ID converter failed: %s", exc)

    # Pass 0: Europe PMC full-text XML for OA articles (cleaner and more
    # reliable than the PDF chain). Hits skip the PDF pipeline entirely.
    xml_candidates = [
        s for s in auto_fetch_candidates
        if s.reference_number is not None
        and s.reference_number not in found_ranks
        and (s.pmcid or (s.pmid and pmid_to_pmcid.get(s.pmid)))
    ]
    if xml_candidates:
        sem_xml = asyncio.Semaphore(5)

        async def _xml_lookup(s: ScoredStudy) -> None:
            nonlocal europe_pmc_xml_hits
            rank = s.reference_number
            if rank is None:
                return
            pmcid = s.pmcid or (pmid_to_pmcid.get(s.pmid) if s.pmid else None)
            if not pmcid:
                return
            async with sem_xml:
                text = await fetch_europe_pmc_fulltext_xml(pmcid)
            if not text:
                return
            _store_fulltext_for_rank(request, rank, text, source="europe_pmc_xml")
            found_ranks[rank] = {
                "rank": rank, "title": s.title, "doi": s.doi, "pmid": s.pmid,
                "pmcid": pmcid, "evidence_level": s.evidence_level, "source": "europe_pmc_xml",
                "downloadable": True,
            }
            europe_pmc_xml_hits += 1

        await asyncio.gather(*[_xml_lookup(s) for s in xml_candidates])

    # Pass 1: Parallel Unpaywall (10 concurrent)
    if has_unpywall:
        sem = asyncio.Semaphore(10)

        async def _lookup(s: ScoredStudy) -> None:
            nonlocal unpywall_hits
            rank = s.reference_number
            if rank is None or not s.doi or rank in found_ranks:
                return
            async with sem:
                try:
                    pdf_link = await asyncio.to_thread(Unpywall.get_pdf_link, s.doi)
                    if pdf_link:
                        found_ranks[rank] = {
                            "rank": rank, "title": s.title, "doi": s.doi, "pmid": s.pmid, "pmcid": s.pmcid,
                            "evidence_level": s.evidence_level, "pdf_url": pdf_link, "source": "unpaywall",
                        }
                        unpywall_hits += 1
                except Exception:
                    pass

        await asyncio.gather(*[_lookup(s) for s in auto_fetch_candidates])

    # Pass 2: PMC for ALL candidates with PMIDs (PMC tgz downloads are more
    # reliable than Unpaywall URLs which often return 403 from publishers)
    remaining = [
        s for s in auto_fetch_candidates
        if s.reference_number is not None
        and (s.pmid or s.pmcid)
        and s.reference_number not in found_ranks
    ]
    if remaining:
        sem_pmc = asyncio.Semaphore(5)

        async def _pmc_lookup(s: ScoredStudy) -> None:
            nonlocal pmc_hits
            rank = s.reference_number
            if rank is None:
                return
            pmcid = s.pmcid or (pmid_to_pmcid.get(s.pmid) if s.pmid else None)
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
                            "rank": rank, "title": s.title, "doi": s.doi, "pmid": s.pmid,
                            "pmcid": pmcid, "evidence_level": s.evidence_level,
                            "pdf_url": tgz_href, "source": "pmc",
                        }
                        pmc_hits += 1
                except Exception as exc:
                    _log.info("[FULLTEXT] PMC OA failed for %s: %s", pmcid, exc)

        await asyncio.gather(*[_pmc_lookup(s) for s in remaining])

    # Build URL map: prefer PMC tgz over Unpaywall direct links.
    # Store list of URLs per rank so parse_pdf can try multiple.
    _url_map: dict[int, list[str]] = {}
    for r in found_ranks.values():
        if not r.get("pdf_url"):
            continue
        rank_id = r["rank"]
        url = r["pdf_url"]
        if rank_id not in _url_map:
            _url_map[rank_id] = []
        # PMC tgz goes first (most reliable)
        if url.endswith(".tar.gz"):
            _url_map[rank_id].insert(0, url)
        else:
            _url_map[rank_id].append(url)

    bridge._pdf_bytes = {}
    bridge._pdf_sources = {}
    download_failed_ranks: list[int] = []
    parse_failed_ranks: list[int] = []
    if _url_map:
        sem_download = asyncio.Semaphore(4)

        async def _validate_pdf(rank: int, urls: list[str]) -> None:
            async with sem_download:
                pdf_bytes, source = await _download_pdf_bytes(rank, urls)
            if not pdf_bytes:
                download_failed_ranks.append(rank)
                return
            text, parse_error = await _extract_pdf_text_from_bytes(rank, pdf_bytes, source)
            if not text:
                parse_failed_ranks.append(rank)
                _log.info("[FULLTEXT] Downloaded PDF for rank %d but parse validation failed: %s", rank, parse_error)
                return
            bridge._pdf_bytes[rank] = pdf_bytes
            bridge._pdf_sources[rank] = source
            _store_fulltext_for_rank(
                request,
                rank,
                text,
                source="downloaded_pdf",
                pdf_source=source,
                pdf_url=urls[0] if urls else None,
            )

        await asyncio.gather(*[_validate_pdf(rank, urls) for rank, urls in _url_map.items()])

    downloadable_url_map = {rank: urls for rank, urls in _url_map.items() if rank in bridge._pdf_bytes}
    bridge._pdf_urls = {k: v[0] for k, v in downloadable_url_map.items()}
    bridge._pdf_url_alternatives = downloadable_url_map
    for rank in list(found_ranks):
        row = found_ranks[rank]
        if row.get("pdf_url") and rank not in bridge._pdf_bytes:
            found_ranks.pop(rank)
        elif row.get("pdf_url"):
            row["downloadable"] = True
            row["download_source"] = bridge._pdf_sources.get(rank)

    available = sorted(found_ranks.values(), key=lambda r: r["rank"])
    candidate_ranks = [int(s.reference_number) for s in candidates if s.reference_number is not None]
    found_rank_ids = {int(r["rank"]) for r in available}
    missing_pdf_ranks = [rank for rank in candidate_ranks if rank not in found_rank_ids]
    _log.info(
        "[FULLTEXT] %d full texts found (europe_pmc_xml=%d, unpywall=%d, pmc=%d, failed_download=%d, failed_parse=%d) from %d candidate studies (%d auto-fetchable)",
        len(available), europe_pmc_xml_hits, unpywall_hits, pmc_hits, len(download_failed_ranks), len(parse_failed_ranks), len(candidates), len(auto_fetch_candidates),
    )
    result = {
        "level_I_II_studies": len(high_evidence_candidates),
        "candidate_studies": len(candidates),
        "high_evidence_candidate_studies": len(high_evidence_candidates),
        "auto_fetchable_studies": len(auto_fetch_candidates),
        "pdfs_found": len(available),
        "discovered_pdf_ranks": sorted(_url_map),
        "validated_pdf_ranks": sorted(bridge._pdf_bytes),
        "download_failed_ranks": sorted(download_failed_ranks),
        "parse_failed_ranks": sorted(parse_failed_ranks),
        "europe_pmc_xml_hits": europe_pmc_xml_hits,
        "unpywall_hits": unpywall_hits,
        "pmc_hits": pmc_hits,
        "user_upload_hits": len(manual_ranks),
        "available": available,
        "missing_pdf_ranks": missing_pdf_ranks,
        "manual_upload_needed": bool(missing_pdf_ranks),
    }
    if not allow_user_checkpoint or not missing_pdf_ranks:
        return result

    requested_upload_ranks = list(missing_pdf_ranks)
    await bridge.on_tool_start(
        "await_user_pdfs",
        {"ranks": requested_upload_ranks, "reason": "missing_pdfs_after_fetch_fulltext"},
    )
    checkpoint = await tool_await_user_pdfs(request, bridge, requested_upload_ranks)
    await bridge.on_tool_end("await_user_pdfs", checkpoint)
    bridge._intermediate["await_user_pdfs"] = checkpoint

    uploaded_after = set(_manual_fulltext_uploaded_ranks(request, candidate_ranks))
    for s in candidates:
        rank = s.reference_number
        if rank is None or not _stored_fulltext_for_rank(request, rank):
            continue
        stored = _stored_fulltext_for_rank(request, rank)
        found_ranks[rank] = {
            "rank": rank,
            "title": s.title,
            "doi": s.doi,
            "pmid": s.pmid,
            "pmcid": s.pmcid,
            "evidence_level": s.evidence_level,
            "source": stored[1] if stored else "user_upload",
        }

    available_after = sorted(found_ranks.values(), key=lambda r: r["rank"])
    found_after_ids = {int(r["rank"]) for r in available_after}
    unavailable_pdf_ranks = [rank for rank in candidate_ranks if rank not in found_after_ids]
    result.update({
        "pdfs_found": len(available_after),
        "user_upload_hits": len(uploaded_after),
        "available": available_after,
        "requested_upload_ranks": requested_upload_ranks,
        "missing_pdf_ranks": [],
        "unavailable_pdf_ranks": unavailable_pdf_ranks,
        "manual_upload_needed": False,
        "user_pdf_checkpoint": checkpoint,
    })
    return result


async def tool_await_user_pdfs(
    request: RunRequest,
    bridge: AgenticEventBridge,
    ranks: list[int] | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Pause the agent while the UI lets the user upload PDFs for missing ranks."""
    ranked_by_ref = {
        int(s.reference_number): s
        for s in bridge.ranked_studies
        if s.reference_number is not None
    }
    requested_ranks = [int(rank) for rank in (ranks or []) if int(rank) in ranked_by_ref]
    if not requested_ranks:
        fetch_result = bridge._intermediate.get("fetch_fulltext")
        if isinstance(fetch_result, dict):
            requested_ranks = [
                int(rank)
                for rank in fetch_result.get("missing_pdf_ranks", [])
                if int(rank) in ranked_by_ref
            ]
    if not requested_ranks:
        requested_ranks = [
            int(s.reference_number)
            for s in bridge.ranked_studies
            if s.reference_number is not None and s.evidence_level in _EBM_HIGH_EVIDENCE
        ][:5]
    requested_ranks = list(dict.fromkeys(requested_ranks))
    if not requested_ranks:
        return {"status": "skipped", "reason": "No ranked studies are waiting for user PDFs."}

    uploaded_before = _manual_fulltext_uploaded_ranks(request, requested_ranks)
    missing = [rank for rank in requested_ranks if rank not in uploaded_before]
    if not missing:
        return {
            "status": "ok",
            "uploaded_ranks": uploaded_before,
            "missing_ranks": [],
            "continued": True,
        }

    found_ranks = sorted(set(getattr(bridge, "_pdf_urls", {}).keys()))
    approval_id = _create_or_update_pdf_approval(
        request,
        bridge.ranked_studies,
        missing_ranks=missing,
        found_ranks=found_ranks,
    )
    await bridge.queue.put(
        RuntimeEventPayload(
            event_type=EventType.APPROVAL_REQUESTED,
            phase=bridge.progress.enter("fulltext")[0],
            progress=bridge.progress.advance(),
            message=f"Waiting for user PDFs for {len(missing)} studies",
            tool_name="await_user_pdfs",
            extra={
                "type": "pdf_upload",
                "approval_id": approval_id,
                "missing_pdf_ranks": missing,
                "found_pdf_ranks": found_ranks,
            },
        )
    )
    if not approval_id:
        return {
            "status": "unavailable",
            "reason": "No run database path was available for a PDF checkpoint.",
            "uploaded_ranks": uploaded_before,
            "missing_ranks": missing,
        }

    status: str | None = ApprovalStatus.PENDING.value
    while status == ApprovalStatus.PENDING.value:
        await asyncio.sleep(1.0)
        status = _approval_status(request, approval_id)
        if status is None:
            return {
                "status": "unavailable",
                "approval_id": approval_id,
                "reason": "The PDF checkpoint could not be found.",
                "uploaded_ranks": _manual_fulltext_uploaded_ranks(request, requested_ranks),
                "missing_ranks": requested_ranks,
                "continued": False,
            }
        run_status = _run_status(request)
        if run_status in _TERMINAL_RUN_STATUSES:
            uploaded_now = _manual_fulltext_uploaded_ranks(request, requested_ranks)
            return {
                "status": "cancelled" if run_status in {ResearchStatus.CANCELLED.value, ResearchStatus.INTERRUPTED.value} else "stale",
                "approval_id": approval_id,
                "run_status": run_status,
                "uploaded_ranks": uploaded_now,
                "missing_ranks": [rank for rank in requested_ranks if rank not in uploaded_now],
                "continued": False,
            }

    uploaded_after = _manual_fulltext_uploaded_ranks(request, requested_ranks)
    missing_after = [rank for rank in requested_ranks if rank not in uploaded_after]
    if status == ApprovalStatus.REJECTED.value:
        return {
            "status": "skipped",
            "approval_id": approval_id,
            "uploaded_ranks": uploaded_after,
            "missing_ranks": missing_after,
            "continued": False,
        }
    if status == ApprovalStatus.APPROVED.value:
        return {
            "status": "ok",
            "approval_id": approval_id,
            "uploaded_ranks": uploaded_after,
            "missing_ranks": missing_after,
            "continued": True,
        }
    return {
        "status": "unavailable",
        "approval_id": approval_id,
        "uploaded_ranks": uploaded_after,
        "missing_ranks": missing_after,
        "continued": False,
    }


async def tool_parse_pdf(
    request: RunRequest,
    bridge: AgenticEventBridge,
    rank: int,
    *,
    allow_user_checkpoint: bool = True,
) -> dict[str, Any]:
    study = next((s for s in bridge.ranked_studies if s.reference_number == rank), None)
    title = study.title if study else f"Study #{rank}"
    stored_fulltext = _stored_fulltext_for_rank(request, rank)
    if stored_fulltext:
        text, stored_source = stored_fulltext
        return {
            "rank": rank,
            "title": title,
            "source": stored_source,
            "text_length": len(text),
            "fulltext": text,
        }

    cached_pdf = getattr(bridge, "_pdf_bytes", {}).get(rank)
    pdf_bytes: bytes | None = cached_pdf
    source = getattr(bridge, "_pdf_sources", {}).get(rank, "validated_pdf") if cached_pdf else "none"

    urls = getattr(bridge, "_pdf_url_alternatives", {}).get(rank, [])
    if not urls:
        primary = bridge._pdf_urls.get(rank, "")
        if primary:
            urls = [primary]

    if not pdf_bytes and urls:
        pdf_bytes, source = await _download_pdf_bytes(rank, urls)

    checkpoint: dict[str, Any] | None = None
    if not pdf_bytes and allow_user_checkpoint:
        previous_checkpoint = bridge._intermediate.get("await_user_pdfs")
        already_requested = (
            isinstance(previous_checkpoint, dict)
            and rank in {int(r) for r in previous_checkpoint.get("missing_ranks", []) if str(r).isdigit()}
            and previous_checkpoint.get("status") in {"ok", "skipped", "cancelled", "stale"}
        )
        if not already_requested:
            await bridge.on_tool_start(
                "await_user_pdfs",
                {"ranks": [rank], "reason": "discovered_pdf_download_failed"},
            )
            checkpoint = await tool_await_user_pdfs(request, bridge, [rank])
            await bridge.on_tool_end("await_user_pdfs", checkpoint)
            bridge._intermediate["await_user_pdfs"] = checkpoint
            stored_fulltext = _stored_fulltext_for_rank(request, rank)
            if stored_fulltext:
                text, stored_source = stored_fulltext
                return {
                    "rank": rank,
                    "title": title,
                    "source": stored_source,
                    "text_length": len(text),
                    "fulltext": text,
                    "pdf_checkpoint": checkpoint,
                }

    if not pdf_bytes:
        error_result: dict[str, Any] = {
            "rank": rank,
            "error": f"Could not download PDF for rank {rank}",
            "title": title,
        }
        if checkpoint:
            error_result["pdf_checkpoint"] = checkpoint
        return error_result

    text, parse_error = await _extract_pdf_text_from_bytes(rank, pdf_bytes, source)
    if text:
        _store_fulltext_for_rank(
            request,
            rank,
            text,
            source="downloaded_pdf",
            pdf_source=source,
            pdf_url=urls[0] if urls else None,
        )
        return {"rank": rank, "title": title, "source": source, "text_length": len(text), "fulltext": text}

    if allow_user_checkpoint:
        await bridge.on_tool_start(
            "await_user_pdfs",
            {"ranks": [rank], "reason": "downloaded_pdf_parse_failed"},
        )
        checkpoint = await tool_await_user_pdfs(request, bridge, [rank])
        await bridge.on_tool_end("await_user_pdfs", checkpoint)
        bridge._intermediate["await_user_pdfs"] = checkpoint
        stored_fulltext = _stored_fulltext_for_rank(request, rank)
        if stored_fulltext:
            text, stored_source = stored_fulltext
            return {
                "rank": rank,
                "title": title,
                "source": stored_source,
                "text_length": len(text),
                "fulltext": text,
                "pdf_checkpoint": checkpoint,
            }

    error_result = {
        "rank": rank,
        "error": f"Could not parse PDF for rank {rank}",
        "title": title,
        "parse_error": parse_error,
    }
    if checkpoint:
        error_result["pdf_checkpoint"] = checkpoint
    return error_result


# ---------------------------------------------------------------------------
# Shared system prompt
# ---------------------------------------------------------------------------

def agentic_system_prompt(request: RunRequest, provider_name: str = "Research Agent") -> str:
    offline_note = (
        "\n\nOFFLINE MODE IS ENABLED. All search tools will return empty/mock results. "
        "Acknowledge this limitation in your report."
        if request.offline_mode else ""
    )
    # Choose domain-specific prompt based on query plan
    from .research import build_query_plan
    plan = build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
    is_clinical = plan.domain == "clinical"

    if is_clinical:
        domain_instructions = _clinical_prompt(request)
    else:
        domain_instructions = _healthcare_prompt(request)

    return f"""\
{domain_instructions}

## Tools

**Planning**: plan_search, suggest_databases, write_todos, update_progress
**Search** (one call each): search_pubmed, search_pmc, search_europe_pmc, search_openalex, search_crossref, search_cochrane, search_semantic_scholar, search_scopus{", search_clinical_trials" if is_clinical else ""}, search_preprints
**Snowballing** (citation-graph traversal on ranked studies):
- get_references(reference_number) — fetch the reference list of a ranked study [n] (backward)
- get_citations(reference_number) — fetch papers citing a ranked study [n] (forward)
**Evidence** (reads from shared state — NO large JSON arguments needed):
- get_studies(context) — deduplicates and pre-scores all collected studies, returns a pre-ranked TOP TIER grouped by evidence level I->V for YOUR review
- browse_studies(page, evidence_level, source) — page/expand the scored pool for more candidates by level or source; does NOT re-rank or reset screening
- screen_studies(included_indices, excluded_indices, exclusion_reasons) — whitelist: ONLY included_indices survive, every other study is dropped (unlisted ones recorded as "not selected"). Pass excluded_indices (+ reasons) only to name notable exclusions in Methods
- finalize_ranking(ranked_indices, rationale) — submit your ranking. Pass indices best-first.
- appraise_evidence(findings, certainties, rationales, reference_numbers_csv) — record GRADE certainty per major finding
- verify_studies() — verifies PMIDs of ranked studies
- synthesize_report() — returns structured evidence data for you to write the final report
- submit_report(report_markdown) — submit your completed report. MUST be called as the final step.
**Fulltext** (call AFTER finalize_ranking):
- fetch_fulltext() — Europe PMC full-text + Unpaywall + PubMed Central for free full text across ALL ranked studies
- await_user_pdfs(ranks) — pauses until the user clicks Continue or Skip after uploading PDFs
- parse_pdf(rank) — parses a user-uploaded PDF first, otherwise downloads and parses the discovered PDF

## Workflow (follow exactly)

1. Call `plan_search` with the query.
2. Call search tools (one per database, use queries from the plan). Search 3-5 databases{" — include search_clinical_trials for registered/ongoing trials" if is_clinical else ""}.
3. Call `get_studies` with context="{"clinical" if is_clinical else "general"}". \
It returns a pre-ranked TOP TIER grouped by evidence level I->V (with facet counts and total). \
Carefully review EVERY abstract shown. If `has_more` is true and you need wider coverage before screening, call `browse_studies(page=2)` or filter with `browse_studies(evidence_level=...)` / `browse_studies(source=...)`. Assess relevance to the query, study design, evidence level, and quality.
4. Call `screen_studies`: pass `included_indices` with EVERY index you want to keep — every study you do not include is automatically dropped (recorded as "not selected"). Optionally add `excluded_indices` (+ one reason each — e.g. population mismatch, wrong intervention/comparator, wrong study type, off-topic) to name the notable exclusions in Methods.
5. Call `finalize_ranking` with your ordered list of included study indices (best first) and a detailed rationale.
6. (Optional) If 2+ Level I/II studies were ranked and coverage is thin, call `get_references` and/or `get_citations` for the top 1-2 of them (at most 3 snowball calls total), then call `get_studies` and `screen_studies` again to merge and re-screen the new candidates.
7. Call `fetch_fulltext` to find free full text across all ranked studies. This tool opens the user PDF upload checkpoint itself when publisher PDFs are missing; wait for it to return before continuing.
8. Call `parse_pdf` for up to 6-10 key studies that have full text available or were uploaded by the user — prioritize direct evidence, high-evidence reviews/trials, and articles central to the conclusion.
9. Call `appraise_evidence`: for each major finding state a GRADE certainty (High/Moderate/Low/Very Low) with a short rationale and the supporting reference numbers. {"Start High for findings from RCTs/meta-analyses and Low for observational studies; rate down for risk of bias, imprecision, indirectness, or inconsistency." if is_clinical else "Describe the strength and limitations of the evidence base; formal GRADE is optional for non-clinical questions."}
10. Call `verify_studies` to validate PMIDs.
11. Call `synthesize_report` — this returns the structured evidence data.
12. **Write the full report** using the evidence data (see Report Format below).
13. Call `submit_report(report_markdown)` with your complete report. This is the FINAL step.

Do NOT pass study data as arguments — tools read from shared state.
Do NOT repeat searches. One call per database, then move forward.

## Search Discipline

- Use at most 3-5 query variants for a source; add variants when a source returned few relevant hits.
- NEVER fabricate PMIDs, DOIs, or NCT IDs — cite only identifiers that appear in tool results.
- Verify the spelling of uncommon medical terms (drug names, eponymous syndromes) before searching; prefer the standard term over an abbreviation on the first search.
- Search broadly: request up to 20-25 results per source for primary databases (the tools cap at 25). You review a pre-ranked tier from `get_studies` and can page the full pool with `browse_studies`, so cast a wide net first.
- Only call `search_preprints` when peer-reviewed evidence is sparse or the topic is very recent, and always label preprint findings as not peer reviewed.

## Report Quality Requirements (CRITICAL)

- The submitted report must be the report itself, not a completion note or summary of what you did.
- If any studies are ranked, write a comprehensive 1,800-2,600 word report when at least 10 studies are ranked, otherwise 1,200-2,000 words unless the evidence base is genuinely empty.
- Start with a level-1 markdown title (`# ...`).
- Use these numbered markdown sections exactly: `## 1. Executive Summary`, `## 2. Background`, `## 3. Methods`, `## 4. Results/Findings`, `## 5. Discussion`, `## 6. Conclusions`, `## 7. References`.
- Synthesize across studies; compare findings, study designs, populations, agreement, contradictions, and evidence quality.
- Cite only searched studies as [1], [2], etc. Do not cite unsearched sources.
- In Results/Findings, order evidence levels from Level I to Level V. Never put Level IV/V evidence before Level I/II evidence.
- State the GRADE certainty of evidence (High/Moderate/Low/Very Low) for each major finding, using your `appraise_evidence` judgments.
- In Methods, note how many studies were screened out and the dominant exclusion reasons. If your appraisal was based on abstracts only (no full text), say so under Limitations.
- Number References sequentially as [1], [2], [3] with no gaps. In-text citations must use only those reference numbers.
- Never write phrases like "the full report is above/below" or "I have completed the report" in `submit_report`.

## Anti-Hallucination Rules (CRITICAL)

- ONLY cite sources from your search results. NEVER invent PMIDs, DOIs, or findings.
- ONLY state what abstracts EXPLICITLY say.
- If a conclusion says "no significant difference", report that — NEVER reverse or contradict findings.
- If findings are mixed or inconclusive, report that accurately.
- Cite studies as [1], [2], etc. throughout the text and keep citation numbers synchronized with the References section.

## Query

- **Query**: {request.query}
- **Type**: {request.query_type}
- **Language**: {request.language}{offline_note}
"""


def _clinical_prompt(request: RunRequest) -> str:
    return f"""\
You are a Medical Research Agent ({request.provider}) specialized in evidence-based medicine \
and systematic literature review.

## Core Capabilities
1. Build optimized search queries using PICO or PCC frameworks
2. Search medical databases (PubMed, PMC, Europe PMC, Crossref, Scopus, Cochrane Library, OpenAlex, Semantic Scholar)
3. Classify evidence levels (Level I–V)
4. Validate study populations against target criteria
5. Synthesize findings into comprehensive evidence-based reports

## Search Strategy Guidelines

### For Clinical Questions (PICO)
- Use "comprehensive" search strategy to prioritize recent landmark trials
- Ensure recent RCTs (last 3 years) from NEJM, Lancet, JAMA are included
- Validate that study populations match the query criteria

### Database Coverage
Search multiple databases for comprehensive coverage:
- PubMed (primary for clinical evidence)
- PMC and Europe PMC (published open-access biomedical articles)
- Cochrane (systematic reviews)
- Crossref (published journal article metadata)
- OpenAlex (broad academic coverage, free)
- Semantic Scholar (Medicine-filtered, free)
- Scopus (if API key available — citation counts)
- ClinicalTrials.gov (registered/ongoing trials; flags whether results were posted)

## Evidence Classification

Assign evidence levels to each study:
- **Level I**: Systematic reviews, meta-analyses of RCTs
- **Level II**: Individual RCTs, well-designed controlled trials
- **Level III**: Non-randomized controlled studies, cohort studies
- **Level IV**: Case series, case-control studies
- **Level V**: Expert opinion, narrative reviews, case reports

## Evidence Appraisal (GRADE)

Rate the certainty of evidence for each major finding/outcome, not just the study type:
- Start **High** for findings based on RCTs or meta-analyses of RCTs; start **Low** for findings based on observational studies.
- Rate DOWN for: risk of bias, inconsistency across studies, indirectness (population/intervention/outcome mismatch), and imprecision (wide confidence intervals, few events).
- Report the resulting certainty as **High / Moderate / Low / Very Low** with a one-line rationale.
- When you judged a finding from the abstract only (no full text retrieved), say so — abstracts limit risk-of-bias appraisal.

## Report Format (Markdown) — YOU MUST WRITE THIS

Your final submitted report MUST be the complete research report itself, not a status update. \
For non-empty evidence, write 1,800-2,600 words when at least 10 studies are ranked, otherwise 1,200-2,000 words. Start with a level-1 markdown title, then include these numbered top-level sections exactly:

## 1. Executive Summary
Directly answer the clinical question in 2-3 paragraphs. Highlight the key finding and \
cite the landmark trial. State the strength of evidence and bottom-line conclusion.

## 2. Background
Why this question matters clinically. What is the current state of knowledge.

## 3. Methods
Search strategy, databases searched with hit counts, population criteria, inclusion/exclusion reasoning.

## 4. Results/Findings
Organize by evidence level, with [n] citations throughout:
- Level I evidence (systematic reviews, meta-analyses)
- Level II evidence (RCTs)
- Level III–V evidence
- Compare and contrast findings across studies
- Note agreements, contradictions, and effect sizes
- State the GRADE certainty (High/Moderate/Low/Very Low) for each major finding
Do not present Level IV/V evidence before Level I/II evidence.

## 5. Discussion
- Address population-specific considerations
- Clinical implications and applicability
- Limitations of the available evidence (including whether appraisal was abstract-only)
- Compare registered trials (ClinicalTrials.gov) against the published evidence; explicitly flag completed-but-unpublished trials as potential publication bias
- Note how many studies were screened out and why
- Gaps in the literature

## 6. Conclusions
Clear clinical takeaways. What the evidence supports, what remains uncertain.

## 7. References
Vancouver format with PMIDs/DOIs: [n] Authors. Title. Journal. Year;Vol(Issue):Pages. DOI/PMID.
Number references sequentially from [1] with no gaps, and do not cite numbers that are absent here.

Write in {request.language} language. If you write the prose in a non-English language, keep numbered \
citations [n], PMID, DOI, journal names, and reference formatting intact."""


def _healthcare_prompt(request: RunRequest) -> str:
    return f"""\
You are a Healthcare Research Agent ({request.provider}) specialized in comprehensive academic \
literature review across healthcare disciplines including ethics, policy, informatics, social care, \
nursing, public health, education, and implementation science.

## Core Capabilities
1. Build keyword-based search strategies for broad healthcare/academic topics
2. Search academic databases (PubMed, PMC, Europe PMC, Crossref, OpenAlex, Semantic Scholar, Scopus)
3. Identify and include diverse study methodologies (qualitative, mixed methods, policy analyses, \
theoretical frameworks, reviews)
4. Synthesize findings into thematic reports

## Search Strategy Guidelines

### For Healthcare/Academic Research Topics
- Build keyword-based search queries using natural language terms
- Do NOT use PICO or PCC frameworks for non-clinical topics
- Do NOT attempt MeSH term mapping for broad healthcare topics
- Prioritize OpenAlex and Semantic Scholar for cross-disciplinary coverage
- Use PubMed for healthcare topics it indexes well
- Skip Cochrane for non-clinical-intervention topics
- Skip ClinicalTrials.gov — the trial registry is for clinical-intervention questions only

## Screening & Appraisal
- Still call `screen_studies` to select the studies to keep: pass `included_indices` for everything in scope (unlisted studies are dropped); add `excluded_indices` + reasons for notable off-topic exclusions.
- For `appraise_evidence`, describe the strength and limitations of the evidence base (methodological diversity, transferability, saturation). Formal GRADE certainty is optional for non-clinical questions — use it only where an intervention's effect is being judged.

### Database Coverage
Search multiple databases for comprehensive coverage:
- OpenAlex (primary for broad academic coverage, free)
- Crossref (published journal article metadata)
- Europe PMC / PMC (biomedical open-access and indexed literature)
- Semantic Scholar (cross-disciplinary without field restrictions, free)
- PubMed (for healthcare topics it indexes: nursing, bioethics, public health)
- Scopus (if API key available — citation counts and broader coverage)

## Report Format (Markdown) — YOU MUST WRITE THIS

Your final submitted report MUST be the complete research report itself, not a status update. \
For non-empty evidence, write 1,800-2,600 words when at least 10 studies are ranked, otherwise 1,200-2,000 words. Start with a level-1 markdown title, then include these numbered top-level sections exactly:

## 1. Executive Summary
Directly answer the research question in 2-3 paragraphs. Summarize the state of knowledge, \
the strength of the evidence base, and the key takeaway.

## 2. Background
Why this topic matters. The current landscape and knowledge gaps.

## 3. Methods
Search strategy: databases searched, query terms used, hit counts per source, \
inclusion/exclusion reasoning.

## 4. Results/Findings
Organize thematically — do NOT just list studies one by one. Instead:
- Group related findings by theme, approach, or outcome
- Compare and contrast what different studies found
- Consider diverse study types (qualitative, quantitative, mixed methods) as equally valid
- Note where the literature agrees, disagrees, or shows gaps
- Cite sources as [n] throughout

## 5. Discussion
Interpret what these findings mean for practitioners, educators, or policymakers, including limitations and gaps.

## 6. Conclusions
Clear takeaways and future directions.

## 7. References
Vancouver format with DOIs: [n] Authors. Title. Journal. Year;Vol(Issue):Pages. DOI.
Number references sequentially from [1] with no gaps, and do not cite numbers that are absent here.

Write in {request.language} language. If you write the prose in a non-English language, keep numbered \
citations [n], DOI, journal names, and reference formatting intact."""


# ---------------------------------------------------------------------------
# Shared recovery
# ---------------------------------------------------------------------------

def recover_report_from_bridge(request: RunRequest, bridge: AgenticEventBridge, runtime_name: str = "Agentic Runtime") -> str:
    """Build a report from whatever the agent produced via shared state.

    Priority: accepted submitted_report > fallback template.
    """
    # Check if agent called submit_report
    submitted = bridge._intermediate.get("submitted_report")
    if isinstance(submitted, str) and submitted.strip():
        return submitted.strip()

    # Fallback to deterministic template only as last resort
    plan = bridge.plan or build_query_plan(request.query, request.query_type, request.provider, request.query_payload)
    verification = bridge.verification or empty_verification_summary(
        "Verification was incomplete due to agent timeout or error."
    )
    return render_report(
        query=request.query, plan=plan,
        search_results=bridge.search_results,
        ranked_studies=bridge.ranked_studies,
        verification=verification,
        provider=request.provider,
        runtime_name=f"{runtime_name} (fallback)",
    )


# ---------------------------------------------------------------------------
# Tool descriptions (shared across all providers)
# ---------------------------------------------------------------------------

TOOL_DESCRIPTIONS: dict[str, str] = {
    "plan_search": "Build a search plan. Returns keywords, databases, and source queries.",
    "suggest_databases": "Suggest database coverage for a research query.",
    "search_pubmed": "Search PubMed for medical literature.",
    "search_pmc": "Search PubMed Central for published open-access biomedical articles.",
    "search_europe_pmc": "Search Europe PMC for published biomedical literature.",
    "search_openalex": "Search OpenAlex for open-access academic papers.",
    "search_crossref": "Search Crossref for published journal article metadata.",
    "search_cochrane": "Search Cochrane for systematic reviews.",
    "search_semantic_scholar": "Search Semantic Scholar for academic papers.",
    "search_scopus": "Search Scopus for academic citations.",
    "search_clinical_trials": "Search the ClinicalTrials.gov registry (API v2). Returns trials with status/phase and whether results were posted — use for ongoing trials and publication-bias awareness.",
    "search_preprints": "Search preprint servers (medRxiv/bioRxiv) via Europe PMC. Use ONLY when peer-reviewed evidence is sparse or the topic is very recent; results are labeled preprints and rated Level V.",
    "get_references": "Backward snowballing: fetch the reference list of a ranked study [n]. Candidates merge into the pool on the next get_studies call.",
    "get_citations": "Forward snowballing: fetch papers that cite a ranked study [n]. Candidates merge into the pool on the next get_studies call.",
    "get_studies": "Deduplicate and pre-score ALL collected studies, then return a pre-ranked TOP TIER grouped by evidence level I->V (with facet counts and a has_more flag). Use browse_studies to page through the rest.",
    "browse_studies": "Page or filter the already-scored study pool by page number, evidence_level, or source. Reads existing scores — does NOT re-rank or reset screening.",
    "screen_studies": "Whitelist screening: pass included_indices and ONLY those studies survive; every other study is dropped. Optionally pass excluded_indices (+ a reason each) to name notable exclusions in Methods.",
    "finalize_ranking": "Submit your ranking after reviewing studies. Pass ordered indices (best first).",
    "appraise_evidence": "Record GRADE certainty (High/Moderate/Low/Very Low) for each major finding, with rationale and the supporting reference numbers.",
    "verify_studies": "Verify PMIDs of the ranked studies against PubMed.",
    "synthesize_report": "Returns structured evidence data for writing the final report.",
    "submit_report": "Submit your written research report (full markdown). MUST be called as the last step.",
    "translate_report": "Translate the submitted report to the target language.",
    "write_todos": "Create a research TODO list to plan the workflow.",
    "update_progress": "Signal a phase transition or progress update to the user.",
    "fetch_fulltext": "Look up free full text via Europe PMC, Unpaywall, and PMC for ranked studies; asks for user PDFs when automated fetches are missing.",
    "await_user_pdfs": "Pause until the user uploads PDFs and clicks Continue, or clicks Skip.",
    "parse_pdf": "Parse a user-uploaded or discovered full-text PDF to markdown.",
}
