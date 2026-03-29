from __future__ import annotations

from .models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary


def _render_methods(plan: QueryPlan, results: list[SearchProviderResult]) -> list[str]:
    lines = [
        "## Methods",
        "",
        f"- Query type: `{plan.query_type}`",
        f"- Domain: `{plan.domain}`",
        f"- Keywords: {', '.join(plan.keywords) or 'None'}",
        "- Database plan:",
    ]
    for source in plan.databases:
        query = plan.source_queries.get(source, plan.normalized_query)
        matched = next((result for result in results if result.source == source), None)
        if matched is None:
            lines.append(f"  - {source}: not executed")
            continue
        if matched.skipped:
            lines.append(f"  - {source}: skipped ({matched.error})")
        elif matched.error:
            lines.append(f"  - {source}: failed ({matched.error})")
        else:
            lines.append(f"  - {source}: {len(matched.studies)} hits using `{query}`")
    return lines


def render_report(
    *,
    query: str,
    plan: QueryPlan,
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    verification: VerificationSummary,
    provider: str,
    runtime_name: str,
) -> str:
    top_studies = ranked_studies[:8]
    lines = [
        f"# Research Report: {query[:120]}",
        "",
        f"- Runtime: `{runtime_name}`",
        f"- Provider: `{provider}`",
        f"- Results reviewed: {len(ranked_studies)}",
        "",
        "## Executive Summary",
        "",
    ]

    if top_studies:
        lines.append(
            f"The deterministic pipeline found {len(ranked_studies)} ranked studies across {len(plan.databases)} planned sources. "
            f"The highest-ranked evidence includes {top_studies[0].title} and {top_studies[min(1, len(top_studies) - 1)].title if len(top_studies) > 1 else top_studies[0].title}."
        )
    else:
        lines.append(
            "The deterministic pipeline completed, but no retrievable studies were ranked. Review the source errors and query plan before trusting a synthesized answer."
        )

    lines.append("")
    lines.extend(_render_methods(plan, search_results))
    lines.extend(["", "## Ranked Evidence", ""])

    if top_studies:
        for study in top_studies:
            lines.append(
                f"- [{study.reference_number}] {study.title}. "
                f"Source: {', '.join(study.sources or [study.source])}. "
                f"Evidence: {study.evidence_level or 'Unknown'}. "
                f"Score: {study.composite_score}. "
                f"Citations: {study.citation_count}."
            )
            if study.abstract:
                snippet = study.abstract.replace("\n", " ").strip()
                lines.append(f"  Abstract summary: {snippet[:280]}{'...' if len(snippet) > 280 else ''}")
    else:
        lines.append("- No ranked studies available.")

    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Verified PMIDs: {verification.verified_pmids}",
            f"- Missing PMIDs: {verification.missing_pmids}",
            f"- Missing from PubMed: {verification.missing_from_pubmed}",
        ]
    )
    if verification.notes:
        lines.extend(f"- {note}" for note in verification.notes)

    lines.extend(["", "## References", ""])
    for study in top_studies:
        citation_parts = [f"[{study.reference_number}] {study.title}"]
        if study.journal:
            citation_parts.append(study.journal)
        if study.publication_year:
            citation_parts.append(study.publication_year)
        if study.doi:
            citation_parts.append(f"doi:{study.doi}")
        elif study.pmid:
            citation_parts.append(f"PMID:{study.pmid}")
        lines.append(". ".join(citation_parts) + ".")

    if plan.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in plan.notes)

    return "\n".join(lines)
