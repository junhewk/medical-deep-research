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
    build_query_plan,
    empty_verification_summary,
    flatten_studies,
    render_report,
    render_verification_report,
    score_and_rank_results,
    search_source,
    verify_studies,
)
from ..research.models import EvidenceStudy, ScoredStudy, SearchProviderResult, VerificationSummary
from ..research.planning import extract_keywords, suggest_databases
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
        max_results_per_source: int = 6,
        ncbi_api_key: str | None = None,
        scopus_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        offline_mode: bool | None = None,
        recent_years_lookback: int | None = None,
        scopus_view: str | None = None,
    ) -> dict[str, object]:
        """Execute the deterministic search plan across all configured sources."""
        plan = build_query_plan(query, query_type, provider)
        resolved_offline_mode = _resolve_offline_mode(offline_mode)
        start_year = _start_year_from_lookback(_resolve_lookback(recent_years_lookback))
        resolved_view = _resolve_scopus_view(scopus_view)
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
        results = []
        for source in plan.databases:
            results.append(
                await search_source(
                    source,
                    plan.source_queries.get(source, plan.normalized_query),
                    api_keys=api_keys,
                    max_results=max_results_per_source,
                    offline_mode=resolved_offline_mode,
                    domain=plan.domain,
                    start_year=start_year,
                    scopus_view=resolved_view,
                )
            )
        flattened = flatten_studies(results)
        return {
            "plan": plan.model_dump(),
            "results": [result.model_dump() for result in results],
            "studies": [study.model_dump() for study in flattened],
            "counts": {result.source: len(result.studies) for result in results},
            "errors": {result.source: result.error for result in results if result.error},
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
    def synthesize_report(
        query: str,
        query_type: str = "free",
        provider: str = "openai",
        search_results_json: str | list[dict[str, object]] = "[]",
        ranked_studies_json: str | list[dict[str, object]] = "[]",
        verification_json: str | dict[str, object] | None = None,
        runtime_name: str = "Deterministic Python Runtime",
    ) -> str:
        """Render the final research report from normalized search, ranking, and verification data."""
        plan = build_query_plan(query, query_type, provider)
        return render_report(
            query=query,
            plan=plan,
            search_results=_parse_search_results(search_results_json),
            ranked_studies=_parse_scored_studies(ranked_studies_json),
            verification=_parse_verification_summary(verification_json),
            provider=provider,
            runtime_name=runtime_name,
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
