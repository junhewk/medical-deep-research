from __future__ import annotations

import argparse
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlmodel import select

from ..config import load_settings
from ..persistence import AppDatabase
from ..research import (
    MAX_REPORT_STUDIES,
    build_audit_report,
    build_prisma_summary,
    build_query_plan,
    deduplicate_studies,
    empty_verification_summary,
    flatten_studies,
    render_report,
    render_verification_report,
    score_and_rank_results,
    search_source,
    source_catalog,
    verify_studies,
)
from ..research.models import EvidenceStudy, ScoredStudy, SearchProviderResult, VerificationSummary
from ..research.planning import (
    build_pubmed_query,
    convert_to_scopus_query,
    extract_keywords,
    parse_structured_query,
    suggest_databases,
    structured_query_text,
)
from ..tools import score_study_metadata


def _decode_payload(payload: str | list[dict[str, object]] | dict[str, object] | None) -> Any:
    if payload is None:
        return None
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_secret(explicit: str | None, env_name: str) -> str | None:
    return explicit or os.getenv(env_name)


def _resolve_offline_mode(explicit: bool | None) -> bool:
    if explicit is None:
        return _env_flag("MDR_OFFLINE_MODE", default=False)
    return explicit


def _resolve_lookback(explicit: int | None) -> int:
    if explicit is not None and explicit > 0:
        return explicit
    raw = os.getenv("MDR_RECENT_YEARS_LOOKBACK")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return 5


def _start_year_from_lookback(lookback: int) -> int:
    from datetime import datetime
    return datetime.now().year - max(1, lookback) + 1


def _resolve_scopus_view(explicit: str | None) -> str:
    candidate = (explicit or os.getenv("MDR_SCOPUS_VIEW") or "STANDARD").upper()
    return candidate if candidate in {"STANDARD", "COMPLETE"} else "STANDARD"


def _parse_search_results(results_json: str | list[dict[str, object]]) -> list[SearchProviderResult]:
    records = _decode_payload(results_json)
    return [SearchProviderResult.model_validate(record) for record in records]


def _parse_evidence_studies(studies_json: str | list[dict[str, object]]) -> list[EvidenceStudy]:
    records = _decode_payload(studies_json)
    return [EvidenceStudy.model_validate(record) for record in records]


def _parse_scored_studies(studies_json: str | list[dict[str, object]]) -> list[ScoredStudy]:
    records = _decode_payload(studies_json)
    return [ScoredStudy.model_validate(record) for record in records]


def _parse_verification_summary(verification_json: str | dict[str, object] | None) -> VerificationSummary:
    payload = _decode_payload(verification_json)
    if not payload:
        return empty_verification_summary("Verification was not provided to the MCP report tool.")
    return VerificationSummary.model_validate(payload)


def _parse_optional_dict(payload_json: str | dict[str, object] | None) -> dict[str, object] | None:
    payload = _decode_payload(payload_json)
    return payload if isinstance(payload, dict) else None


def _source_queries_for_text(plan: Any, text: str, fields: dict[str, str] | None = None) -> dict[str, str]:
    keywords = extract_keywords(text, limit=10)
    pubmed_query = build_pubmed_query(text, keywords, fields)
    queries = {source: text for source in plan.databases}
    if "PubMed" in queries:
        queries["PubMed"] = pubmed_query
    if "PMC" in queries:
        queries["PMC"] = pubmed_query
    if "Cochrane" in queries:
        queries["Cochrane"] = pubmed_query
    scopus_query = convert_to_scopus_query(pubmed_query)
    if scopus_query and "Scopus" in queries:
        queries["Scopus"] = scopus_query
    return queries


def _same_source_queries(left: dict[str, str], right: dict[str, str]) -> bool:
    return {key: " ".join(value.split()) for key, value in left.items()} == {
        key: " ".join(value.split()) for key, value in right.items()
    }


def _incremental_search_variants(query: str, query_type: str, provider: str) -> tuple[Any, list[dict[str, object]]]:
    plan = build_query_plan(query, query_type, provider)
    variants: list[dict[str, object]] = [
        {
            "round": 1,
            "strategy": "focused",
            "reason": "Initial source-specific query plan.",
            "source_queries": dict(plan.source_queries),
        }
    ]

    fields = parse_structured_query(query)
    candidates: list[tuple[str, str, dict[str, str]]] = []
    if fields:
        concept_context = {
            key: value
            for key, value in fields.items()
            if key in {"concept", "intervention", "context", "outcome"}
        }
        if concept_context:
            candidates.append(
                (
                    "concept_context",
                    "Removed population terms after sparse first-round retrieval.",
                    concept_context,
                )
            )
        concept_only = {
            key: value
            for key, value in fields.items()
            if key in {"concept", "intervention"}
        }
        if concept_only and concept_only != concept_context:
            candidates.append(
                (
                    "concept_only",
                    "Removed context terms after sparse concept/context retrieval.",
                    concept_only,
                )
            )
    else:
        keyword_text = " ".join(plan.keywords[:6])
        if keyword_text:
            candidates.append(
                (
                    "keyword_bundle",
                    "Fallback keyword bundle after sparse first-round retrieval.",
                    {"concept": keyword_text},
                )
            )

    seen_queries = [dict(plan.source_queries)]
    for strategy, reason, candidate_fields in candidates:
        candidate_text = structured_query_text(query, candidate_fields)
        if not candidate_text:
            continue
        source_queries = _source_queries_for_text(plan, candidate_text, candidate_fields)
        if any(_same_source_queries(source_queries, seen) for seen in seen_queries):
            continue
        seen_queries.append(source_queries)
        variants.append(
            {
                "round": len(variants) + 1,
                "strategy": strategy,
                "reason": reason,
                "source_queries": source_queries,
            }
        )
    return plan, variants


def _needs_search_widening(
    *,
    unique_count: int,
    min_unique_studies: int,
) -> bool:
    return unique_count < min_unique_studies


def _merge_incremental_source_results(
    plan: Any,
    per_source_results: dict[str, list[SearchProviderResult]],
    per_source_queries: dict[str, list[tuple[str, str]]],
) -> list[SearchProviderResult]:
    merged: list[SearchProviderResult] = []
    for source in plan.databases:
        source_results = per_source_results.get(source, [])
        studies = deduplicate_studies(flatten_studies(source_results))
        queries = per_source_queries.get(source, [])
        query_text = " | ".join(
            f"{strategy}: {query}"
            for strategy, query in queries
        ) or plan.source_queries.get(source, plan.normalized_query)
        errors = [result.error for result in source_results if result.error]
        any_success = any(not result.error and not result.skipped for result in source_results)
        skipped = bool(source_results) and all(result.skipped for result in source_results)
        merged.append(
            SearchProviderResult(
                source=source,
                query=query_text,
                studies=studies,
                error=None if any_success or not errors else "; ".join(dict.fromkeys(errors)),
                skipped=skipped and not studies,
            )
        )
    return merged


def _synthesis_payload(
    *,
    query: str,
    query_type: str,
    provider: str,
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    verification: VerificationSummary,
    fulltext: dict[str, object] | None = None,
) -> dict[str, object]:
    plan = build_query_plan(query, query_type, provider)
    search_summary = {
        result.source: {
            "hits": len(result.studies),
            "query": result.query,
            "error": result.error,
            "skipped": result.skipped,
        }
        for result in search_results
    }
    studies: list[dict[str, object]] = []
    for study in ranked_studies[:MAX_REPORT_STUDIES]:
        entry: dict[str, object] = {
            "rank": study.reference_number,
            "title": study.title,
            "authors": study.authors[:3] if study.authors else [],
            "year": study.publication_year,
            "journal": study.journal,
            "source": study.source,
            "sources": study.sources,
            "doi": study.doi,
            "pmid": study.pmid,
            "pmcid": study.pmcid,
            "evidence_level": study.evidence_level,
            "citation_count": study.citation_count,
            "score": study.composite_score,
        }
        if study.abstract:
            entry["abstract"] = study.abstract[:900]
        studies.append(entry)

    fulltext_payload = fulltext or {}
    fulltext_available = fulltext_payload.get("available") if isinstance(fulltext_payload, dict) else None
    available_ranks = [
        item.get("rank")
        for item in fulltext_available
        if isinstance(item, dict) and item.get("rank") is not None
    ] if isinstance(fulltext_available, list) else []
    return {
        "query": query,
        "query_type": query_type,
        "language": "from run settings",
        "plan": {
            "domain": plan.domain,
            "keywords": plan.keywords,
            "databases": plan.databases,
            "notes": plan.notes,
        },
        "search_summary": search_summary,
        "total_ranked": len(ranked_studies),
        "studies": studies,
        "verification": {
            "verified_pmids": verification.verified_pmids,
            "missing_pmids": verification.missing_pmids,
            "missing_from_pubmed": verification.missing_from_pubmed,
            "notes": verification.notes,
        },
        "fulltext": {
            "attempted": bool(fulltext_payload),
            "pdfs_found": fulltext_payload.get("pdfs_found") if isinstance(fulltext_payload, dict) else None,
            "available_ranks": available_ranks,
            "parsed_fulltext": fulltext_payload.get("parsed_fulltext") if isinstance(fulltext_payload, dict) else None,
            "requested_upload_ranks": fulltext_payload.get("requested_upload_ranks") if isinstance(fulltext_payload, dict) else None,
            "unavailable_pdf_ranks": fulltext_payload.get("unavailable_pdf_ranks") if isinstance(fulltext_payload, dict) else None,
            "manual_upload_needed": fulltext_payload.get("manual_upload_needed") if isinstance(fulltext_payload, dict) else None,
            "user_pdf_checkpoint": fulltext_payload.get("user_pdf_checkpoint") if isinstance(fulltext_payload, dict) else None,
        },
        "instructions": (
            "Write the final report in markdown. The first non-empty line must be a level-1 title beginning with '# '. "
            "Use these numbered sections exactly: ## 1. Executive Summary, ## 2. Background, ## 3. Methods, "
            "## 4. Results/Findings, ## 5. Discussion, ## 6. Conclusions, ## 7. References. "
            "The report must synthesize across studies rather than list them, and must use available full-text excerpts "
            "for key study detail when present. Cite ranked studies as [1], [2], etc. throughout the text and keep "
            "the References section sequential with no gaps. In Results/Findings, discuss evidence by level from "
            "Level I/II before lower-level evidence. Include a concise certainty/limitations paragraph: if full "
            "text was unavailable for key studies, say the appraisal is abstract-limited. Do not include runtime "
            "metadata bullets, database hit tables, tool status messages, or phrases saying the report is above/below."
        ),
    }


def create_literature_server() -> FastMCP:
    server = FastMCP("Medical Literature", json_response=True)

    @server.tool()
    def keyword_bundle(query: str, query_type: str = "free", provider: str = "openai") -> dict[str, object]:
        """Build a deterministic search bundle for a medical research query."""
        return build_query_plan(query, query_type, provider).model_dump()

    @server.tool()
    def databases(query: str, provider: str = "openai") -> list[str]:
        """Suggest database coverage for the current query."""
        return suggest_databases(query, provider)

    @server.tool()
    def list_sources(
        ncbi_api_key: str | None = None,
        scopus_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        offline_mode: bool | None = None,
        include_auxiliary: bool = False,
    ) -> dict[str, object]:
        """List literature source catalog entries and credential status."""
        api_keys = {
            key: value
            for key, value in {
                "ncbi": _resolve_secret(ncbi_api_key, "MDR_NCBI_API_KEY"),
                "scopus": _resolve_secret(scopus_api_key, "MDR_SCOPUS_API_KEY"),
                "semantic_scholar": _resolve_secret(
                    semantic_scholar_api_key,
                    "MDR_SEMANTIC_SCHOLAR_API_KEY",
                ),
            }.items()
            if value
        }
        return {
            "literature_only": not include_auxiliary,
            "sources": [
                entry.model_dump()
                for entry in source_catalog(
                    api_keys,
                    offline_mode=_resolve_offline_mode(offline_mode),
                    include_auxiliary=include_auxiliary,
                )
            ],
        }

    @server.tool()
    async def search_pubmed(
        query: str,
        max_results: int = 8,
        api_key: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search PubMed with the deterministic Python adapter."""
        result = await search_source(
            "PubMed",
            query,
            api_keys={"ncbi": key} if (key := _resolve_secret(api_key, "MDR_NCBI_API_KEY")) else {},
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            domain="clinical",
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_openalex(
        query: str,
        max_results: int = 8,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search OpenAlex with the deterministic Python adapter."""
        result = await search_source(
            "OpenAlex",
            query,
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_pmc(
        query: str,
        max_results: int = 8,
        api_key: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search PubMed Central with the deterministic Python adapter."""
        result = await search_source(
            "PMC",
            query,
            api_keys={"ncbi": key} if (key := _resolve_secret(api_key, "MDR_NCBI_API_KEY")) else {},
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            domain="clinical",
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_europe_pmc(
        query: str,
        max_results: int = 8,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search Europe PMC with the deterministic Python adapter."""
        result = await search_source(
            "Europe PMC",
            query,
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            domain="clinical",
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_crossref(
        query: str,
        max_results: int = 8,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search Crossref with the deterministic Python adapter."""
        result = await search_source(
            "Crossref",
            query,
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_cochrane(
        query: str,
        max_results: int = 6,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search Cochrane reviews through the deterministic Python adapter."""
        result = await search_source(
            "Cochrane",
            query,
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_semantic_scholar(
        query: str,
        max_results: int = 8,
        api_key: str | None = None,
        fields_of_study: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
    ) -> dict[str, object]:
        """Search Semantic Scholar with the deterministic Python adapter."""
        del fields_of_study
        resolved_api_key = _resolve_secret(api_key, "MDR_SEMANTIC_SCHOLAR_API_KEY")
        result = await search_source(
            "Semantic Scholar",
            query,
            api_keys={"semantic_scholar": resolved_api_key} if resolved_api_key else {},
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            domain="clinical",
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
        )
        return result.model_dump()

    @server.tool()
    async def search_scopus(
        query: str,
        max_results: int = 8,
        api_key: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
        scopus_view: str | None = None,
    ) -> dict[str, object]:
        """Search Scopus with the deterministic Python adapter."""
        resolved_api_key = _resolve_secret(api_key, "MDR_SCOPUS_API_KEY")
        result = await search_source(
            "Scopus",
            query,
            api_keys={"scopus": resolved_api_key} if resolved_api_key else {},
            max_results=max_results,
            offline_mode=_resolve_offline_mode(offline_mode),
            start_year=_start_year_from_lookback(_resolve_lookback(recent_years_lookback)),
            scopus_view=_resolve_scopus_view(scopus_view),
        )
        return result.model_dump()

    @server.tool()
    async def aggregate_search(
        query: str,
        query_type: str = "free",
        provider: str = "openai",
        max_results_per_source: int = 25,
        min_unique_studies: int = 24,
        max_search_rounds: int = 3,
        ncbi_api_key: str | None = None,
        scopus_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
        scopus_view: str | None = None,
    ) -> dict[str, object]:
        """Execute an incremental search plan across all configured sources."""
        plan, variants = _incremental_search_variants(query, query_type, provider)
        resolved_offline_mode = _resolve_offline_mode(offline_mode)
        start_year = _start_year_from_lookback(_resolve_lookback(recent_years_lookback))
        resolved_view = _resolve_scopus_view(scopus_view)
        max_rounds = max(1, min(max_search_rounds, len(variants)))
        result_limit = max(1, min(max_results_per_source, 25))
        min_unique = max(1, min_unique_studies)
        api_keys = {
            key: value
            for key, value in {
                "ncbi": _resolve_secret(ncbi_api_key, "MDR_NCBI_API_KEY"),
                "scopus": _resolve_secret(scopus_api_key, "MDR_SCOPUS_API_KEY"),
                "semantic_scholar": _resolve_secret(
                    semantic_scholar_api_key,
                    "MDR_SEMANTIC_SCHOLAR_API_KEY",
                ),
            }.items()
            if value
        }

        per_source_results: dict[str, list[SearchProviderResult]] = {source: [] for source in plan.databases}
        per_source_queries: dict[str, list[tuple[str, str]]] = {source: [] for source in plan.databases}
        iterations: list[dict[str, object]] = []

        for variant in variants[:max_rounds]:
            strategy = str(variant["strategy"])
            source_queries = variant["source_queries"]
            assert isinstance(source_queries, dict)
            round_results: list[SearchProviderResult] = []
            for source in plan.databases:
                source_query = str(source_queries.get(source) or plan.source_queries.get(source) or plan.normalized_query)
                per_source_queries[source].append((strategy, source_query))
                result = await search_source(
                    source,
                    source_query,
                    api_keys=api_keys,
                    max_results=result_limit,
                    offline_mode=resolved_offline_mode,
                    domain=plan.domain,
                    start_year=start_year,
                    scopus_view=resolved_view,
                )
                per_source_results[source].append(result)
                round_results.append(result)

            merged_so_far = _merge_incremental_source_results(plan, per_source_results, per_source_queries)
            unique_after_round = len(deduplicate_studies(flatten_studies(merged_so_far)))
            iterations.append(
                {
                    "round": variant["round"],
                    "strategy": strategy,
                    "reason": variant["reason"],
                    "counts": {result.source: len(result.studies) for result in round_results},
                    "errors": {result.source: result.error for result in round_results if result.error},
                    "queries": {
                        source: str(source_queries.get(source) or plan.source_queries.get(source) or plan.normalized_query)
                        for source in plan.databases
                    },
                    "unique_after_round": unique_after_round,
                }
            )
            if not _needs_search_widening(
                unique_count=unique_after_round,
                min_unique_studies=min_unique,
            ):
                break

        results = _merge_incremental_source_results(plan, per_source_results, per_source_queries)
        flattened = deduplicate_studies(flatten_studies(results))
        return {
            "plan": plan.model_dump(),
            "source_catalog": [
                entry.model_dump()
                for entry in source_catalog(
                    api_keys,
                    offline_mode=resolved_offline_mode,
                )
            ],
            "results": [result.model_dump() for result in results],
            "studies": [study.model_dump() for study in flattened],
            "counts": {result.source: len(result.studies) for result in results},
            "errors": {result.source: result.error for result in results if result.error},
            "iterations": iterations,
            "max_results_per_source": result_limit,
            "min_unique_studies": min_unique,
            "credentials_present": {
                "ncbi": "ncbi" in api_keys,
                "scopus": "scopus" in api_keys,
                "semantic_scholar": "semantic_scholar" in api_keys,
            },
        }

    @server.resource("literature://keywords/{query}")
    def keyword_resource(query: str) -> str:
        """Expose extracted keywords as a resource for agent runtimes."""
        return json.dumps({"keywords": extract_keywords(query)}, indent=2)

    return server


def create_evidence_server() -> FastMCP:
    server = FastMCP("Medical Evidence", json_response=True)

    @server.tool()
    def score_evidence(title: str, abstract: str = "") -> dict[str, object]:
        """Score a study title or abstract with a conservative evidence heuristic."""
        return score_study_metadata(title, abstract)

    @server.tool()
    def verification_report(query: str) -> str:
        """Create a verification checklist artifact from the current query."""
        return "\n".join(
            [
                "# Verification Checklist",
                "",
                f"- Query: {query}",
                f"- Keywords: {', '.join(extract_keywords(query))}",
                "- Verify PMID coverage for the highest-ranked studies.",
                "- Review source failures before trusting absent evidence.",
            ]
        )

    @server.tool()
    def report_template(query: str, query_type: str = "free", provider: str = "openai") -> str:
        """Create a draft report shell from deterministic planning data."""
        plan = build_query_plan(query, query_type, provider)
        return render_report(
            query=query,
            plan=plan,
            search_results=[],
            ranked_studies=[],
            verification=empty_verification_summary(
                "This template was generated before search execution and PMID verification."
            ),
            provider=provider,
            runtime_name="Deterministic Python Runtime",
        )

    @server.tool()
    def rank_results(studies_json: str | list[dict[str, object]], context: str = "general") -> dict[str, object]:
        """Rank a JSON array of study records."""
        studies = _parse_evidence_studies(studies_json)
        ranked = score_and_rank_results(studies, context=context)
        return {"studies": [study.model_dump() for study in ranked]}

    @server.tool()
    async def verify_results(
        studies_json: str | list[dict[str, object]],
        ncbi_api_key: str | None = None,
        offline_mode: bool | None = None,
    ) -> dict[str, object]:
        """Verify ranked study records against PubMed identifiers."""
        studies = _parse_scored_studies(studies_json)
        resolved_api_key = _resolve_secret(ncbi_api_key, "MDR_NCBI_API_KEY")
        summary = await verify_studies(
            studies,
            api_keys={"ncbi": resolved_api_key} if resolved_api_key else {},
            offline_mode=_resolve_offline_mode(offline_mode),
        )
        return {"summary": summary.model_dump(), "markdown": render_verification_report(summary)}

    @server.tool()
    def prisma_flow(
        search_results_json: str | list[dict[str, object]],
        ranked_studies_json: str | list[dict[str, object]],
        screening_json: str | dict[str, object] | None = None,
        full_text_assessed: int = 0,
    ) -> dict[str, object]:
        """Build a deterministic PRISMA-style flow summary."""
        summary = build_prisma_summary(
            _parse_search_results(search_results_json),
            _parse_scored_studies(ranked_studies_json),
            screening=_parse_optional_dict(screening_json),
            full_text_assessed=full_text_assessed,
            final_synthesis_limit=MAX_REPORT_STUDIES,
        )
        return summary.model_dump()

    @server.tool()
    def audit_report(
        report_markdown: str,
        search_results_json: str | list[dict[str, object]],
        ranked_studies_json: str | list[dict[str, object]],
        verification_json: str | dict[str, object] | None = None,
        screening_json: str | dict[str, object] | None = None,
        appraisal_json: str | dict[str, object] | None = None,
        fulltext_json: str | dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Audit a report against stored citations, counts, verification, and source text."""
        fulltext_payload = _parse_optional_dict(fulltext_json)
        fulltext_excerpts = []
        if isinstance(fulltext_payload, dict):
            fulltext = fulltext_payload.get("fulltext")
            if isinstance(fulltext, dict) and isinstance(fulltext.get("excerpts"), list):
                fulltext_excerpts = [
                    item for item in fulltext["excerpts"] if isinstance(item, dict)
                ]
            elif isinstance(fulltext_payload.get("excerpts"), list):
                fulltext_excerpts = [
                    item for item in fulltext_payload["excerpts"] if isinstance(item, dict)
                ]
        audit = build_audit_report(
            report_markdown,
            _parse_search_results(search_results_json),
            _parse_scored_studies(ranked_studies_json),
            _parse_verification_summary(verification_json),
            screening=_parse_optional_dict(screening_json),
            appraisal=_parse_optional_dict(appraisal_json),
            fulltext_excerpts=fulltext_excerpts,
            final_synthesis_limit=MAX_REPORT_STUDIES,
        )
        return audit.model_dump()

    @server.tool()
    def synthesize_report(
        query: str,
        query_type: str = "free",
        provider: str = "openai",
        search_results_json: str | list[dict[str, object]] = "[]",
        ranked_studies_json: str | list[dict[str, object]] = "[]",
        verification_json: str | dict[str, object] | None = None,
        fulltext_json: str | dict[str, object] | None = None,
        runtime_name: str = "Deterministic Python Runtime",
    ) -> dict[str, object]:
        """Return structured evidence data and final report instructions."""
        del runtime_name
        fulltext_payload = _decode_payload(fulltext_json)
        return _synthesis_payload(
            query=query,
            query_type=query_type,
            provider=provider,
            search_results=_parse_search_results(search_results_json),
            ranked_studies=_parse_scored_studies(ranked_studies_json),
            verification=_parse_verification_summary(verification_json),
            fulltext=fulltext_payload if isinstance(fulltext_payload, dict) else None,
        )

    return server


def create_workspace_server() -> FastMCP:
    settings = load_settings()
    database = AppDatabase(settings)
    database.create_all()
    server = FastMCP("Medical Workspace", json_response=True)

    @server.tool()
    def list_runs() -> list[dict[str, object]]:
        """List existing research runs."""
        with database.session() as session:
            from ..models import ResearchRun

            runs = list(session.exec(select(ResearchRun).order_by(ResearchRun.created_at.desc())))  # type: ignore[attr-defined]
            return [
                {
                    "id": run.id,
                    "query": run.query,
                    "status": run.status,
                    "provider": run.provider,
                    "runtime_name": run.runtime_name,
                }
                for run in runs[:50]
            ]

    @server.tool()
    def list_artifacts(run_id: str) -> list[dict[str, object]]:
        """List artifacts for a research run."""
        with database.session() as session:
            from ..models import ResearchArtifact

            artifacts = list(
                session.exec(
                    select(ResearchArtifact)
                    .where(ResearchArtifact.run_id == run_id)
                    .order_by(ResearchArtifact.created_at.desc())  # type: ignore[attr-defined]
                )
            )
            return [
                {
                    "id": artifact.id,
                    "type": artifact.artifact_type,
                    "name": artifact.name,
                    "created_at": artifact.created_at.isoformat(),
                }
                for artifact in artifacts
            ]

    @server.resource("workspace://artifact/{artifact_id}")
    def read_artifact(artifact_id: str) -> str:
        """Read a saved artifact as a resource."""
        with database.session() as session:
            from ..models import ResearchArtifact

            artifact = session.get(ResearchArtifact, artifact_id)
            if artifact is None:
                return json.dumps({"error": "artifact not found"}, indent=2)
            return json.dumps(
                {
                    "id": artifact.id,
                    "type": artifact.artifact_type,
                    "name": artifact.name,
                    "content_text": artifact.content_text,
                    "content_json": artifact.content_json,
                },
                indent=2,
            )

    return server


SERVERS = {
    "literature": create_literature_server,
    "evidence": create_evidence_server,
    "workspace": create_workspace_server,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Medical Deep Research MCP server")
    parser.add_argument("server", choices=sorted(SERVERS))
    parser.add_argument("--transport", default="streamable-http")
    args = parser.parse_args()

    server = SERVERS[args.server]()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
