from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from .models import EvidenceStudy, ScoredStudy
from .planning import _structured_fields_from_payload, parse_structured_query, structured_query_text


_RELEVANCE_STOP_WORDS = {
    "about",
    "adult",
    "adults",
    "among",
    "and",
    "are",
    "based",
    "between",
    "care",
    "clinical",
    "compare",
    "compared",
    "disease",
    "effect",
    "effects",
    "for",
    "from",
    "health",
    "impact",
    "into",
    "management",
    "medical",
    "patient",
    "patients",
    "people",
    "role",
    "study",
    "that",
    "the",
    "their",
    "these",
    "this",
    "using",
    "versus",
    "with",
}

_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "large language model",
        "large language models",
        "llm",
        "llms",
        "chatgpt",
        "gpt",
        "generative ai",
        "generative artificial intelligence",
        "retrieval augmented generation",
        "rag",
        "conversational agent",
        "conversational agents",
        "chatbot",
        "chatbots",
        "virtual assistant",
        "virtual assistants",
    ),
    (
        "artificial intelligence",
        "ai",
        "machine learning",
        "deep learning",
    ),
    (
        "diabetes",
        "type 2 diabetes",
        "type ii diabetes",
        "t2d",
        "t2dm",
        "diabetes mellitus",
    ),
    (
        "randomized",
        "randomised",
        "randomized controlled trial",
        "randomised controlled trial",
        "rct",
        "trial",
    ),
)


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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokenize(text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in _RELEVANCE_STOP_WORDS
    }
    if "llm" in text.lower():
        tokens.add("llm")
    if "ai" in text.lower():
        tokens.add("ai")
    return tokens


def _study_relevance_text(study: EvidenceStudy) -> str:
    return _normalize_text(
        " ".join(
            part
            for part in (
                study.title,
                study.abstract or "",
                study.journal or "",
                " ".join(study.mesh_terms),
                " ".join(study.publication_types),
            )
            if part
        )
    )


def _query_fields(query: str | None, query_payload: dict[str, Any] | None) -> dict[str, str]:
    if not query:
        return {}
    return _structured_fields_from_payload(query_payload) or parse_structured_query(query)


def _synonym_hits(needles: str, haystack: str) -> float | None:
    lowered_needles = needles.lower()
    for group in _SYNONYM_GROUPS:
        if not any(term in lowered_needles for term in group):
            continue
        return 1.0 if any(term in haystack for term in group) else 0.0
    return None


def _term_match_score(terms: str, haystack: str, haystack_tokens: set[str]) -> float:
    normalized_terms = _normalize_text(terms)
    if not normalized_terms:
        return 0.5

    synonym_score = _synonym_hits(normalized_terms, haystack)
    if synonym_score is not None:
        return synonym_score

    tokens = _tokenize(normalized_terms)
    if not tokens:
        return 0.5
    matched = sum(1 for token in tokens if token in haystack_tokens or token in haystack)
    score = matched / len(tokens)
    if len(normalized_terms.split()) > 1 and normalized_terms in haystack:
        score = max(score, 0.9)
    return min(score, 1.0)


def get_relevance_score(
    study: EvidenceStudy,
    *,
    query: str | None = None,
    query_payload: dict[str, Any] | None = None,
) -> float:
    if not query:
        return 0.0

    haystack = _study_relevance_text(study)
    if not haystack:
        return 0.0
    haystack_tokens = _tokenize(haystack)
    fields = _query_fields(query, query_payload)
    normalized_query = structured_query_text(query, query_payload or fields)

    focus_text = fields.get("intervention") or fields.get("concept") or ""
    population_text = fields.get("population") or ""
    outcome_text = fields.get("outcome") or ""

    query_tokens = _tokenize(normalized_query)
    query_score = (
        sum(1 for token in query_tokens if token in haystack_tokens or token in haystack) / len(query_tokens)
        if query_tokens
        else 0.5
    )
    focus_score = _term_match_score(focus_text, haystack, haystack_tokens) if focus_text else 0.5
    population_score = _term_match_score(population_text, haystack, haystack_tokens) if population_text else 0.5
    outcome_score = _term_match_score(outcome_text, haystack, haystack_tokens) if outcome_text else 0.5

    if focus_text:
        relevance = focus_score * 0.50 + population_score * 0.20 + outcome_score * 0.10 + query_score * 0.20
    else:
        relevance = query_score * 0.65 + population_score * 0.20 + outcome_score * 0.15

    if focus_text and focus_score == 0.0:
        relevance = min(relevance, 0.28)
    if population_text and population_score == 0.0:
        relevance = min(relevance, 0.60)
    return max(0.0, min(relevance, 1.0))


def _merge_duplicate(target: EvidenceStudy, incoming: EvidenceStudy) -> EvidenceStudy:
    merged = target.model_copy(deep=True)
    merged.sources = sorted(set((target.sources or [target.source]) + (incoming.sources or [incoming.source])))
    if not merged.abstract and incoming.abstract:
        merged.abstract = incoming.abstract
    if not merged.doi and incoming.doi:
        merged.doi = incoming.doi
    if not merged.pmid and incoming.pmid:
        merged.pmid = incoming.pmid
    if not merged.pmcid and incoming.pmcid:
        merged.pmcid = incoming.pmcid
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


def score_and_rank_results(
    studies: list[EvidenceStudy],
    *,
    context: str = "general",
    query: str | None = None,
    query_payload: dict[str, Any] | None = None,
) -> list[ScoredStudy]:
    deduped = deduplicate_studies(studies)
    scored: list[ScoredStudy] = []
    for study in deduped:
        evidence_level_score = get_evidence_level_score(study.evidence_level)
        citation_score = get_citation_score(study.citation_count)
        recency_score = get_recency_score(study.publication_date or study.publication_year, 3 if context == "clinical" else 5)
        relevance_score = get_relevance_score(study, query=query, query_payload=query_payload)
        if context == "clinical":
            base_score = (
                evidence_level_score * 0.30
                + citation_score * 0.15
                + recency_score * 0.40
                + (1.0 if study.is_landmark_journal else 0.0) * 0.15
            )
        else:
            base_score = evidence_level_score * 0.40 + citation_score * 0.30 + recency_score * 0.30
        composite_score = (
            base_score * 0.55 + relevance_score * 0.45
            if query
            else base_score
        )
        scored.append(
            ScoredStudy(
                **study.model_dump(),
                relevance_score=round(relevance_score, 2),
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
