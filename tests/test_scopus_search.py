from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from medical_deep_research.research.search import SCOPUS_BASE_URL, search_scopus


def response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", SCOPUS_BASE_URL),
        json=payload or {"search-results": {"entry": []}},
    )


class FakeAsyncClient:
    responses: list[httpx.Response] = []
    calls: list[dict[str, object]] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

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
            result = await search_scopus("TITLE-ABS-KEY(vats)", api_key="test-key")

        self.assertTrue(result.skipped)
        self.assertIn("HTTP 500", result.error or "")
        self.assertIn("as if no API key", result.error or "")
        self.assertNotIn("api.elsevier.com", result.error or "")
        self.assertEqual(len(FakeAsyncClient.calls), 2)
        self.assertEqual(FakeAsyncClient.calls[0]["view"], "COMPLETE")
        self.assertEqual(FakeAsyncClient.calls[1]["view"], "STANDARD")


if __name__ == "__main__":
    unittest.main()
