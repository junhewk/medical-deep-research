from __future__ import annotations

import unittest
from unittest.mock import patch

from medical_deep_research.mcp import servers
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult


class IncrementalMcpSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_aggregate_search_widens_after_sparse_first_round(self) -> None:
        calls: list[tuple[str, str]] = []

        async def fake_search_source(
            source: str,
            query: str,
            **_kwargs: object,
        ) -> SearchProviderResult:
            calls.append((source, query))
            # First round has no retrievable results. Broader rounds add one
            # source result each so the test can observe incremental widening.
            if "Population:" in query or "Health professions learners" in query:
                return SearchProviderResult(source=source, query=query, studies=[])
            return SearchProviderResult(
                source=source,
                query=query,
                studies=[
                    EvidenceStudy(
                        source=source.lower().replace(" ", "_"),
                        source_id=f"{source}-1",
                        title=f"{source} widened hit",
                    )
                ],
            )

        with patch.object(servers, "search_source", side_effect=fake_search_source):
            tool = servers.create_literature_server()._tool_manager._tools["aggregate_search"].fn
            result = await tool(
                query=(
                    "Population: Health professions learners; "
                    "Concept: AI-supported education, training; "
                    "Context: shared decision making education"
                ),
                query_type="pcc",
                provider="codex",
                max_results_per_source=5,
                min_unique_studies=24,
                max_search_rounds=3,
            )

        self.assertGreaterEqual(len(result["iterations"]), 2)
        self.assertEqual(result["iterations"][0]["strategy"], "focused")
        self.assertEqual(result["iterations"][1]["strategy"], "concept_context")
        self.assertGreater(len(result["studies"]), 0)
        self.assertGreater(len(calls), len(result["counts"]))
        self.assertIn("credentials_present", result)


if __name__ == "__main__":
    unittest.main()
