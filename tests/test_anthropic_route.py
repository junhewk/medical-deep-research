from __future__ import annotations

import asyncio
import sys
import types
import unittest
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from medical_deep_research.agentic_tools import AgenticEventBridge, tool_submit_report
from medical_deep_research.models import EventType, RunRequest
from medical_deep_research.research.models import EvidenceStudy, ScoredStudy, SearchProviderResult, VerificationSummary
from medical_deep_research.runtime import AnthropicRuntime


class AlwaysAvailableAnthropicRuntime(AnthropicRuntime):
    @property
    def sdk_available(self) -> bool:
        return True


class FastTimeoutAnthropicRuntime(AlwaysAvailableAnthropicRuntime):
    agentic_timeout_seconds = 0.01


def fake_lc_tool(arg: object = None) -> object:
    def decorate(func: Callable[..., object], name: str | None = None) -> Callable[..., object]:
        setattr(func, "name", name or func.__name__)
        return func

    if callable(arg):
        return decorate(arg)
    if isinstance(arg, str):
        return lambda func: decorate(func, arg)
    return lambda func: decorate(func)


def _tool_name(tool: object) -> str:
    return str(getattr(tool, "name", getattr(tool, "__name__", "tool")))


async def call_fake_tool(tools: list[object], tool_name: str, **kwargs: object) -> object:
    for tool in tools:
        if _tool_name(tool) == tool_name:
            return await tool(**kwargs)  # type: ignore[misc]
    raise AssertionError(f"Tool not found: {tool_name}")


@contextmanager
def fake_langchain_agent(agent_impl: Callable[[list[object], dict[str, object]], Any]) -> object:
    agents_module = types.ModuleType("langchain.agents")
    core_tools_module = types.ModuleType("langchain_core.tools")
    langchain_module = types.ModuleType("langchain")
    langchain_core_module = types.ModuleType("langchain_core")
    langchain_anthropic_module = types.ModuleType("langchain_anthropic")

    class FakeAgent:
        def __init__(self, tools: list[object]) -> None:
            self.tools = tools

        async def ainvoke(self, inputs: dict[str, object]) -> object:
            result = agent_impl(self.tools, inputs)
            if hasattr(result, "__await__"):
                return await result
            return result

    def create_agent(*, model: str, tools: list[object], system_prompt: str) -> FakeAgent:
        assert model.startswith("anthropic:")
        assert system_prompt
        return FakeAgent(tools)

    agents_module.create_agent = create_agent
    core_tools_module.tool = fake_lc_tool

    previous = {
        name: sys.modules.get(name)
        for name in (
            "langchain",
            "langchain.agents",
            "langchain_core",
            "langchain_core.tools",
            "langchain_anthropic",
        )
    }
    sys.modules["langchain"] = langchain_module
    sys.modules["langchain.agents"] = agents_module
    sys.modules["langchain_core"] = langchain_core_module
    sys.modules["langchain_core.tools"] = core_tools_module
    sys.modules["langchain_anthropic"] = langchain_anthropic_module
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


async def fake_search_source(source: str, query: str, **_kwargs: object) -> SearchProviderResult:
    studies = []
    if source == "PubMed":
        studies = [
            EvidenceStudy(
                source="PubMed",
                source_id="12345678",
                title="Erector spinae plane block after cardiac surgery randomized trial",
                abstract="A randomized trial evaluating ESPB after cardiac surgery reported reduced pain scores.",
                journal="Journal of Clinical Anesthesia",
                publication_year="2024",
                pmid="12345678",
                citation_count=12,
                evidence_level="Level II",
                publication_types=["Randomized Controlled Trial"],
                sources=["PubMed"],
            )
        ]
    return SearchProviderResult(source=source, query=query, studies=studies)


async def fake_verify_studies(studies: list[object], **_kwargs: object) -> VerificationSummary:
    return VerificationSummary(
        total_considered=len(studies),
        verified_pmids=len(studies),
        missing_pmids=0,
        missing_from_pubmed=0,
        notes=["fake verification"],
    )


def make_request(*, language: str = "en") -> RunRequest:
    return RunRequest(
        run_id="test-run",
        query="Population: cardiac surgery; Intervention: ESPB; Comparison: PCA; Outcome: Pain score",
        query_type="pico",
        mode="detailed",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        language=language,
        api_keys={"anthropic": "test-key"},
        offline_mode=False,
    )


def make_valid_report() -> str:
    synthesis = " ".join(
        [
            (
                "The randomized evidence remains limited but clinically relevant because the ESPB cohort "
                "reported lower postoperative pain scores than PCA alone while preserving a plausible safety "
                "profile for cardiac surgery patients [1]."
            )
            for _ in range(90)
        ]
    )
    return f"""# Research Report

## Executive Summary
ESPB after cardiac surgery was evaluated against PCA in the searched evidence. The key finding is that
regional analgesia may reduce pain scores when added to conventional analgesic care [1].

## Background
Postoperative pain after cardiac surgery affects mobilization, pulmonary recovery, and patient satisfaction.
The clinical question asks whether ESPB improves analgesic outcomes compared with PCA alone.

## Methods
The agent searched PubMed and screened the retrieved study for population, intervention, comparator, and
outcome alignment. The included evidence was ranked by relevance, evidence level, recency, and source quality.

## Results
{synthesis}

## Discussion
The evidence should be interpreted cautiously because the available ranked set is small. Still, the study design
is relevant to the clinical question and supports further focused comparison of ESPB with PCA-based strategies [1].

## Conclusions
ESPB may be a useful analgesic adjunct after cardiac surgery, but conclusions should remain proportional to the
limited evidence retrieved in this run.

## References
[1] Test AB. Erector spinae plane block after cardiac surgery randomized trial. Journal of Clinical Anesthesia.
2024. PMID: 12345678.
"""


def make_ranked_study() -> ScoredStudy:
    return ScoredStudy(
        source="PubMed",
        source_id="12345678",
        title="Erector spinae plane block after cardiac surgery randomized trial",
        abstract="A randomized trial evaluating ESPB after cardiac surgery reported reduced pain scores.",
        journal="Journal of Clinical Anesthesia",
        publication_year="2024",
        pmid="12345678",
        citation_count=12,
        evidence_level="Level II",
        publication_types=["Randomized Controlled Trial"],
        sources=["PubMed"],
        evidence_level_score=4.0,
        citation_score=1.2,
        recency_score=1.0,
        composite_score=6.2,
        reference_number=1,
    )


class AnthropicRouteTests(unittest.IsolatedAsyncioTestCase):
    async def collect_events(
        self,
        agent_impl: Callable[[list[object], dict[str, object]], Any],
        *,
        runtime: AnthropicRuntime | None = None,
        request: RunRequest | None = None,
    ) -> list[object]:
        with (
            fake_langchain_agent(agent_impl),
            patch("medical_deep_research.runtime.search_source", fake_search_source),
            patch("medical_deep_research.runtime.verify_studies", fake_verify_studies),
            patch("medical_deep_research.agentic_tools.search_source", fake_search_source),
            patch("medical_deep_research.agentic_tools.verify_studies", fake_verify_studies),
        ):
            selected_runtime = runtime or AlwaysAvailableAnthropicRuntime()
            selected_request = request or make_request()
            return [event async for event in selected_runtime.stream_run(selected_request)]

    async def test_no_tool_calls_runs_deterministic_fallback(self) -> None:
        async def no_op_agent(_tools: list[object], _inputs: dict[str, object]) -> object:
            return {"messages": []}

        events = await self.collect_events(no_op_agent)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        self.assertGreaterEqual(len(completed), 1)
        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertTrue(final.extra["agentic_fallback"])
        self.assertIn("completed without calling any research tools", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)
        self.assertNotIn("not executed", final.report_markdown or "")

    async def test_agent_error_before_tools_runs_deterministic_fallback_with_reason(self) -> None:
        async def error_agent(_tools: list[object], _inputs: dict[str, object]) -> object:
            raise RuntimeError("missing Anthropic dependency")

        events = await self.collect_events(error_agent)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertIn("RuntimeError: missing Anthropic dependency", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)

    async def test_default_anthropic_path_does_not_require_git(self) -> None:
        async def no_op_agent(_tools: list[object], _inputs: dict[str, object]) -> object:
            return {"messages": []}

        events = await self.collect_events(no_op_agent)
        start = next(event for event in events if event.event_type == EventType.RUN_STARTED)

        self.assertEqual(start.extra["runtime_engine"], "langchain_anthropic")
        self.assertNotIn("git", str(start.extra).lower())

    async def test_planning_only_run_falls_back_before_empty_report(self) -> None:
        async def planning_only_agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "plan_search", query=make_request().query, query_type="pico")
            return {"messages": [{"content": "Planning finished but no searches were executed."}]}

        events = await self.collect_events(planning_only_agent)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertIn("completed without executing any search tools", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)

    async def test_tool_using_agentic_run_reports_tool_counts(self) -> None:
        report = make_valid_report().strip()

        async def successful_agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "plan_search", query=make_request().query, query_type="pico")
            await call_fake_tool(tools, "search_pubmed", query="cardiac surgery ESPB PCA pain", max_results=3)
            await call_fake_tool(tools, "get_studies", context="clinical")
            await call_fake_tool(tools, "finalize_ranking", ranked_indices=[1], rationale="Most relevant RCT.")
            await call_fake_tool(tools, "verify_studies")
            await call_fake_tool(tools, "submit_report", report_markdown=report)
            return {"messages": [{"content": "Perfect! I have successfully completed the literature review."}]}

        events = await self.collect_events(successful_agent)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "native_sdk_agentic")
        self.assertEqual(final.extra["runtime_engine"], "langchain_anthropic")
        self.assertFalse(final.extra["had_error"])
        self.assertGreater(final.extra["tool_calls"], 0)
        self.assertEqual(final.extra["ranked_results"], 1)
        self.assertEqual(final.extra["search_sources_executed"], ["PubMed"])
        self.assertEqual(final.extra["report_source"], "submitted_report")
        self.assertEqual(final.report_markdown, report)
        self.assertNotIn("Perfect!", final.report_markdown or "")

    async def test_timeout_without_submitted_report_runs_deterministic_fallback(self) -> None:
        async def timeout_agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "search_pubmed", query="cardiac surgery ESPB PCA pain", max_results=3)
            await asyncio.sleep(1)
            return {"messages": []}

        events = await self.collect_events(timeout_agent, runtime=FastTimeoutAnthropicRuntime())
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertTrue(final.extra["agentic_fallback"])
        self.assertIn("timed out before submitting a final report", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)

    async def test_submitted_report_survives_late_timeout(self) -> None:
        report = make_valid_report().strip()

        async def timeout_after_submit_agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "search_pubmed", query="cardiac surgery ESPB PCA pain", max_results=3)
            await call_fake_tool(tools, "get_studies", context="clinical")
            await call_fake_tool(tools, "finalize_ranking", ranked_indices=[1], rationale="Most relevant RCT.")
            await call_fake_tool(tools, "submit_report", report_markdown=report)
            await asyncio.sleep(1)
            return {"messages": []}

        events = await self.collect_events(timeout_after_submit_agent, runtime=FastTimeoutAnthropicRuntime())
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "native_sdk_agentic")
        self.assertTrue(final.extra["had_error"])
        self.assertEqual(final.extra["report_source"], "submitted_report")
        self.assertEqual(final.report_markdown, report)

    async def test_deterministic_fallback_translates_when_language_is_non_english(self) -> None:
        translated = ("## 번역 보고서\n\n" + "한국어 번역입니다. " * 80).strip()

        async def no_op_agent(_tools: list[object], _inputs: dict[str, object]) -> object:
            return {"messages": []}

        async def fake_translate(
            _request: RunRequest,
            bridge: AgenticEventBridge,
            _report_markdown: str,
            _target_language: str = "ko",
        ) -> dict[str, object]:
            bridge._intermediate["submitted_report"] = translated
            bridge.set_result(translated)
            return {"status": "ok", "length": len(translated)}

        with patch("medical_deep_research.runtime.tool_translate_report", fake_translate):
            events = await self.collect_events(no_op_agent, request=make_request(language="ko"))

        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]
        artifacts = [event for event in events if event.event_type == EventType.ARTIFACT_CREATED]

        final = completed[-1]
        self.assertEqual(final.report_markdown, translated)
        self.assertEqual(final.extra["translation_status"], "ok")
        self.assertTrue(any(event.artifact_name == "Report (English)" for event in artifacts))

    async def test_submit_report_rejects_short_status_summary(self) -> None:
        bridge = AgenticEventBridge()
        bridge.search_results.append(
            SearchProviderResult(
                source="PubMed",
                query="cardiac surgery ESPB PCA pain",
                studies=[make_ranked_study()],
            )
        )
        bridge.ranked_studies = [make_ranked_study()]

        result = await tool_submit_report(
            make_request(),
            bridge,
            "Perfect! I have successfully completed the literature review. Summary: ESPB may reduce pain [1].",
        )

        self.assertIn("error", result)
        self.assertIn("Report quality gate failed", result["error"])
        self.assertNotIn("submitted_report", bridge._intermediate)
        self.assertIsNone(bridge._result)


if __name__ == "__main__":
    unittest.main()
