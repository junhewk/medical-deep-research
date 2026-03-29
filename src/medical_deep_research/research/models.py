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
    publication_date: str | None = None
    publication_year: str | None = None
    doi: str | None = None
    pmid: str | None = None
    citation_count: int = 0
    url: str | None = None
    evidence_level: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    is_landmark_journal: bool = False
    sources: list[str] = Field(default_factory=list)


class SearchProviderResult(BaseModel):
    source: str
    query: str
    studies: list[EvidenceStudy] = Field(default_factory=list)
    error: str | None = None
    skipped: bool = False


class ScoredStudy(EvidenceStudy):
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

