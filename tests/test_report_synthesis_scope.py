from __future__ import annotations

import unittest

from medical_deep_research.agentic_tools import AgenticEventBridge, tool_synthesize_report
from medical_deep_research.models import ArtifactType, RunRequest
from medical_deep_research.research import MAX_REPORT_STUDIES
from medical_deep_research.research.models import ScoredStudy


def make_request() -> RunRequest:
    return RunRequest(
        run_id="test-report-scope",
        query="Population: learners; Concept: AI education; Context: communication training",
        query_type="pcc",
        mode="detailed",
        provider="local",
        model="test-model",
        language="en",
        offline_mode=False,
    )


def make_study(rank: int) -> ScoredStudy:
    return ScoredStudy(
        source="PubMed",
        source_id=str(rank),
        title=f"Study {rank}",
        abstract=f"Abstract for study {rank}.",
        authors=[f"Author {rank}"],
        journal="Journal of Testing",
        publication_year="2026",
        doi=f"10.1000/test.{rank}",
        citation_count=rank,
        evidence_level="Level II",
        relevance_score=0.8,
        evidence_level_score=0.8,
        citation_score=0.5,
        recency_score=1.0,
        composite_score=0.75,
        reference_number=rank,
    )


class ReportSynthesisScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_report_includes_twenty_six_ranked_studies(self) -> None:
        bridge = AgenticEventBridge()
        bridge.ranked_studies = [make_study(rank) for rank in range(1, 27)]

        data = await tool_synthesize_report(make_request(), bridge)

        self.assertEqual(data["total_ranked"], 26)
        self.assertEqual(len(data["studies"]), 26)
        self.assertEqual(data["report_reference_numbers"], list(range(1, 27)))
        self.assertEqual(data["omitted_ranked"], 0)

    async def test_synthesize_report_caps_above_report_limit_and_exposes_scope(self) -> None:
        bridge = AgenticEventBridge()
        bridge.ranked_studies = [make_study(rank) for rank in range(1, MAX_REPORT_STUDIES + 6)]

        data = await tool_synthesize_report(make_request(), bridge)

        self.assertEqual(len(data["studies"]), MAX_REPORT_STUDIES)
        self.assertEqual(data["omitted_ranked"], 5)
        self.assertEqual(data["report_reference_numbers"], list(range(1, MAX_REPORT_STUDIES + 1)))
        self.assertIn("Use only rank values present in the studies array", data["instructions"])

    async def test_ranked_artifact_contains_all_ranked_studies(self) -> None:
        bridge = AgenticEventBridge()
        bridge.ranked_studies = [make_study(rank) for rank in range(1, 27)]

        await bridge.on_tool_end("finalize_ranking", {"status": "ok", "total_ranked": 26})

        events = []
        while not bridge.queue.empty():
            events.append(await bridge.queue.get())

        artifacts = [event for event in events if event.artifact_type == ArtifactType.RANKED_RESULTS]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(len(artifacts[0].artifact_json["studies"]), 26)


if __name__ == "__main__":
    unittest.main()
