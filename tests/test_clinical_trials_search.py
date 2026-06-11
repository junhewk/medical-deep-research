from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from medical_deep_research.research.search import (
    CLINICALTRIALS_BASE_URL,
    search_clinical_trials,
    search_preprints,
)

# Trimmed but field-accurate capture of a ClinicalTrials.gov API v2 response.
SAMPLE_STUDIES = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04535960",
                    "briefTitle": "SGLT2 Inhibition in Congestive Heart Failure",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "startDateStruct": {"date": "2019-01-24"},
                    "primaryCompletionDateStruct": {"date": "2023-10"},
                    "resultsFirstPostDateStruct": {"date": "2024-02-01"},
                },
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "University Health Network"}},
                "descriptionModule": {"briefSummary": "Mechanistic insights into SGLT2i in heart failure."},
                "conditionsModule": {"conditions": ["Heart Failure", "Type 2 Diabetes"]},
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE2"],
                    "designInfo": {"allocation": "RANDOMIZED"},
                    "enrollmentInfo": {"count": 36},
                },
                "armsInterventionsModule": {"interventions": [{"name": "Empagliflozin 25 MG"}]},
            }
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT06280976",
                    "briefTitle": "Observational Registry of Coronary Plaque",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2024-03-01"},
                },
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "University of Louisville"}},
                "descriptionModule": {"briefSummary": "Observational cohort of plaque burden."},
                "conditionsModule": {"conditions": ["Coronary Artery Disease"]},
                "designModule": {
                    "studyType": "OBSERVATIONAL",
                    "phases": [],
                    "designInfo": {},
                },
            }
        },
    ],
    "nextPageToken": "abc",
}


def ct_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("GET", CLINICALTRIALS_BASE_URL),
        json=payload,
    )


class FakeAsyncClient:
    responses: list[httpx.Response] = []
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        return None

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _url: str, *, params: dict[str, object]) -> httpx.Response:
        self.__class__.calls.append(dict(params))
        return self.__class__.responses.pop(0)


class ClinicalTrialsSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []
        FakeAsyncClient.calls = []

    async def test_offline_mode_skips(self) -> None:
        result = await search_clinical_trials("heart failure", offline_mode=True)
        self.assertTrue(result.skipped)

    async def test_maps_registry_fields(self) -> None:
        FakeAsyncClient.responses = [ct_response(SAMPLE_STUDIES)]
        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_clinical_trials("heart failure", max_results=5)

        self.assertEqual(result.source, "ClinicalTrials.gov")
        self.assertEqual(len(result.studies), 2)

        randomized = result.studies[0]
        self.assertEqual(randomized.source, "clinicaltrials")
        self.assertEqual(randomized.source_id, "NCT04535960")
        self.assertEqual(randomized.evidence_level, "Level II")  # interventional + randomized
        self.assertEqual(randomized.trial_status, "COMPLETED")
        self.assertEqual(randomized.trial_phase, "PHASE2")
        self.assertTrue(randomized.has_published_results)
        self.assertEqual(randomized.url, "https://clinicaltrials.gov/study/NCT04535960")
        self.assertEqual(randomized.publication_year, "2019")

        observational = result.studies[1]
        self.assertIsNone(observational.evidence_level)  # not randomized interventional
        self.assertFalse(observational.has_published_results)
        self.assertEqual(observational.trial_status, "RECRUITING")

    async def test_network_error_is_reported(self) -> None:
        class BoomClient(FakeAsyncClient):
            async def get(self, _url: str, *, params: dict[str, object]) -> httpx.Response:
                raise httpx.ConnectError("boom")

        with patch("medical_deep_research.research.search.httpx.AsyncClient", BoomClient):
            result = await search_clinical_trials("heart failure")

        self.assertIsNotNone(result.error)
        self.assertEqual(result.studies, [])


class PreprintSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []
        FakeAsyncClient.calls = []

    async def test_preprints_force_level_v_and_label(self) -> None:
        payload = {
            "resultList": {
                "result": [
                    {
                        "id": "PPR123",
                        "title": "A promising preprint on heart failure",
                        "authorString": "Smith J, Doe A",
                        "pubYear": "2025",
                        "abstractText": "We report novel findings.",
                        "journalTitle": "medRxiv",
                    }
                ]
            }
        }
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search"),
            json=payload,
        )
        FakeAsyncClient.responses = [response]
        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_preprints("heart failure", max_results=5)

        self.assertEqual(result.source, "Preprints")
        self.assertEqual(len(result.studies), 1)
        study = result.studies[0]
        self.assertEqual(study.evidence_level, "Level V")
        self.assertIn("PREPRINT", study.abstract or "")
        self.assertIn("preprint", study.publication_types)
        self.assertIn("AND SRC:PPR", str(FakeAsyncClient.calls[0]["query"]))


if __name__ == "__main__":
    unittest.main()
