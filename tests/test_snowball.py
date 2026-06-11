from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from medical_deep_research.research.models import EvidenceStudy
from medical_deep_research.research.scoring import deduplicate_studies
from medical_deep_research.research.snowball import snowball


class FakeAsyncClient:
    responses: list[httpx.Response] = []

    def __init__(self, **kwargs: object) -> None:
        return None

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _url: str, *, params: dict[str, object] | None = None) -> httpx.Response:
        return self.__class__.responses.pop(0)


def epmc_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/"),
        json=payload,
    )


class SnowballTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []

    async def test_europe_pmc_references_mapped_and_dedupe_merges_sources(self) -> None:
        seed = EvidenceStudy(source="pubmed", source_id="111", title="Seed", pmid="34449189")
        references_payload = {
            "referenceList": {
                "reference": [
                    {
                        "id": "32446323",
                        "title": "A randomized controlled trial of disease-modifying therapy in HFrEF.",
                        "authorString": "Vaduganathan M, Solomon SD",
                        "journalAbbreviation": "Lancet",
                        "pubYear": 2020,
                        "citationType": "randomized controlled trial",
                    }
                ]
            }
        }
        FakeAsyncClient.responses = [epmc_response(references_payload)]
        with patch("medical_deep_research.research.snowball.httpx.AsyncClient", FakeAsyncClient):
            result = await snowball(seed, "references", max_results=10)

        self.assertIsNone(result.error)
        self.assertEqual(len(result.studies), 1)
        found = result.studies[0]
        self.assertEqual(found.pmid, "32446323")
        self.assertEqual(found.source, "europe_pmc_references")
        self.assertTrue(found.is_landmark_journal)  # Lancet
        self.assertEqual(found.evidence_level, "Level II")

        # A later get_studies dedupe merges the snowballed candidate by PMID.
        existing = EvidenceStudy(source="openalex", source_id="x", title="Other", pmid="32446323")
        merged = deduplicate_studies([existing, found])
        self.assertEqual(len(merged), 1)
        self.assertIn("openalex", merged[0].sources)
        self.assertIn("europe_pmc_references", merged[0].sources)

    async def test_no_identifier_returns_clear_error(self) -> None:
        seed = EvidenceStudy(source="crossref", source_id="t", title="No ids")
        result = await snowball(seed, "citations")
        self.assertEqual(result.studies, [])
        self.assertIn("neither PMID nor DOI", result.error or "")


if __name__ == "__main__":
    unittest.main()
