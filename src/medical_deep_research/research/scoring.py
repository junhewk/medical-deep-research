from __future__ import annotations

import math
from datetime import UTC, datetime

from .models import EvidenceStudy, ScoredStudy


def get_evidence_level_score(level: str | None) -> float:
    if not level:
        return 0.3
    lowered = level.lower().strip()
    if "level i" in lowered or lowered == "i":
        return 1.0
    if "level ii" in lowered or lowered == "ii":
        return 0.8
    if "level iii" in lowered or lowered == "iii":
        return 0.6
    if "level iv" in lowered or lowered == "iv":
        return 0.4
    if "level v" in lowered or lowered == "v":
        return 0.2
    return 0.3


def get_citation_score(citation_count: int | None) -> float:
    if not citation_count or citation_count <= 0:
        return 0.0
    return min(math.log(citation_count + 1) / math.log(1000), 1.0)


def get_recency_score(publication_date: str | None, half_life_years: int = 5) -> float:
    if not publication_date:
        return 0.5
    raw = publication_date.strip()
    for fmt in ("%Y-%m-%d", "%Y-%b-%d", "%Y-%B-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            years_old = (datetime.now(UTC) - parsed).days / 365.25
            return max(pow(0.5, years_old / half_life_years), 0.1)
        except ValueError:
            continue
    return 0.5


def _merge_duplicate(target: EvidenceStudy, incoming: EvidenceStudy) -> EvidenceStudy:
    merged = target.model_copy(deep=True)
    merged.sources = sorted(set((target.sources or [target.source]) + (incoming.sources or [incoming.source])))
    if not merged.abstract and incoming.abstract:
        merged.abstract = incoming.abstract
    if not merged.doi and incoming.doi:
        merged.doi = incoming.doi
    if not merged.pmid and incoming.pmid:
        merged.pmid = incoming.pmid
    merged.citation_count = max(target.citation_count, incoming.citation_count)
    if not merged.evidence_level and incoming.evidence_level:
        merged.evidence_level = incoming.evidence_level
    if not merged.publication_date and incoming.publication_date:
        merged.publication_date = incoming.publication_date
    if not merged.publication_year and incoming.publication_year:
        merged.publication_year = incoming.publication_year
    merged.is_landmark_journal = target.is_landmark_journal or incoming.is_landmark_journal
    if len(incoming.authors) > len(merged.authors):
        merged.authors = incoming.authors
    return merged


def deduplicate_studies(studies: list[EvidenceStudy]) -> list[EvidenceStudy]:
    deduped: dict[str, EvidenceStudy] = {}
    for study in studies:
        key = (study.doi or study.pmid or study.title).strip().lower()
        if key in deduped:
            deduped[key] = _merge_duplicate(deduped[key], study)
        else:
            initial = study.model_copy(deep=True)
            initial.sources = initial.sources or [initial.source]
            deduped[key] = initial
    return list(deduped.values())


def score_and_rank_results(studies: list[EvidenceStudy], *, context: str = "general") -> list[ScoredStudy]:
    deduped = deduplicate_studies(studies)
    scored: list[ScoredStudy] = []
    for study in deduped:
        evidence_level_score = get_evidence_level_score(study.evidence_level)
        citation_score = get_citation_score(study.citation_count)
        recency_score = get_recency_score(study.publication_date or study.publication_year, 3 if context == "clinical" else 5)
        if context == "clinical":
            composite_score = (
                evidence_level_score * 0.30
                + citation_score * 0.15
                + recency_score * 0.40
                + (1.0 if study.is_landmark_journal else 0.0) * 0.15
            )
        else:
            composite_score = evidence_level_score * 0.40 + citation_score * 0.30 + recency_score * 0.30
        scored.append(
            ScoredStudy(
                **study.model_dump(),
                evidence_level_score=round(evidence_level_score, 2),
                citation_score=round(citation_score, 2),
                recency_score=round(recency_score, 2),
                composite_score=round(composite_score, 2),
            )
        )

    scored.sort(key=lambda item: item.composite_score, reverse=True)
    for idx, study in enumerate(scored, start=1):
        study.reference_number = idx
    return scored

