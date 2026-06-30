from __future__ import annotations

from .models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary

# Maximum number of ranked studies that flow into the synthesized report.
MAX_REPORT_STUDIES = 20


def _render_methods(plan: QueryPlan, results: list[SearchProviderResult]) -> list[str]:
    searched = []
    skipped = []
    failed = []
    total_hits = 0
    for source in plan.databases:
        matched = next((result for result in results if result.source == source), None)
        if matched is None:
            skipped.append(source)
            continue
        if matched.skipped:
            skipped.append(source)
            continue
        if matched.error:
            failed.append(source)
            continue
        total_hits += len(matched.studies)
        searched.append(f"{source} ({len(matched.studies)})")
    lines = [
        "## 3. Methods",
        "",
        f"The query was handled as a {plan.query_type.upper()} question in the {plan.domain} domain. "
        f"The search used the main concepts: {', '.join(plan.keywords[:10]) or 'none'}.",
        "",
        f"Searches returned {total_hits} source records before deduplication and ranking. "
        f"Executed sources: {', '.join(searched) or 'none'}.",
    ]
    if skipped:
        lines.append(f"Sources not executed or skipped: {', '.join(skipped)}.")
    if failed:
        lines.append(f"Sources with errors: {', '.join(failed)}.")
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
    top_studies = ranked_studies[:MAX_REPORT_STUDIES]
    lines = [
        "# Research Report",
        "",
        "## 1. Executive Summary",
        "",
    ]
    del runtime_name, provider

    if top_studies:
        lines.append(
            f"The evidence workflow identified {len(ranked_studies)} ranked studies relevant to the question. "
            f"The leading evidence includes {top_studies[0].title}"
            f"{' and ' + top_studies[1].title if len(top_studies) > 1 else ''}."
        )
    else:
        lines.append(
            "The evidence workflow completed, but no retrievable studies were ranked. The search should be revised before drawing conclusions."
        )

    lines.extend(["", "## 2. Background", "", f"Research question: {query}"])
    lines.extend(_render_methods(plan, search_results))
    lines.extend(["", "## 4. Results/Findings", ""])

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
            "## 5. Discussion",
            "",
            "The ranked evidence should be interpreted with attention to indirectness, study design, and the amount of full text available for appraisal. "
            "Automated ranking is not a substitute for duplicate human screening or a formal risk-of-bias review.",
            "",
            f"Identifier verification checked the highest-ranked PMID-bearing records: {verification.verified_pmids} PMIDs verified, "
            f"{verification.missing_pmids} records without PMIDs in the checked set, and {verification.missing_from_pubmed} records missing from PubMed.",
        ]
    )
    if verification.notes:
        lines.extend(f"- {note}" for note in verification.notes)

    lines.extend(
        [
            "",
            "## 6. Conclusions",
            "",
            "The available evidence should be treated as a mapped evidence base for review and follow-up screening. "
            "Conclusions should be strengthened only after full-text review of the key studies and explicit certainty appraisal.",
        ]
    )

    lines.extend(["", "## 7. References", ""])
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
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in plan.notes)

    return "\n".join(lines)
