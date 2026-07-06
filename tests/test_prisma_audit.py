from __future__ import annotations

import unittest

from medical_deep_research.research import build_audit_report, build_prisma_summary
from medical_deep_research.research.models import (
    EvidenceStudy,
    ScoredStudy,
    SearchProviderResult,
    VerificationDetail,
    VerificationSummary,
)


def scored(reference_number: int, title: str = "Published trial") -> ScoredStudy:
    return ScoredStudy(
        source="pubmed",
        source_id=str(reference_number),
        title=title,
        abstract="A randomized trial reported mortality outcomes.",
        journal="Journal",
        publication_year="2025",
        pmid=str(1000 + reference_number),
        sources=["pubmed"],
        evidence_level_score=0.8,
        citation_score=0.1,
        recency_score=0.9,
        composite_score=0.7,
        reference_number=reference_number,
    )


class PrismaAuditTests(unittest.TestCase):
    def test_prisma_excludes_non_literature_before_ranking(self) -> None:
        search_results = [
            SearchProviderResult(
                source="PubMed",
                query="q",
                studies=[
                    EvidenceStudy(
                        source="pubmed", source_id="1", title="A", sources=["pubmed"]
                    ),
                    EvidenceStudy(
                        source="pubmed", source_id="2", title="B", sources=["pubmed"]
                    ),
                ],
            ),
            SearchProviderResult(
                source="ClinicalTrials.gov",
                query="q",
                studies=[
                    EvidenceStudy(
                        source="clinicaltrials",
                        source_id="NCT1",
                        title="Registry",
                        sources=["clinicaltrials"],
                    )
                ],
            ),
        ]

        summary = build_prisma_summary(search_results, [scored(1)])

        self.assertEqual(summary.records_identified_total, 3)
        self.assertEqual(summary.records_after_deduplication, 2)
        self.assertEqual(summary.records_screened, 2)
        self.assertEqual(summary.studies_included, 1)
        self.assertTrue(any("non-literature" in note for note in summary.notes))

    def test_prisma_uses_screening_artifact_counts(self) -> None:
        summary = build_prisma_summary(
            [],
            [scored(1), scored(2)],
            screening={
                "screened_count": 5,
                "included": 2,
                "excluded": [{"reference_number": 3, "reason": "wrong population"}],
                "not_selected_count": 2,
            },
        )

        self.assertEqual(summary.records_screened, 5)
        self.assertEqual(summary.records_excluded, 3)
        self.assertEqual(summary.studies_included, 2)
        self.assertEqual(summary.excluded_records[0]["reason"], "wrong population")

    def test_audit_flags_invalid_citation_and_count_mismatch(self) -> None:
        report = (
            "# Report\n\n"
            "## 1. Executive Summary\n"
            "We ranked 3 studies and found benefit [2].\n\n"
            "## 7. References\n\n"
            "[1] Published trial. PMID: 1001."
        )

        audit = build_audit_report(report, [], [scored(1)])
        codes = {finding.code for finding in audit.findings}

        self.assertEqual(audit.status, "flagged")
        self.assertIn("invalid_citation", codes)
        self.assertIn("count_mismatch", codes)

    def test_audit_flags_pubmed_verification_failure(self) -> None:
        verification = VerificationSummary(
            total_considered=1,
            verified_pmids=0,
            missing_pmids=0,
            missing_from_pubmed=1,
            details=[
                VerificationDetail(
                    reference_number=1,
                    title="Published trial",
                    pmid="1001",
                    exists_in_pubmed=False,
                )
            ],
        )
        report = (
            "# Report\n\n"
            "## 1. Executive Summary\n"
            "Published evidence was reviewed [1].\n\n"
            "## 7. References\n\n"
            "[1] Published trial. PMID: 1001."
        )

        audit = build_audit_report(report, [], [scored(1)], verification)

        self.assertIn(
            "pubmed_verification_failed", {finding.code for finding in audit.findings}
        )


if __name__ == "__main__":
    unittest.main()
