from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from medical_deep_research.research.search import (
    NCBI_BASE_URL,
    SCOPUS_BASE_URL,
    SEMANTIC_SCHOLAR_BASE_URL,
    search_cochrane,
    search_pmc,
    search_pubmed,
    search_scopus,
    search_semantic_scholar,
)
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult


def response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", SCOPUS_BASE_URL),
        json=payload or {"search-results": {"entry": []}},
    )


def semantic_response(
    status_code: int,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", SEMANTIC_SCHOLAR_BASE_URL),
        json=payload or {"data": []},
        headers=headers,
    )


def ncbi_response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", f"{NCBI_BASE_URL}/esearch.fcgi"),
        json=payload or {"esearchresult": {"idlist": []}},
    )


def ncbi_xml_response(status_code: int, text: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", f"{NCBI_BASE_URL}/efetch.fcgi"),
        text=text,
    )


class FakeAsyncClient:
    responses: list[httpx.Response] = []
    calls: list[dict[str, object]] = []
    last_headers: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        headers = kwargs.get("headers")
        self.__class__.last_headers = dict(headers) if isinstance(headers, dict) else {}

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _url: str, *, params: dict[str, object]) -> httpx.Response:
        self.__class__.calls.append(dict(params))
        return self.__class__.responses.pop(0)


class ScopusSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []
        FakeAsyncClient.calls = []
        FakeAsyncClient.last_headers = {}

    async def test_no_key_skips_scopus_cleanly(self) -> None:
        result = await search_scopus("TITLE-ABS-KEY(vats)", api_key="")

        self.assertTrue(result.skipped)
        self.assertEqual(result.error, "Scopus API key not configured")

    async def test_rejected_key_returns_concise_error(self) -> None:
        FakeAsyncClient.responses = [response(403)]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_scopus("TITLE-ABS-KEY(vats)", api_key="bad-key")

        self.assertTrue(result.skipped)
        self.assertIn("API key was rejected", result.error or "")
        self.assertIn("as if no API key", result.error or "")
        self.assertNotIn("api.elsevier.com", result.error or "")
        self.assertEqual(len(FakeAsyncClient.calls), 1)

    async def test_server_error_retries_with_standard_view_and_hides_url(self) -> None:
        FakeAsyncClient.responses = [response(500), response(500)]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_scopus("TITLE-ABS-KEY(vats)", api_key="test-key", scopus_view="COMPLETE")

        self.assertTrue(result.skipped)
        self.assertIn("HTTP 500", result.error or "")
        self.assertIn("as if no API key", result.error or "")
        self.assertNotIn("api.elsevier.com", result.error or "")
        self.assertEqual(len(FakeAsyncClient.calls), 2)
        self.assertEqual(FakeAsyncClient.calls[0]["view"], "COMPLETE")
        self.assertEqual(FakeAsyncClient.calls[1]["view"], "STANDARD")

    async def test_default_view_is_standard(self) -> None:
        FakeAsyncClient.responses = [response(200)]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            await search_scopus("TITLE-ABS-KEY(vats)", api_key="test-key")

        self.assertEqual(FakeAsyncClient.calls[0]["view"], "STANDARD")

    async def test_scopus_key_is_sanitized_from_pasted_header(self) -> None:
        FakeAsyncClient.responses = [response(200)]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_scopus("TITLE-ABS-KEY(vats)", api_key="X-ELS-APIKey: test-key \n")

        self.assertFalse(result.skipped)
        self.assertEqual(FakeAsyncClient.last_headers["X-ELS-APIKey"], "test-key")

    async def test_scopus_uses_inline_pubyear_not_date_param(self) -> None:
        FakeAsyncClient.responses = [response(200)]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            await search_scopus("TITLE-ABS-KEY(vats)", api_key="test-key", start_year=2020)

        params = FakeAsyncClient.calls[0]
        self.assertNotIn("date", params)
        self.assertIn("PUBYEAR > 2019", str(params.get("query", "")))
        self.assertIn("PUBYEAR <", str(params.get("query", "")))

    async def test_cochrane_wraps_query_and_passes_ncbi_key(self) -> None:
        captured: dict[str, object] = {}

        async def fake_search_pubmed(
            query: str,
            *,
            max_results: int,
            api_key: str | None = None,
            offline_mode: bool = False,
            start_year: int | None = None,
        ) -> SearchProviderResult:
            captured.update(
                {
                    "query": query,
                    "max_results": max_results,
                    "api_key": api_key,
                    "offline_mode": offline_mode,
                    "start_year": start_year,
                }
            )
            return SearchProviderResult(
                source="PubMed",
                query=query,
                studies=[
                    EvidenceStudy(
                        source="pubmed",
                        source_id="1",
                        title="Cochrane review",
                    )
                ],
            )

        with patch("medical_deep_research.research.search.search_pubmed", side_effect=fake_search_pubmed):
            result = await search_cochrane(
                '"artificial intelligence"[tiab] AND "shared decision making"[tiab]',
                max_results=3,
                api_key="ncbi-key",
                offline_mode=True,
                start_year=2022,
            )

        self.assertIn('"Cochrane Database Syst Rev"[Journal]', str(captured["query"]))
        self.assertEqual(captured["api_key"], "ncbi-key")
        self.assertEqual(captured["max_results"], 3)
        self.assertEqual(captured["offline_mode"], True)
        self.assertEqual(captured["start_year"], 2022)
        self.assertEqual(result.source, "Cochrane")
        self.assertEqual(result.studies[0].source, "cochrane")
        self.assertEqual(result.studies[0].evidence_level, "Level I")

    async def test_pubmed_retries_transient_ncbi_502(self) -> None:
        FakeAsyncClient.responses = [
            ncbi_response(502),
            ncbi_response(200, {"esearchresult": {"idlist": []}}),
        ]

        with (
            patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient),
            patch("medical_deep_research.research.search.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await search_pubmed("AI communication training", max_results=5)

        self.assertEqual(result.source, "PubMed")
        self.assertIsNone(result.error)
        self.assertEqual(len(FakeAsyncClient.calls), 2)
        self.assertIn("User-Agent", FakeAsyncClient.last_headers)
        self.assertEqual(FakeAsyncClient.calls[0]["tool"], "medical-deep-research")
        self.assertIn("email", FakeAsyncClient.calls[0])

    async def test_pubmed_uses_article_ids_not_reference_ids(self) -> None:
        FakeAsyncClient.responses = [
            ncbi_response(200, {"esearchresult": {"idlist": ["123"]}}),
            ncbi_xml_response(
                200,
                """
                <PubmedArticleSet>
                  <PubmedArticle>
                    <MedlineCitation>
                      <PMID>123</PMID>
                      <Article>
                        <Journal><Title>Journal</Title></Journal>
                        <ArticleTitle>AI communication training article</ArticleTitle>
                        <Abstract><AbstractText>Abstract text.</AbstractText></Abstract>
                      </Article>
                    </MedlineCitation>
                    <PubmedData>
                      <ReferenceList>
                        <Reference>
                          <ArticleIdList>
                            <ArticleId IdType="doi">10.1000/reference</ArticleId>
                            <ArticleId IdType="pmc">PMCREF</ArticleId>
                          </ArticleIdList>
                        </Reference>
                      </ReferenceList>
                      <ArticleIdList>
                        <ArticleId IdType="pubmed">123</ArticleId>
                        <ArticleId IdType="doi">10.1000/article</ArticleId>
                        <ArticleId IdType="pmc">PMCARTICLE</ArticleId>
                      </ArticleIdList>
                    </PubmedData>
                  </PubmedArticle>
                </PubmedArticleSet>
                """,
            ),
        ]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_pubmed("AI communication training", max_results=1)

        self.assertEqual(result.studies[0].doi, "10.1000/article")
        self.assertEqual(result.studies[0].pmcid, "PMCARTICLE")

    async def test_pmc_uses_per_record_articleids_for_pmid_mapping(self) -> None:
        FakeAsyncClient.responses = [
            ncbi_response(200, {"esearchresult": {"idlist": ["11364946", "12816013"]}}),
            ncbi_response(
                200,
                {
                    "result": {
                        "uids": ["11364946", "12816013"],
                        "11364946": {
                            "title": "Simulated patient study",
                            "fulljournalname": "JMIR Medical Education",
                            "pubdate": "2024",
                            "articleids": [
                                {"idtype": "pmid", "value": "39150749"},
                                {"idtype": "pmcid", "value": "PMC11364946"},
                                {"idtype": "doi", "value": "10.2196/59213"},
                            ],
                        },
                        "12816013": {
                            "title": "Coaching messages study",
                            "fulljournalname": "Journal",
                            "pubdate": "2025",
                            "articleids": [
                                {"idtype": "pmid", "value": "41568066"},
                                {"idtype": "pmcid", "value": "PMC12816013"},
                                {"idtype": "doi", "value": "10.1007/s41347-025-00491-5"},
                            ],
                        },
                    }
                },
            ),
        ]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_pmc("large language model simulated patient", max_results=2)

        self.assertEqual([(s.pmcid, s.pmid) for s in result.studies], [
            ("PMC11364946", "39150749"),
            ("PMC12816013", "41568066"),
        ])
        self.assertEqual(len(FakeAsyncClient.calls), 2)


class SemanticScholarSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []
        FakeAsyncClient.calls = []
        FakeAsyncClient.last_headers = {}

    async def test_no_key_skips_semantic_scholar_cleanly(self) -> None:
        result = await search_semantic_scholar("query", api_key="")

        self.assertTrue(result.skipped)
        self.assertEqual(result.error, "Semantic Scholar API key not configured")

    async def test_bad_field_filter_retries_without_fields_of_study(self) -> None:
        FakeAsyncClient.responses = [
            semantic_response(400, {"message": "Invalid fieldsOfStudy"}),
            semantic_response(
                200,
                {
                    "data": [
                        {
                            "paperId": "abc",
                            "title": "ESPB after cardiac surgery",
                            "year": 2024,
                            "authors": [{"name": "Test A"}],
                            "citationCount": 3,
                        }
                    ]
                },
            ),
        ]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_semantic_scholar(
                "cardiac surgery ESPB", max_results=5, api_key="test-key"
            )

        self.assertIsNone(result.error)
        self.assertEqual(len(result.studies), 1)
        self.assertIn("fieldsOfStudy", FakeAsyncClient.calls[0])
        self.assertNotIn("fieldsOfStudy", FakeAsyncClient.calls[1])

    async def test_empty_field_filtered_result_retries_without_fields_of_study(self) -> None:
        FakeAsyncClient.responses = [
            semantic_response(200, {"data": []}),
            semantic_response(
                200,
                {
                    "data": [
                        {
                            "paperId": "def",
                            "title": "Serratus plane block pain score",
                            "year": 2023,
                            "citationCount": 7,
                        }
                    ]
                },
            ),
        ]

        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_semantic_scholar(
                "cardiac surgery ESPB", max_results=5, api_key="test-key"
            )

        self.assertIsNone(result.error)
        self.assertEqual(len(result.studies), 1)
        self.assertEqual(len(FakeAsyncClient.calls), 2)
        self.assertIn("fieldsOfStudy", FakeAsyncClient.calls[0])
        self.assertNotIn("fieldsOfStudy", FakeAsyncClient.calls[1])

    async def test_rate_limit_retries_with_retry_after(self) -> None:
        FakeAsyncClient.responses = [
            semantic_response(429, {"message": "Too many requests"}, headers={"retry-after": "0"}),
            semantic_response(
                200,
                {
                    "data": [
                        {
                            "paperId": "ghi",
                            "title": "Regional block after thoracic surgery",
                            "year": 2022,
                        }
                    ]
                },
            ),
        ]

        sleep_mock = AsyncMock()
        with (
            patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient),
            patch("medical_deep_research.research.search.asyncio.sleep", sleep_mock),
        ):
            result = await search_semantic_scholar(
                "thoracic surgery block", max_results=5, api_key="test-key"
            )

        self.assertIsNone(result.error)
        self.assertEqual(len(result.studies), 1)
        sleep_mock.assert_awaited_once_with(0.0)


if __name__ == "__main__":
    unittest.main()
