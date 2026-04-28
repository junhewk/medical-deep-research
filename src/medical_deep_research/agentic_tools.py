"""Shared tool logic and event bridge for all agentic runtimes.

Provider-specific builders (Anthropic, OpenAI, Google, LangChain) wrap these
functions in their SDK's tool format.  The functions operate on a shared
``AgenticEventBridge`` that holds per-run state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

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
from .research.planning import suggest_databases as _suggest_databases
from .research.search import POLITE_EMAIL
from .models import RunRequest

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event bridge — provider-agnostic shared state + event queue
# ---------------------------------------------------------------------------

# Canonical (bare) tool names used in the phase map.
# Provider-specific builders may namespace them (e.g. ``mcp__literature__plan_search``)
# and should call ``bridge.set_tool_name_map`` if the runtime tool names differ.

_BARE_PHASE_MAP: dict[str, tuple[str, int]] = {
    "plan_search": ("planning", 12),
    "suggest_databases": ("planning", 14),
    "search_pubmed": ("searching", 20),
    "search_openalex": ("searching", 30),
    "search_cochrane": ("searching", 40),
    "search_semantic_scholar": ("searching", 50),
    "search_scopus": ("searching", 58),
    "get_studies": ("ranking", 68),
    "finalize_ranking": ("ranking", 75),
    "verify_studies": ("verifying", 82),
    "synthesize_report": ("synthesizing", 92),
    "write_todos": ("planning", 8),
    "update_progress": ("planning", 10),
    "fetch_fulltext": ("fulltext", 78),
    "parse_pdf": ("fulltext", 80),
}


class AgenticEventBridge:
    """Shared state + async event queue for agentic runtimes.

    Tool functions mutate this object (append search results, store rankings,
    etc.).  Hook / callback adapters push ``RuntimeEventPayload`` events onto
    ``self.queue`` so the ``stream_run`` coroutine can yield them to the
    service layer.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[RuntimeEventPayload | None] = asyncio.Queue()
        self._intermediate: dict[str, Any] = {}
        self._todos: list[str] = []
        self._tool_call_count = 0
        self._result: str | None = None
        self._error: Exception | None = None

        # Shared state written by tools, read by evidence tools
        self.search_results: list[SearchProviderResult] = []
        self.ranked_studies: list[ScoredStudy] = []
        self.verification: VerificationSummary | None = None
        self.plan: QueryPlan | None = None
        self._pre_scored: list[ScoredStudy] = []
        self._pdf_urls: dict[int, str] = {}
        self._pdf_url_alternatives: dict[int, list[str]] = {}

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

    def _phase_for(self, tool_name: str) -> tuple[str, int]:
        bare = self._bare_name(tool_name)
        if bare in _BARE_PHASE_MAP:
            return _BARE_PHASE_MAP[bare]
        if bare.startswith("search_"):
            return ("searching", 35)
        return ("searching", 50)

    # -- Generic event helpers (called by provider-specific hooks/callbacks) --

    async def on_tool_start(self, tool_name: str, tool_input: dict[str, Any] | None = None) -> None:
        phase, progress = self._phase_for(tool_name)
        self._tool_call_count += 1
        input_summary = {}
        if tool_input:
            input_summary = {k: (str(v)[:120] + "..." if len(str(v)) > 120 else v) for k, v in tool_input.items()}
        _log.info("[AGENT CALL #%d] %s  input=%s", self._tool_call_count, tool_name, json.dumps(input_summary, default=str))
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

    async def on_tool_end(self, tool_name: str, response: Any = None) -> None:
        phase, progress = self._phase_for(tool_name)
        resp_str = str(response) if response else "<empty>"
        resp_preview = resp_str[:300] + "..." if len(resp_str) > 300 else resp_str
        _log.info("[AGENT RESULT #%d] %s  response_len=%d  preview=%s", self._tool_call_count, tool_name, len(resp_str), resp_preview)
        bare = self._bare_name(tool_name)
        if bare in ("get_studies", "finalize_ranking", "verify_studies", "synthesize_report", "plan_search", "fetch_fulltext"):
            self._intermediate[bare] = response
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


async def tool_search(request: RunRequest, bridge: AgenticEventBridge, source: str, query: str, max_results: int = 8) -> dict[str, Any]:
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
    return {"source": result.source, "count": len(result.studies), "error": result.error, "studies": studies_summary}


async def tool_get_studies(request: RunRequest, bridge: AgenticEventBridge, context: str = "general") -> dict[str, Any]:
    all_studies = flatten_studies(bridge.search_results)
    if not all_studies:
        return {"error": "No studies collected yet. Run search tools first.", "studies": []}
    pre_scored = score_and_rank_results(all_studies, context=context)
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
            "score_breakdown": {"evidence": s.evidence_level_score, "citations": s.citation_score, "recency": s.recency_score},
        })
    return {"total": len(studies_out), "context": context, "studies": studies_out}


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
    studies_data = []
    for s in bridge.ranked_studies[:12]:
        entry: dict[str, Any] = {
            "rank": s.reference_number,
            "title": s.title,
            "authors": s.authors[:3] if s.authors else [],
            "year": s.publication_year,
            "journal": s.journal,
            "source": s.source,
            "doi": s.doi,
            "pmid": s.pmid,
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

    data = {
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
        "studies": studies_data,
        "verification": {
            "verified_pmids": verification.verified_pmids,
            "missing_pmids": verification.missing_pmids,
            "notes": verification.notes,
        },
        "instructions": (
            "Write a comprehensive research synthesis report in markdown. "
            "Submit the report itself, not a completion/status message. "
            "For non-empty evidence, target 1,200-2,000 words. "
            "The report MUST include: "
            "(1) An executive summary that directly answers the research question; "
            "(2) A methods section describing the search strategy; "
            "(3) A findings section that synthesizes evidence across studies — do NOT just list studies, "
            "compare and contrast findings, identify patterns, agreements and contradictions; "
            "(4) A discussion section interpreting the evidence, noting limitations, gaps, and quality of evidence; "
            "(5) A conclusion with clear takeaways; "
            "(6) A numbered references section. "
            "Cite studies by [number] throughout the text. "
            "In Results/Findings, present evidence levels from highest to lowest: Level I, Level II, Level III, Level IV, Level V. "
            "Number references sequentially as [1], [2], [3] with no gaps, and use only those same numbers in text citations. "
            "Write in the language specified by the query language setting."
        ),
    }
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


_EVIDENCE_LEVEL_RE = re.compile(r"\bLevel\s+(IV|III|II|I|V)\b", re.IGNORECASE)
_EVIDENCE_LEVEL_ORDER = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


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

    ordered_levels = [
        _EVIDENCE_LEVEL_ORDER[match.group(1).upper()]
        for match in _EVIDENCE_LEVEL_RE.finditer(findings)
    ]
    if len(set(ordered_levels)) < 2:
        return []

    highest_seen = ordered_levels[0]
    for level in ordered_levels[1:]:
        if level < highest_seen:
            return ["Results/Findings must present evidence levels from Level I to Level V, not lower levels before higher levels."]
        highest_seen = max(highest_seen, level)
    return []


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

    return issues


async def tool_submit_report(request: RunRequest, bridge: AgenticEventBridge, report_markdown: str) -> dict[str, Any]:
    """Store the agent-written final report."""
    report_markdown = str(report_markdown).strip()
    if not report_markdown:
        return {"error": "Report is empty. Write the full report and submit again."}
    quality_issues = report_quality_issues(
        report_markdown,
        ranked_count=len(bridge.ranked_studies),
        search_count=sum(len(result.studies) for result in bridge.search_results),
    )
    if quality_issues:
        bridge._intermediate["rejected_report"] = report_markdown
        bridge._intermediate["rejected_report_issues"] = quality_issues
        return {
            "error": "Report quality gate failed. Rewrite and submit the full report.",
            "issues": quality_issues,
            "instructions": (
                "Submit the complete markdown report itself, not a status update. "
                "Use the required sections, synthesize the evidence, cite searched studies as [n], "
                "include numbered references in strict [1], [2], [3] order, and organize evidence levels from Level I to Level V."
            ),
        }
    bridge._intermediate["submitted_report"] = report_markdown
    bridge.set_result(report_markdown)
    return {"status": "ok", "length": len(report_markdown)}


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
    base_url = os.getenv("MDR_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    from openai import AsyncOpenAI
    local_client = AsyncOpenAI(api_key="local", base_url=base_url)
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


async def tool_fetch_fulltext(request: RunRequest, bridge: AgenticEventBridge) -> dict[str, Any]:
    candidates = [
        s for s in bridge.ranked_studies
        if s.evidence_level in _EBM_HIGH_EVIDENCE and s.doi and s.reference_number is not None
    ]
    if not candidates:
        return {"error": "No Level I/II studies with DOIs found."}

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

    # Pass 1: Parallel Unpaywall (10 concurrent)
    if has_unpywall:
        sem = asyncio.Semaphore(10)

        async def _lookup(s: ScoredStudy) -> None:
            nonlocal unpywall_hits
            rank = s.reference_number
            if rank is None:
                return
            async with sem:
                try:
                    pdf_link = await asyncio.to_thread(Unpywall.get_pdf_link, s.doi)
                    if pdf_link:
                        found_ranks[rank] = {
                            "rank": rank, "title": s.title, "doi": s.doi, "pmid": s.pmid,
                            "evidence_level": s.evidence_level, "pdf_url": pdf_link, "source": "unpaywall",
                        }
                        unpywall_hits += 1
                except Exception:
                    pass

        await asyncio.gather(*[_lookup(s) for s in candidates])

    # Pass 2: PMC for ALL candidates with PMIDs (PMC tgz downloads are more
    # reliable than Unpaywall URLs which often return 403 from publishers)
    remaining = [s for s in candidates if s.pmid and s.reference_number is not None]
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

        sem_pmc = asyncio.Semaphore(5)

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
        rank_id = r["rank"]
        url = r["pdf_url"]
        if rank_id not in _url_map:
            _url_map[rank_id] = []
        # PMC tgz goes first (most reliable)
        if url.endswith(".tar.gz"):
            _url_map[rank_id].insert(0, url)
        else:
            _url_map[rank_id].append(url)
    bridge._pdf_urls = {k: v[0] for k, v in _url_map.items()}
    bridge._pdf_url_alternatives = _url_map
    available = sorted(found_ranks.values(), key=lambda r: r["rank"])
    _log.info("[FULLTEXT] %d PDFs found (unpaywall=%d, pmc=%d) from %d Level I/II studies",
              len(available), unpywall_hits, pmc_hits, len(candidates))
    return {"level_I_II_studies": len(candidates), "pdfs_found": len(available), "unpaywall_hits": unpywall_hits, "pmc_hits": pmc_hits, "available": available}


async def tool_parse_pdf(request: RunRequest, bridge: AgenticEventBridge, rank: int) -> dict[str, Any]:
    import io
    import tarfile
    import tempfile

    study = next((s for s in bridge.ranked_studies if s.reference_number == rank), None)
    title = study.title if study else f"Study #{rank}"
    urls = getattr(bridge, "_pdf_url_alternatives", {}).get(rank, [])
    if not urls:
        primary = bridge._pdf_urls.get(rank, "")
        if primary:
            urls = [primary]

    pdf_bytes: bytes | None = None
    source = "none"

    for url in urls:
        if pdf_bytes:
            break
        # PMC tgz archive
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
                _log.info("[PARSE_PDF] PMC tgz failed for rank %d: %s", rank, exc)
        # Direct URL (Unpaywall or other)
        else:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=True,
                                             headers={"User-Agent": "Mozilla/5.0 (compatible; MedicalDeepResearch/1.0; academic-research)"}) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if resp.content[:5] == b"%PDF-":
                        pdf_bytes = resp.content
                        source = "direct_url"
                        _log.info("[PARSE_PDF] Downloaded %d bytes via direct URL for rank %d", len(pdf_bytes), rank)
            except Exception as exc:
                _log.info("[PARSE_PDF] Direct URL failed for rank %d: %s", rank, exc)

    if not pdf_bytes:
        return {"error": f"Could not download PDF for rank {rank}", "title": title}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        pdf_path = f.name

    text = ""
    # Stage 1: markitdown[pdf] (no Java required)
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = await asyncio.to_thread(md.convert, pdf_path)
        text = (getattr(result, "text_content", None) or "").strip()
    except ImportError:
        pass
    except Exception as exc:
        _log.info("[PARSE_PDF] markitdown failed for rank %d: %s", rank, exc)

    # Stage 2: opendataloader-pdf fallback (requires Java)
    if not text:
        try:
            import opendataloader_pdf
            import glob as _glob
            output_dir = tempfile.mkdtemp()
            await asyncio.to_thread(
                opendataloader_pdf.convert,
                input_path=[pdf_path], output_dir=output_dir, format="markdown",
            )
            md_files = _glob.glob(f"{output_dir}/**/*.md", recursive=True)
            if md_files:
                with open(md_files[0]) as mf:
                    text = mf.read()
        except ImportError:
            pass
        except Exception as exc:
            _log.info("[PARSE_PDF] opendataloader failed for rank %d: %s", rank, exc)

    if not text:
        text = f"[PDF parse error: no parser available. PDF: {len(pdf_bytes)} bytes from {source}.]"

    _log.info("[PARSE_PDF] Parsed %d chars for rank %d (source=%s)", len(text), rank, source)

    import os as _os
    try:
        _os.unlink(pdf_path)
    except OSError:
        pass

    return {"rank": rank, "title": title, "source": source, "text_length": len(text), "fulltext": text}


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
**Search** (one call each): search_pubmed, search_openalex, search_cochrane, search_semantic_scholar, search_scopus
**Evidence** (reads from shared state — NO large JSON arguments needed):
- get_studies(context) — deduplicates and pre-scores all collected studies, returns full details for YOUR review
- finalize_ranking(ranked_indices, rationale) — submit your ranking. Pass indices best-first.
- verify_studies() — verifies PMIDs of ranked studies
- synthesize_report() — returns structured evidence data for you to write the final report
- submit_report(report_markdown) — submit your completed report. MUST be called as the final step.
**Fulltext** (call AFTER finalize_ranking):
- fetch_fulltext() — queries Unpaywall + PubMed Central for free PDFs across ALL ranked studies
- parse_pdf(rank) — downloads and parses a specific study's PDF to extract full text

## Workflow (follow exactly)

1. Call `plan_search` with the query.
2. Call search tools (one per database, use queries from the plan). Search 3-5 databases.
3. Call `get_studies` with context="{"clinical" if is_clinical else "general"}". \
Carefully review EVERY abstract. Assess relevance to the query, study design, evidence level, and quality.
4. Call `finalize_ranking` with your ordered list of study indices (best first) and a detailed rationale.
5. Call `fetch_fulltext` to find free PDFs across all ranked studies (Unpaywall + PMC).
6. Call `parse_pdf` for 1-3 studies that have PDFs available — read the full text.
7. Call `verify_studies` to validate PMIDs.
8. Call `synthesize_report` — this returns the structured evidence data.
9. **Write the full report** using the evidence data (see Report Format below).
10. Call `submit_report(report_markdown)` with your complete report. This is the FINAL step.

Do NOT pass study data as arguments — tools read from shared state.
Do NOT repeat searches. One call per database, then move forward.

## Report Quality Requirements (CRITICAL)

- The submitted report must be the report itself, not a completion note or summary of what you did.
- If any studies are ranked, write a comprehensive 1,200-2,000 word report unless the evidence base is genuinely empty.
- Use these markdown sections: Executive Summary, Background, Methods, Results/Findings, Discussion, Conclusions, References.
- Synthesize across studies; compare findings, study designs, populations, agreement, contradictions, and evidence quality.
- Cite only searched studies as [1], [2], etc. Do not cite unsearched sources.
- In Results/Findings, order evidence levels from Level I to Level V. Never put Level IV/V evidence before Level I/II evidence.
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
2. Search medical databases (PubMed, Scopus, Cochrane Library, OpenAlex, Semantic Scholar)
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
- Cochrane (systematic reviews)
- OpenAlex (broad academic coverage, free)
- Semantic Scholar (Medicine-filtered, free)
- Scopus (if API key available — citation counts)

## Evidence Classification

Assign evidence levels to each study:
- **Level I**: Systematic reviews, meta-analyses of RCTs
- **Level II**: Individual RCTs, well-designed controlled trials
- **Level III**: Non-randomized controlled studies, cohort studies
- **Level IV**: Case series, case-control studies
- **Level V**: Expert opinion, narrative reviews, case reports

## Report Format (Markdown) — YOU MUST WRITE THIS

Your final submitted report MUST be the complete research report itself, not a status update. \
For non-empty evidence, write 1,200-2,000 words and include these sections:

### 1. Executive Summary
Directly answer the clinical question in 2-3 paragraphs. Highlight the key finding and \
cite the landmark trial. State the strength of evidence and bottom-line conclusion.

### 2. Background
Why this question matters clinically. What is the current state of knowledge.

### 3. Methods
Search strategy, databases searched with hit counts, population criteria, inclusion/exclusion reasoning.

### 4. Results
Organize by evidence level, with [n] citations throughout:
- Level I evidence (systematic reviews, meta-analyses)
- Level II evidence (RCTs)
- Level III–V evidence
- Compare and contrast findings across studies
- Note agreements, contradictions, and effect sizes
Do not present Level IV/V evidence before Level I/II evidence.

### 5. Discussion
- Address population-specific considerations
- Clinical implications and applicability
- Limitations of the available evidence
- Gaps in the literature

### 6. Conclusions
Clear clinical takeaways. What the evidence supports, what remains uncertain.

### 7. References
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
2. Search academic databases (PubMed, OpenAlex, Semantic Scholar, Scopus)
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

### Database Coverage
Search multiple databases for comprehensive coverage:
- OpenAlex (primary for broad academic coverage, free)
- Semantic Scholar (cross-disciplinary without field restrictions, free)
- PubMed (for healthcare topics it indexes: nursing, bioethics, public health)
- Scopus (if API key available — citation counts and broader coverage)

## Report Format (Markdown) — YOU MUST WRITE THIS

Your final submitted report MUST be the complete research report itself, not a status update. \
For non-empty evidence, write 1,200-2,000 words and include these sections:

### 1. Executive Summary
Directly answer the research question in 2-3 paragraphs. Summarize the state of knowledge, \
the strength of the evidence base, and the key takeaway.

### 2. Background & Context
Why this topic matters. The current landscape and knowledge gaps.

### 3. Methods
Search strategy: databases searched, query terms used, hit counts per source, \
inclusion/exclusion reasoning.

### 4. Findings
Organize thematically — do NOT just list studies one by one. Instead:
- Group related findings by theme, approach, or outcome
- Compare and contrast what different studies found
- Consider diverse study types (qualitative, quantitative, mixed methods) as equally valid
- Note where the literature agrees, disagrees, or shows gaps
- Cite sources as [n] throughout

### 5. Implications for Practice and Policy
What do these findings mean for practitioners, educators, or policymakers?

### 6. Recommendations & Future Directions
What should be done next? Where are the gaps in knowledge?

### 7. References
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
    "search_openalex": "Search OpenAlex for open-access academic papers.",
    "search_cochrane": "Search Cochrane for systematic reviews.",
    "search_semantic_scholar": "Search Semantic Scholar for academic papers.",
    "search_scopus": "Search Scopus for academic citations.",
    "get_studies": "Deduplicate and pre-score ALL collected studies. Returns full details for your review.",
    "finalize_ranking": "Submit your ranking after reviewing studies. Pass ordered indices (best first).",
    "verify_studies": "Verify PMIDs of the ranked studies against PubMed.",
    "synthesize_report": "Returns structured evidence data for writing the final report.",
    "submit_report": "Submit your written research report (full markdown). MUST be called as the last step.",
    "translate_report": "Translate the submitted report to the target language.",
    "write_todos": "Create a research TODO list to plan the workflow.",
    "update_progress": "Signal a phase transition or progress update to the user.",
    "fetch_fulltext": "Look up free full-text PDFs via Unpaywall + PMC for Level I & II ranked studies.",
    "parse_pdf": "Download and parse a full-text PDF to markdown.",
}
