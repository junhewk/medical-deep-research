from __future__ import annotations

import unittest

from medical_deep_research.research import source_catalog
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult
from medical_deep_research.research.search import flatten_studies, search_source


class SourceCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_is_literature_only_by_default(self) -> None:
        entries = source_catalog({})
        names = {entry.name for entry in entries}

        self.assertIn("PubMed", names)
        self.assertIn("Preprints", names)
        self.assertNotIn("ClinicalTrials.gov", names)

    def test_catalog_marks_required_credentials(self) -> None:
        missing = {entry.name: entry for entry in source_catalog({})}
        present = {entry.name: entry for entry in source_catalog({"scopus": "key"})}

        self.assertFalse(missing["Scopus"].enabled)
        self.assertEqual(missing["Scopus"].credential_status, "missing")
        self.assertTrue(present["Scopus"].enabled)
        self.assertEqual(present["Scopus"].credential_status, "present")

    def test_auxiliary_catalog_marks_registry_non_rankable(self) -> None:
        entries = {
            entry.name: entry for entry in source_catalog({}, include_auxiliary=True)
        }

        self.assertIn("ClinicalTrials.gov", entries)
        self.assertFalse(entries["ClinicalTrials.gov"].ranked_evidence)
        self.assertEqual(entries["ClinicalTrials.gov"].source_type, "registry")

    def test_flatten_studies_filters_non_literature_by_default(self) -> None:
        results = [
            SearchProviderResult(
                source="PubMed",
                query="q",
                studies=[
                    EvidenceStudy(
                        source="pubmed",
                        source_id="1",
                        title="Published trial",
                        sources=["pubmed"],
                    )
                ],
            ),
            SearchProviderResult(
                source="ClinicalTrials.gov",
                query="q",
                studies=[
                    EvidenceStudy(
                        source="clinicaltrials",
                        source_id="NCT1",
                        title="Registry record",
                        sources=["clinicaltrials"],
                    )
                ],
            ),
        ]

        self.assertEqual(
            [study.title for study in flatten_studies(results)], ["Published trial"]
        )
        self.assertEqual(len(flatten_studies(results, rankable_only=False)), 2)

    async def test_search_source_accepts_catalog_aliases(self) -> None:
        result = await search_source("clinicaltrials", "q", offline_mode=True)

        self.assertEqual(result.source, "ClinicalTrials.gov")
        self.assertTrue(result.skipped)


if __name__ == "__main__":
    unittest.main()
