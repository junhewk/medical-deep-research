from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from medical_deep_research.research.search import (
    SCOPUS_BASE_URL,
    SEMANTIC_SCHOLAR_BASE_URL,
    search_scopus,
    search_semantic_scholar,
)


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
