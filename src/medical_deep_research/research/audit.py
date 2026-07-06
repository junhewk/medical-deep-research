from __future__ import annotations

import re
from typing import Any

from .connectors import is_rankable_evidence_study
from .models import (
    AuditFinding,
    AuditReport,
    ScoredStudy,
    SearchProviderResult,
    VerificationSummary,
)


_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_REFERENCE_ENTRY_RE = re.compile(r"(?m)^\s*(?:[-*]\s*)?\[(\d{1,3})\]\s+")
_NUMERIC_CLAIM_RE = re.compile(
    r"\b(?:"
    r"\d+(?:\.\d+)?\s*(?:%|mg|mcg|g|kg|ml|mmhg|years?|months?|weeks?|days?|"
    r"patients?|participants?|subjects?|studies|trials|events?)|"
    r"p\s*[<=>]\s*0?\.\d+|"
    r"(?:OR|RR|HR|MD|SMD)\s*[=:]?\s*\d+(?:\.\d+)?|"
    r"95\s*%\s*CI"
    r")\b",
    re.IGNORECASE,
)
_COUNT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\branked\s+(\d+)\s+stud", re.IGNORECASE), "ranked"),
    (re.compile(r"\b(\d+)\s+ranked\s+stud", re.IGNORECASE), "ranked"),
    (re.compile(r"\bscreened\s+(\d+)\s+(?:records?|stud)", re.IGNORECASE), "screened"),
    (
        re.compile(r"\b(\d+)\s+(?:records?|studies)\s+screened\b", re.IGNORECASE),
        "screened",
    ),
    (re.compile(r"\bincluded\s+(\d+)\s+stud", re.IGNORECASE), "included"),
    (re.compile(r"\b(\d+)\s+studies\s+included\b", re.IGNORECASE), "included"),
)
_METHOD_COUNT_TERMS = {
    "record",
    "records",
    "screened",
    "ranked",
    "included",
    "excluded",
    "identified",
    "database",
    "databases",
    "source",
    "sources",
    "reference",
    "references",
}


def _split_references(report_markdown: str) -> tuple[str, str]:
    lines = report_markdown.splitlines()
    for index, line in enumerate(lines):
        heading = line.strip().lower()
        heading = re.sub(r"^#{1,6}\s*", "", heading)
        heading = re.sub(r"^\d+[.)]\s*", "", heading)
        if heading.startswith("references") or heading.startswith("bibliography"):
            return "\n".join(lines[:index]), "\n".join(lines[index + 1 :])
    return report_markdown, ""


def _valid_reference_numbers(ranked_studies: list[ScoredStudy], limit: int) -> set[int]:
    numbers: set[int] = set()
    for fallback, study in enumerate(ranked_studies[:limit], start=1):
        numbers.add(int(study.reference_number or fallback))
    return numbers


def _citation_numbers(text: str) -> set[int]:
    return {int(match.group(1)) for match in _CITATION_RE.finditer(text)}


def _reference_numbers(references: str) -> set[int]:
    return {int(match.group(1)) for match in _REFERENCE_ENTRY_RE.finditer(references)}


def _evidence_corpus(
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    fulltext_excerpts: list[dict[str, Any]] | None,
) -> str:
    parts: list[str] = []
    for result in search_results:
        for study in result.studies:
            parts.extend(
                value
                for value in (
                    study.title,
                    study.abstract,
                    study.journal,
                    study.publication_year,
                    study.doi,
                    study.pmid,
                )
                if value
            )
    for study in ranked_studies:
        parts.extend(
            value
            for value in (
                study.title,
                study.abstract,
                study.journal,
                study.publication_year,
                study.doi,
                study.pmid,
            )
            if value
        )
    for item in fulltext_excerpts or []:
        excerpt = item.get("excerpt")
        if isinstance(excerpt, str):
            parts.append(excerpt)
    return " ".join(parts).casefold()


def _sentence_windows(text: str) -> list[str]:
    stripped = re.sub(r"\s+", " ", text)
    return [
        part.strip() for part in re.split(r"(?<=[.!?])\s+", stripped) if part.strip()
    ]


def _count_expectations(
    ranked_studies: list[ScoredStudy],
    screening: dict[str, Any] | None,
) -> dict[str, int]:
    expected = {"ranked": len(ranked_studies), "included": len(ranked_studies)}
    if screening:
        for key, target in (("screened_count", "screened"), ("included", "included")):
            try:
                expected[target] = int(screening.get(key) or expected.get(target, 0))
            except (TypeError, ValueError):
                pass
    return expected


def build_audit_report(
    report_markdown: str,
    search_results: list[SearchProviderResult],
    ranked_studies: list[ScoredStudy],
    verification: VerificationSummary | None = None,
    *,
    screening: dict[str, Any] | None = None,
    appraisal: dict[str, Any] | None = None,
    fulltext_excerpts: list[dict[str, Any]] | None = None,
    final_synthesis_limit: int = 12,
) -> AuditReport:
    del appraisal
    findings: list[AuditFinding] = []
    body, references = _split_references(report_markdown or "")
    valid_numbers = _valid_reference_numbers(ranked_studies, final_synthesis_limit)
    citation_numbers = _citation_numbers(body)
    reference_numbers = _reference_numbers(references)

    for number in sorted(citation_numbers - valid_numbers):
        findings.append(
            AuditFinding(
                code="invalid_citation",
                severity="major",
                claim=f"[{number}]",
                issue="Report cites a reference number that is not in the final synthesis set.",
                evidence=f"Allowed reference numbers: {sorted(valid_numbers)}",
            )
        )
    for number in sorted(reference_numbers - valid_numbers):
        findings.append(
            AuditFinding(
                code="invalid_reference_entry",
                severity="major",
                claim=f"[{number}]",
                issue="References section contains an entry outside the final synthesis set.",
                evidence=f"Allowed reference numbers: {sorted(valid_numbers)}",
            )
        )
    if references:
        for number in sorted((citation_numbers & valid_numbers) - reference_numbers):
            findings.append(
                AuditFinding(
                    code="missing_reference_entry",
                    severity="major",
                    claim=f"[{number}]",
                    issue="A cited study is missing from the References section.",
                )
            )

    for study in ranked_studies[:final_synthesis_limit]:
        if not is_rankable_evidence_study(study):
            findings.append(
                AuditFinding(
                    code="non_literature_ranked",
                    severity="major",
                    claim=study.title,
                    issue="A non-literature source was included in ranked EBM evidence.",
                    evidence=study.source,
                )
            )

    if verification:
        for detail in verification.details:
            if detail.exists_in_pubmed is False:
                findings.append(
                    AuditFinding(
                        code="pubmed_verification_failed",
                        severity="major",
                        claim=detail.title,
                        issue="PubMed verification reported that this PMID was not found.",
                        evidence=detail.pmid,
                    )
                )

    expected_counts = _count_expectations(ranked_studies, screening)
    checked_counts = 0
    for pattern, kind in _COUNT_PATTERNS:
        for match in pattern.finditer(body):
            checked_counts += 1
            reported = int(match.group(1))
            expected = expected_counts.get(kind)
            if expected is not None and reported != expected:
                findings.append(
                    AuditFinding(
                        code="count_mismatch",
                        severity="major",
                        claim=match.group(0),
                        issue=f"Reported {kind} count does not match stored workflow data.",
                        evidence=f"reported={reported}; expected={expected}",
                    )
                )

    corpus = _evidence_corpus(search_results, ranked_studies, fulltext_excerpts)
    numeric_findings = 0
    for sentence in _sentence_windows(body):
        lowered = sentence.casefold()
        if any(term in lowered for term in _METHOD_COUNT_TERMS):
            continue
        for match in _NUMERIC_CLAIM_RE.finditer(sentence):
            token = re.sub(r"\s+", " ", match.group(0).casefold()).strip()
            if token and token not in corpus:
                findings.append(
                    AuditFinding(
                        code="unsupported_numeric_claim",
                        severity="major",
                        claim=match.group(0),
                        issue="Numeric clinical/effect claim was not found in stored titles, abstracts, identifiers, or full-text excerpts.",
                        evidence=sentence[:240],
                    )
                )
                numeric_findings += 1
                break
        if numeric_findings >= 8:
            break

    notes = [
        "Deterministic audit only checks stored source records, citations, counts, and available full-text excerpts.",
        "It does not replace human risk-of-bias assessment.",
    ]
    return AuditReport(
        status="clean" if not findings else "flagged",
        findings=findings,
        checked_citations=len(citation_numbers),
        checked_references=len(reference_numbers),
        checked_counts=checked_counts,
        notes=notes,
    )
