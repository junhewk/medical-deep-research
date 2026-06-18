"""Research planning, search, scoring, verification, and reporting tools."""

from .models import EvidenceStudy, QueryPlan, ScoredStudy, SearchProviderResult, VerificationSummary
from .planning import build_query_plan
from .reporting import MAX_REPORT_STUDIES, render_report
from .scoring import deduplicate_studies, score_and_rank_results
from .search import flatten_studies, search_clinical_trials, search_preprints, search_source
from .snowball import snowball
from .verification import empty_verification_summary, render_verification_report, verify_studies

__all__ = [
    "MAX_REPORT_STUDIES",
    "EvidenceStudy",
    "QueryPlan",
    "ScoredStudy",
    "SearchProviderResult",
    "VerificationSummary",
    "build_query_plan",
    "deduplicate_studies",
    "empty_verification_summary",
    "flatten_studies",
    "render_report",
    "render_verification_report",
    "score_and_rank_results",
    "search_clinical_trials",
    "search_preprints",
    "search_source",
    "snowball",
    "verify_studies",
]
