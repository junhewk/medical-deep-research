from __future__ import annotations

from typing import Any

from .connectors import is_rankable_evidence_study
from .models import EvidenceStudy, PrismaSummary, ScoredStudy, SearchProviderResult
from .scoring import deduplicate_studies


def _rankable_studies(
    search_results: list[SearchProviderResult],
) -> list[EvidenceStudy]:
    studies: list[EvidenceStudy] = []
    for result in search_results:
        studies.extend(
            study for study in result.studies if is_rankable_evidence_study(study)
        )
    return studies


def build_prisma_summary(
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    *,
    screening: dict[str, Any] | None = None,
    full_text_assessed: int = 0,
    final_synthesis_limit: int = 12,
) -> PrismaSummary:
    identified_by_source = {
        result.source: len(result.studies) for result in search_results
    }
    identified_total = sum(identified_by_source.values())
    non_rankable_total = sum(
        1
        for result in search_results
        for study in result.studies
        if not is_rankable_evidence_study(study)
    )
    deduplicated = deduplicate_studies(_rankable_studies(search_results))
    deduplicated_count = len(deduplicated)

    excluded_records: list[dict[str, object]] = []
    notes: list[str] = []
    if non_rankable_total:
        notes.append(
            f"Excluded {non_rankable_total} non-literature records before evidence ranking."
        )

    if screening:
        try:
            screened = int(screening.get("screened_count") or 0)
        except (TypeError, ValueError):
            screened = 0
        try:
            included = int(screening.get("included") or len(ranked_studies))
        except (TypeError, ValueError):
            included = len(ranked_studies)
        excluded_records = [
            item for item in (screening.get("excluded") or []) if isinstance(item, dict)
        ][:50]
        not_selected_count = int(screening.get("not_selected_count") or 0)
        excluded = max(0, screened - included)
        if not_selected_count:
            notes.append(
                f"{not_selected_count} screened records were not selected for synthesis."
            )
    else:
        screened = deduplicated_count
        included = len(ranked_studies)
        excluded = max(0, screened - included)
        if excluded:
            notes.append(
                "No explicit screening artifact was available; exclusions reflect ranking cutoff."
            )

    return PrismaSummary(
        records_identified_by_source=identified_by_source,
        records_identified_total=identified_total,
        records_after_deduplication=deduplicated_count,
        records_screened=screened,
        records_excluded=excluded,
        studies_included=included,
        full_text_assessed=max(0, int(full_text_assessed or 0)),
        final_synthesis_set=min(
            len(ranked_studies), max(0, int(final_synthesis_limit or 0))
        ),
        excluded_records=excluded_records,
        notes=notes,
    )
