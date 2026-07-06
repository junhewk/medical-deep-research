"""Research planning, search, scoring, verification, and reporting tools."""

from .audit import build_audit_report
from .connectors import source_catalog
from .models import (
    AuditFinding,
    AuditReport,
    EvidenceStudy,
    PrismaSummary,
    QueryPlan,
    ScoredStudy,
    SearchProviderResult,
    SourceCatalogEntry,
    VerificationSummary,
)
from .planning import build_query_plan
from .prisma import build_prisma_summary
from .reporting import (
    MAX_REPORT_STUDIES,
    format_vancouver_citation,
    render_reference_entries,
    render_reference_list,
    render_report,
)
from .scoring import deduplicate_studies, score_and_rank_results
from .search import flatten_studies, search_clinical_trials, search_preprints, search_source
from .snowball import snowball
from .verification import (
    empty_verification_summary,
    enrich_report_citations,
    render_verification_report,
    verify_studies,
)

__all__ = [
    "MAX_REPORT_STUDIES",
    "AuditFinding",
    "AuditReport",
    "EvidenceStudy",
    "PrismaSummary",
    "QueryPlan",
    "ScoredStudy",
    "SearchProviderResult",
    "SourceCatalogEntry",
    "VerificationSummary",
    "build_audit_report",
    "build_query_plan",
    "build_prisma_summary",
    "deduplicate_studies",
    "empty_verification_summary",
    "enrich_report_citations",
    "flatten_studies",
    "format_vancouver_citation",
    "render_reference_entries",
    "render_reference_list",
    "render_report",
    "render_verification_report",
    "score_and_rank_results",
    "search_clinical_trials",
    "search_preprints",
    "search_source",
    "snowball",
    "source_catalog",
    "verify_studies",
]
