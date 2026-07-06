from __future__ import annotations

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    query: str
    query_type: str
    provider: str
    domain: str
    normalized_query: str
    keywords: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    todos: list[str] = Field(default_factory=list)
    source_queries: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class EvidenceStudy(BaseModel):
    source: str
    source_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    journal_abbrev: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publication_date: str | None = None
    publication_year: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    citation_count: int = 0
    url: str | None = None
    evidence_level: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    is_landmark_journal: bool = False
    sources: list[str] = Field(default_factory=list)
    # Registry metadata (ClinicalTrials.gov records only)
    trial_status: str | None = None
    trial_phase: str | None = None
    has_published_results: bool | None = None


class SearchProviderResult(BaseModel):
    source: str
    query: str
    studies: list[EvidenceStudy] = Field(default_factory=list)
    error: str | None = None
    skipped: bool = False


class SourceCatalogEntry(BaseModel):
    id: str
    name: str
    domain: str
    description: str
    source_type: str = "literature"
    requires_api_key: bool = False
    api_key_names: list[str] = Field(default_factory=list)
    credential_status: str = "not_required"
    enabled: bool = True
    included_by_default: bool = True
    ranked_evidence: bool = True
    peer_reviewed: bool = True
    notes: list[str] = Field(default_factory=list)


class ScoredStudy(EvidenceStudy):
    relevance_score: float = 0.0
    evidence_level_score: float
    citation_score: float
    recency_score: float
    composite_score: float
    reference_number: int | None = None


class VerificationDetail(BaseModel):
    reference_number: int | None = None
    title: str
    pmid: str | None = None
    exists_in_pubmed: bool | None = None
    issue: str | None = None


class VerificationSummary(BaseModel):
    total_considered: int
    verified_pmids: int
    missing_pmids: int
    missing_from_pubmed: int
    offline_mode: bool = False
    details: list[VerificationDetail] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PrismaSummary(BaseModel):
    records_identified_by_source: dict[str, int] = Field(default_factory=dict)
    records_identified_total: int = 0
    records_after_deduplication: int = 0
    records_screened: int = 0
    records_excluded: int = 0
    studies_included: int = 0
    full_text_assessed: int = 0
    final_synthesis_set: int = 0
    excluded_records: list[dict[str, object]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AuditFinding(BaseModel):
    code: str
    severity: str
    claim: str | None = None
    issue: str
    evidence: str | None = None


class AuditReport(BaseModel):
    status: str
    findings: list[AuditFinding] = Field(default_factory=list)
    checked_citations: int = 0
    checked_references: int = 0
    checked_counts: int = 0
    notes: list[str] = Field(default_factory=list)
