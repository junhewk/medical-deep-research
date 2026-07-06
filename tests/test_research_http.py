from __future__ import annotations

import unittest

import httpx

from medical_deep_research.research.http import (
    clear_http_cache,
    get_json,
    reset_rate_limits,
)


class ResearchHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clear_http_cache()
        reset_rate_limits()

    async def test_retries_retryable_status(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, request=request, json={"error": "rate"})
            return httpx.Response(200, request=request, json={"ok": True})

        data = await get_json(
            "https://example.test/retry",
            retries=1,
            backoff_base=0,
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(data, {"ok": True})
        self.assertEqual(calls, 2)

    async def test_caches_only_valid_non_empty_json(self) -> None:
        payloads = [{}, {"items": [1]}]
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, request=request, json=payloads.pop(0))

        transport = httpx.MockTransport(handler)
        first = await get_json("https://example.test/cache", transport=transport)
        second = await get_json("https://example.test/cache", transport=transport)

        self.assertEqual(first, {})
        self.assertEqual(second, {"items": [1]})
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
