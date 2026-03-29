from __future__ import annotations

from .research import empty_verification_summary, render_report
from .research.models import QueryPlan
from .research.planning import (
    build_query_plan as _build_query_plan,
)
from .research.scoring import get_evidence_level_score


SearchBundle = QueryPlan


def build_search_bundle(query: str, query_type: str, provider: str) -> QueryPlan:
    return _build_query_plan(query, query_type, provider)


def score_study_metadata(title: str, abstract: str = "") -> dict[str, object]:
    lowered = f"{title} {abstract}".lower()
    if "meta-analysis" in lowered or "systematic review" in lowered:
        level = "Level I"
    elif "randomized" in lowered or "randomised" in lowered or "trial" in lowered:
        level = "Level II"
    elif "cohort" in lowered or "case-control" in lowered:
        level = "Level III"
    elif "cross-sectional" in lowered or "case series" in lowered:
        level = "Level IV"
    else:
        level = "Level V"
    return {"evidence_level": level, "confidence": round(get_evidence_level_score(level), 2)}


def build_verification_report(query: str, keywords: list[str]) -> str:
    del query
    joined = ", ".join(keywords[:5])
    return "\n".join(
        [
            "# Verification Report",
            "",
            f"- Query scope preserved around: {joined}",
            "- Identifier-level verification is required before publication.",
            "- High-risk claims should be rechecked against PubMed or source abstracts.",
        ]
    )


def draft_report(query: str, query_type: str, provider: str, bundle: QueryPlan) -> str:
    del query_type
    return render_report(
        query=query,
        plan=bundle,
        search_results=[],
        ranked_studies=[],
        verification=empty_verification_summary(
            "Draft report generated before live search execution."
        ),
        provider=provider,
        runtime_name="Deterministic Python Runtime",
    )
