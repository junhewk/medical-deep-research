from __future__ import annotations

import re

from .models import QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary

# Maximum number of ranked studies that flow into synthesized reports.
#
# v2.9.5 widened database searches to 25 results/source, so the post-screened
# evidence set can exceed the old 20-study report window. Keep this high enough
# that a typical expanded run, such as 26 ranked studies, reaches synthesis
# without silently dropping citable references.
MAX_REPORT_STUDIES = 30


def _vancouver_author(name: str) -> str:
    """Normalize a single author name to Vancouver style ("Surname II")."""
    name = (name or "").strip()
    if not name:
        return ""
    parts = name.split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    # Already in "Surname Initials" form (e.g. PubMed esummary "Ahmed O", "Walsh EI").
    if last.isalpha() and last.isupper() and len(last) <= 3:
        return name
    surname = parts[-1]
    initials = "".join(part[0].upper() for part in parts[:-1] if part and part[0].isalpha())
    return f"{surname} {initials}".strip()


def _format_authors(authors: list[str]) -> str:
    """Format an author list per Vancouver rules: up to 6 names, then 'et al.'."""
    formatted = [author for author in (_vancouver_author(a) for a in (authors or [])) if author]
    if not formatted:
        return ""
    if len(formatted) > 6:
        return ", ".join(formatted[:6]) + ", et al."
    return ", ".join(formatted)


def format_vancouver_citation(study: ScoredStudy) -> str:
    """Render one reference deterministically from structured metadata.

    Format: Authors. Title. JournalAbbrev. Year;Volume(Issue):Pages. doi:DOI. PMID: x.
    Missing fields are simply omitted — never fabricated.
    """
    parts: list[str] = []

    authors = _format_authors(study.authors)
    if authors:
        parts.append(authors if authors.endswith(".") else authors + ".")

    title = (study.title or "").strip()
    if title:
        parts.append(title if title.endswith(".") else title + ".")

    journal = study.journal_abbrev or study.journal
    if journal:
        journal_part = journal.rstrip(". ")
        if study.publication_year:
            journal_part += f". {study.publication_year}"
            if study.volume:
                journal_part += f";{study.volume}"
                if study.issue:
                    journal_part += f"({study.issue})"
                if study.pages:
                    journal_part += f":{study.pages}"
        parts.append(journal_part + ".")
    elif study.publication_year:
        parts.append(f"{study.publication_year}.")

    if study.doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", study.doi.strip())
        parts.append(f"doi:{doi}.")
    if study.pmid:
        parts.append(f"PMID: {study.pmid}.")

    return " ".join(parts).strip()


def render_reference_entries(studies: list[ScoredStudy]) -> str:
    """Render numbered reference entries ("[n] citation"), keyed by reference_number."""
    entries: list[str] = []
    for index, study in enumerate(studies, start=1):
        number = study.reference_number if study.reference_number is not None else index
        entries.append(f"[{number}] {format_vancouver_citation(study)}")
    return "\n\n".join(entries)


def render_reference_list(studies: list[ScoredStudy]) -> str:
    """Render a complete numbered references section from structured metadata."""
    body = render_reference_entries(studies)
    return "## 7. References\n\n" + body if body else "## 7. References\n"


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
    if top_studies:
        lines.append(render_reference_entries(top_studies))

    if plan.notes:
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in plan.notes)

    return "\n".join(lines)
