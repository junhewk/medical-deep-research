from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import patch

from medical_deep_research.models import EventType, RunRequest
from medical_deep_research.research.models import QueryPlan, ScoredStudy, VerificationSummary
import medical_deep_research.runtime as runtime_module
from medical_deep_research.agentic_tools import AgenticEventBridge
from medical_deep_research.runtime import (
    AgentResearchOutput,
    CodexRuntime,
    _codex_fetch_fulltext_for_ranked_studies,
    _codex_mcp_completion_extra,
    _codex_output_from_mcp_payloads,
    _codex_progress_update_from_item,
)


def make_request() -> RunRequest:
    return RunRequest(
        run_id="test-codex-progress",
        query="Population: clinicians; Concept: AI education; Context: training",
        query_type="pcc",
        mode="detailed",
        provider="codex",
        model="gpt-5.4",
        language="en",
    )


def minimal_output() -> AgentResearchOutput:
    return AgentResearchOutput(
        plan=QueryPlan(
            query="Population: clinicians; Concept: AI education; Context: training",
            query_type="pcc",
            provider="codex",
            domain="medical education",
            normalized_query="clinicians AI education training",
            keywords=["clinicians", "AI", "education"],
            databases=["PubMed"],
            todos=["Run source searches"],
            notes=[],
        ),
        search_results=[],
        ranked_studies=[],
        verification=VerificationSummary(
            total_considered=0,
            verified_pmids=0,
            missing_pmids=0,
            missing_from_pubmed=0,
        ),
        final_report="## Summary\n\nNo ranked studies were returned by the test runtime.",
    )


class SlowCodexRuntime(CodexRuntime):
    @property
    def sdk_available(self) -> bool:
        return True

    async def _run_codex_tool_agent(
        self,
        request: RunRequest,
        bridge: AgenticEventBridge,
    ) -> None:
        try:
            await bridge.on_tool_start("search_pubmed", {"query": request.query, "max_results": 3})
            await bridge.on_tool_end("search_pubmed", {"source": "PubMed", "count": 3, "studies": []})
            await asyncio.sleep(0.05)
            report = "# Research Report\n\n" + ("This accepted Codex test report sentence has enough words. " * 35)
            await bridge.on_tool_start("submit_report", {"length": len(report)})
            result = await runtime_module.tool_submit_report(request, bridge, report)
            await bridge.on_tool_end("submit_report", result)
        finally:
            await bridge.queue.put(None)


class FailingCodexRuntime(CodexRuntime):
    @property
    def sdk_available(self) -> bool:
        return True

    async def _run_codex_tool_agent(
        self,
        request: RunRequest,
        bridge: AgenticEventBridge,
    ) -> None:
        del request
        try:
            await bridge.on_tool_start("synthesize_report", {})
            await bridge.on_tool_end("synthesize_report", {"error": "tool exploded"})
            raise RuntimeError("synthesize_report failed: tool exploded")
        finally:
            await bridge.queue.put(None)


class CodexRuntimeProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_stream_emits_tool_progress_while_native_task_runs(self) -> None:
        with (
            patch("medical_deep_research.runtime.provider_fallback_reason", return_value=None),
            patch.object(runtime_module, "CODEX_AGENTIC_HEARTBEAT_SECONDS", 0.01),
            patch.object(runtime_module, "CODEX_AGENTIC_TIMEOUT_SECONDS", 1.0),
        ):
            events = [event async for event in SlowCodexRuntime().stream_run(make_request())]

        tool_events = [event for event in events if event.tool_name == "search_pubmed"]
        self.assertGreaterEqual(len(tool_events), 1)
        self.assertGreater(tool_events[0].progress, 10)
        self.assertIn("search_pubmed", tool_events[0].message)
        self.assertEqual(events[-1].event_type, EventType.RUN_COMPLETED)
        self.assertEqual(events[-1].progress, 100)

    async def test_codex_stream_fails_without_deterministic_fallback(self) -> None:
        events = []
        with (
            patch("medical_deep_research.runtime.provider_fallback_reason", return_value=None),
            patch.object(runtime_module, "CODEX_AGENTIC_HEARTBEAT_SECONDS", 0.01),
            patch.object(runtime_module, "CODEX_AGENTIC_TIMEOUT_SECONDS", 1.0),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthesize_report"):
                async for event in FailingCodexRuntime().stream_run(make_request()):
                    events.append(event)

        self.assertTrue(any(event.tool_name == "synthesize_report" for event in events))
        final_messages = [event.message for event in events if event.tool_name == "codex.thread_start"]
        self.assertTrue(any("Codex runtime failed" in message for message in final_messages))
        self.assertFalse(any(event.event_type == EventType.RUN_COMPLETED for event in events))

    async def test_codex_mcp_tool_item_summary_reports_counts(self) -> None:
        item = types.SimpleNamespace(
            root=types.SimpleNamespace(
                type="mcpToolCall",
                tool="aggregate_search",
                server="medical_literature",
                status="completed",
                duration_ms=1200,
                result=types.SimpleNamespace(
                    structured_content={
                        "studies": [{}, {}, {}],
                        "counts": {"PubMed": 2, "OpenAlex": 1, "Scopus": 0},
                    }
                ),
            )
        )

        update = _codex_progress_update_from_item(item, completed=True)

        self.assertIsNotNone(update)
        self.assertEqual(update["phase"], "searching")
        self.assertEqual(update["tool_name"], "literature.aggregate_search")
        self.assertIn("3 studies from 2 sources", update["message"])

    async def test_codex_failed_mcp_tool_item_reports_error_not_report_characters(self) -> None:
        item = types.SimpleNamespace(
            root=types.SimpleNamespace(
                type="mcpToolCall",
                tool="synthesize_report",
                server="medical_evidence",
                status="McpToolCallStatus.failed",
                duration_ms=19,
                result=types.SimpleNamespace(
                    structured_content=None,
                    content=[{"type": "text", "text": "validation failed for synthesize_report"}],
                ),
            )
        )

        update = _codex_progress_update_from_item(item, completed=True)

        self.assertIsNotNone(update)
        self.assertIn("Codex failed evidence.synthesize_report", update["message"])
        self.assertIn("validation failed", update["extra"]["error"])
        self.assertNotIn("report characters", update["message"])

    async def test_codex_output_is_built_from_mcp_payloads(self) -> None:
        request = make_request()
        study = {
            "source": "openalex",
            "source_id": "W1",
            "title": "AI-supported communication training",
            "abstract": "Training study.",
            "evidence_level_score": 1.0,
            "citation_score": 0.2,
            "recency_score": 1.0,
            "composite_score": 2.2,
            "reference_number": 1,
        }
        payloads = {
            "aggregate_search": {
                "plan": minimal_output().plan.model_dump(),
                "results": [
                    {
                        "source": "OpenAlex",
                        "query": "AI communication training",
                        "studies": [
                            {
                                "source": "openalex",
                                "source_id": "W1",
                                "title": "AI-supported communication training",
                            }
                        ],
                    }
                ],
            },
            "rank_results": {"studies": [study]},
            "verify_results": {
                "summary": {
                    "total_considered": 1,
                    "verified_pmids": 0,
                    "missing_pmids": 1,
                    "missing_from_pubmed": 0,
                    "details": [],
                    "notes": ["No PMID available for verification."],
                }
            },
            "synthesize_report": {
                "instructions": "Write final report.",
                "studies": [study],
                "total_ranked": 1,
            },
        }

        output = _codex_output_from_mcp_payloads(
            request,
            "OpenAI Codex SDK",
            payloads,
            final_response={"final_report": "# Research Report\n\nCodex-authored report."},
        )
        extra = _codex_mcp_completion_extra(
            output,
            ["aggregate_search", "rank_results", "fetch_fulltext", "verify_results", "synthesize_report"],
            fulltext_payload={"pdfs_found": 1, "requested_upload_ranks": [1], "unavailable_pdf_ranks": []},
        )

        self.assertEqual(output.final_report, "# Research Report\n\nCodex-authored report.")
        self.assertEqual(len(output.ranked_studies), 1)
        self.assertEqual(output.verification.missing_pmids, 1)
        self.assertEqual(extra["tool_calls"], 5)
        self.assertEqual(extra["report_source"], "codex.final_report")
        self.assertEqual(extra["source_counts"], {"OpenAlex": 1})
        self.assertEqual(extra["fulltext_pdfs_found"], 1)

    async def test_codex_fulltext_bridge_fetches_and_parses_available_text(self) -> None:
        request = make_request()
        plan = minimal_output().plan
        ranked = [
            ScoredStudy(
                source="pubmed",
                source_id="123",
                title="AI training systematic review",
                evidence_level="Level I",
                doi="10.1000/example",
                evidence_level_score=1.0,
                citation_score=0.0,
                recency_score=0.0,
                composite_score=1.0,
                reference_number=1,
            )
        ]
        progress_queue: asyncio.Queue[object] = asyncio.Queue()

        async def fake_fetch(_request, _bridge, *, allow_user_checkpoint: bool = True):
            self.assertTrue(allow_user_checkpoint)
            return {"pdfs_found": 1, "available": [{"rank": 1, "title": "AI training systematic review"}]}

        async def fake_parse(_request, _bridge, rank: int, *, allow_user_checkpoint: bool = True):
            self.assertEqual(rank, 1)
            self.assertFalse(allow_user_checkpoint)
            return {
                "rank": rank,
                "source": "downloaded_pdf",
                "text_length": 21,
                "fulltext": "Full text body for AI training.",
            }

        with (
            patch("medical_deep_research.runtime.tool_fetch_fulltext", side_effect=fake_fetch),
            patch("medical_deep_research.runtime.tool_parse_pdf", side_effect=fake_parse),
        ):
            result = await _codex_fetch_fulltext_for_ranked_studies(
                request,
                plan=plan,
                search_results=[],
                ranked_studies=ranked,
                progress_queue=progress_queue,
            )

        self.assertEqual(result["pdfs_found"], 1)
        self.assertEqual(result["parsed_fulltext"][0]["rank"], 1)
        self.assertIn("Full text body", result["parsed_fulltext"][0]["excerpt"])
        queued_events = []
        while not progress_queue.empty():
            queued_events.append(progress_queue.get_nowait())
        self.assertTrue(any(getattr(event, "tool_name", None) == "fetch_fulltext" for event in queued_events))
        self.assertTrue(any(getattr(event, "tool_name", None) == "parse_pdf" for event in queued_events))


if __name__ == "__main__":
    unittest.main()
