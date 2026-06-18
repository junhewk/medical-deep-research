from __future__ import annotations

import asyncio
import sys
import types
import unittest
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from medical_deep_research.models import EventType, RunRequest
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult, VerificationSummary
from medical_deep_research.runtime import LangChainLocalRuntime


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


class AlwaysAvailableLocalRuntime(LangChainLocalRuntime):
    @property
    def sdk_available(self) -> bool:
        return True


@contextmanager
def fake_langgraph_agent(agent_impl: Callable[[list[object], dict[str, object]], Any]) -> object:
    core_tools_module = types.ModuleType("langchain_core.tools")
    core_messages_module = types.ModuleType("langchain_core.messages")
    langchain_core_module = types.ModuleType("langchain_core")
    langchain_openai_module = types.ModuleType("langchain_openai")
    langgraph_module = types.ModuleType("langgraph")
    langgraph_prebuilt_module = types.ModuleType("langgraph.prebuilt")

    class FakeAgent:
        def __init__(self, tools: list[object]) -> None:
            self.tools = tools

        async def ainvoke(self, inputs: dict[str, object]) -> object:
            result = agent_impl(self.tools, inputs)
            if hasattr(result, "__await__"):
                return await result
            return result

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeMessage:
        def __init__(self, content: object = None, **_kwargs: object) -> None:
            self.content = content

    def create_react_agent(_llm: object, tools: list[object], prompt: object) -> FakeAgent:
        assert prompt
        return FakeAgent(tools)

    core_tools_module.tool = fake_lc_tool
    core_messages_module.SystemMessage = FakeMessage
    core_messages_module.HumanMessage = FakeMessage
    langchain_openai_module.ChatOpenAI = FakeChatOpenAI
    langgraph_prebuilt_module.create_react_agent = create_react_agent

    previous = {
        name: sys.modules.get(name)
        for name in (
            "langchain_core",
            "langchain_core.messages",
            "langchain_core.tools",
            "langchain_openai",
            "langgraph",
            "langgraph.prebuilt",
        )
    }
    sys.modules["langchain_core"] = langchain_core_module
    sys.modules["langchain_core.messages"] = core_messages_module
    sys.modules["langchain_core.tools"] = core_tools_module
    sys.modules["langchain_openai"] = langchain_openai_module
    sys.modules["langgraph"] = langgraph_module
    sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_module
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _assert_progress_monotonic(events: list[Any]) -> None:
    """Progress must never decrease, and a completed run must end at 100."""
    previous = 0
    for event in events:
        assert event.progress >= previous, f"progress went backwards: {previous} -> {event.progress}"
        previous = event.progress
    completed = [e for e in events if e.event_type == EventType.RUN_COMPLETED]
    if completed:
        assert completed[-1].progress == 100, f"final progress {completed[-1].progress} != 100"


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


_LEVELS = ["Level I", "Level II", "Level III", "Level IV", "Level V"]


def _make_study(i: int, source: str, level: str) -> EvidenceStudy:
    return EvidenceStudy(
        source=source,
        source_id=f"{source}-{i}",
        title=f"{source} study {i} on ESPB after cardiac surgery",
        abstract=f"Abstract {i} reporting postoperative pain outcomes for ESPB versus PCA.",
        journal="Journal of Test Anesthesia",
        publication_year="2024",
        pmid=f"PM{i:06d}" if source == "PubMed" else None,
        doi=None if source == "PubMed" else f"10.1000/{source.lower()}-{i}",
        citation_count=50 - i,
        evidence_level=level,
        sources=[source],
    )


async def fake_multi_search_source(source: str, query: str, **_kwargs: object) -> SearchProviderResult:
    """Return a large, evidence-level-varied pool so paging/filtering can be exercised."""
    if source == "PubMed":
        studies = [_make_study(i, "PubMed", _LEVELS[i % 5]) for i in range(20)]
    elif source == "OpenAlex":
        studies = [_make_study(i, "OpenAlex", "Level III") for i in range(5)]
    else:
        studies = []
    return SearchProviderResult(source=source, query=query, studies=studies)


async def fake_verify_studies(studies: list[object], **_kwargs: object) -> VerificationSummary:
    return VerificationSummary(
        total_considered=len(studies),
        verified_pmids=len(studies),
        missing_pmids=0,
        missing_from_pubmed=0,
        notes=["fake verification"],
    )


def make_request() -> RunRequest:
    return RunRequest(
        run_id="test-local-run",
        query="Population: cardiac surgery; Intervention: ESPB; Comparison: PCA; Outcome: Pain score",
        query_type="pico",
        mode="detailed",
        provider="local",
        model="qwen3.6-27b",
        language="en",
        api_keys={"local_base_url": "http://127.0.0.1:11434"},
        offline_mode=False,
    )


def make_valid_report() -> str:
    synthesis = " ".join(
        "The ranked trial is directly relevant to the PICO question and reports postoperative pain outcomes [1]."
        for _ in range(90)
    )
    return f"""# Research Report

## Executive Summary
ESPB after cardiac surgery was evaluated against PCA in the searched evidence [1].

## Background
Postoperative pain after cardiac surgery affects mobilization and pulmonary recovery.

## Methods
The agent searched PubMed and screened the retrieved study for population, intervention, comparator, and outcome alignment.

## Results
{synthesis}

## Discussion
The evidence should be interpreted cautiously because the available ranked set is small [1].
The overall GRADE certainty of evidence for the pain outcome is Low, rated down for imprecision [1].

## Conclusions
ESPB may be a useful analgesic adjunct after cardiac surgery.

## References
[1] Test AB. Erector spinae plane block after cardiac surgery randomized trial. Journal of Clinical Anesthesia. 2024. PMID: 12345678.
"""


class LocalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def collect_events(self, agent_impl: Callable[[list[object], dict[str, object]], Any]) -> list[object]:
        with (
            fake_langgraph_agent(agent_impl),
            patch("medical_deep_research.runtime.search_source", fake_search_source),
            patch("medical_deep_research.runtime.verify_studies", fake_verify_studies),
            patch("medical_deep_research.agentic_tools.search_source", fake_search_source),
            patch("medical_deep_research.agentic_tools.verify_studies", fake_verify_studies),
        ):
            events = [event async for event in AlwaysAvailableLocalRuntime().stream_run(make_request())]
        _assert_progress_monotonic(events)
        return events

    async def test_local_runtime_stops_after_accepted_submit_report(self) -> None:
        report = make_valid_report().strip()

        async def agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "search_pubmed", query="cardiac surgery ESPB PCA pain", max_results=3)
            await call_fake_tool(tools, "get_studies", context="clinical")
            await call_fake_tool(tools, "finalize_ranking", ranked_indices=[1], rationale="Most relevant RCT.")
            await call_fake_tool(tools, "submit_report", report_markdown=report)
            await asyncio.sleep(1)
            return {"messages": []}

        events = await self.collect_events(agent)
        final = [event for event in events if event.event_type == EventType.RUN_COMPLETED][-1]

        self.assertFalse(final.extra["had_error"])
        self.assertEqual(final.extra["report_source"], "submitted_report")
        self.assertEqual(final.report_markdown, report)

    async def test_local_runtime_recovers_after_first_rejected_submit_report(self) -> None:
        report = make_valid_report().replace(
            "available ranked set is small [1].",
            "available ranked set is small [1] [12].",
        )

        async def agent(tools: list[object], _inputs: dict[str, object]) -> object:
            await call_fake_tool(tools, "search_pubmed", query="cardiac surgery ESPB PCA pain", max_results=3)
            await call_fake_tool(tools, "get_studies", context="clinical")
            await call_fake_tool(tools, "finalize_ranking", ranked_indices=[1], rationale="Most relevant RCT.")
            await call_fake_tool(tools, "submit_report", report_markdown=report)
            await asyncio.sleep(1)
            return {"messages": []}

        events = await self.collect_events(agent)
        submit_results = [
            event for event in events
            if event.event_type == EventType.TOOL_RESULT and event.tool_name == "submit_report"
        ]
        final = [event for event in events if event.event_type == EventType.RUN_COMPLETED][-1]

        self.assertEqual(len(submit_results), 1)
        self.assertIn("error", submit_results[0].extra["full_tool_output"])
        self.assertFalse(final.extra["had_error"])
        self.assertEqual(final.extra["report_source"], "recovered_agentic_state")
        self.assertIn("Local LLM (fallback)", final.report_markdown or "")


class NewToolBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def _build_tools(self) -> list[object]:
        from medical_deep_research.agentic_tools import AgenticEventBridge
        from medical_deep_research.runtime import _build_langchain_tools

        with fake_langgraph_agent(lambda _t, _i: {"messages": []}):
            return _build_langchain_tools(make_request(), AgenticEventBridge())

    async def _seed_pool(self, tools: list[object]) -> None:
        with (
            patch("medical_deep_research.agentic_tools.search_source", fake_search_source),
            patch("medical_deep_research.agentic_tools.verify_studies", fake_verify_studies),
        ):
            await call_fake_tool(tools, "search_pubmed", query="q", max_results=3)
            await call_fake_tool(tools, "get_studies", context="clinical")

    def _build_tools_with_bridge(self) -> tuple[list[object], Any]:
        from medical_deep_research.agentic_tools import AgenticEventBridge
        from medical_deep_research.runtime import _build_langchain_tools

        bridge = AgenticEventBridge()
        with fake_langgraph_agent(lambda _t, _i: {"messages": []}):
            return _build_langchain_tools(make_request(), bridge), bridge

    async def _seed_multi(self, tools: list[object], *, sources: tuple[str, ...] = ("PubMed",)) -> None:
        names = {"PubMed": "search_pubmed", "OpenAlex": "search_openalex"}
        with (
            patch("medical_deep_research.agentic_tools.search_source", fake_multi_search_source),
            patch("medical_deep_research.agentic_tools.verify_studies", fake_verify_studies),
        ):
            for src in sources:
                await call_fake_tool(tools, names[src], query="q", max_results=25)
            await call_fake_tool(tools, "get_studies", context="clinical")

    async def test_get_studies_returns_top_tier_with_facets(self) -> None:
        import json

        from medical_deep_research.agentic_tools import STUDY_PAGE_SIZE

        tools = self._build_tools_with_bridge()[0]
        await self._seed_multi(tools)
        result = json.loads(await call_fake_tool(tools, "get_studies", context="clinical"))  # type: ignore[arg-type]
        self.assertEqual(result["total"], 20)
        self.assertEqual(result["shown"], STUDY_PAGE_SIZE)
        self.assertTrue(result["has_more"])
        self.assertEqual(len(result["studies"]), STUDY_PAGE_SIZE)
        self.assertEqual(sum(result["counts_by_evidence_level"].values()), 20)

    async def test_browse_before_get_studies_errors(self) -> None:
        import json

        tools = self._build_tools_with_bridge()[0]
        result = json.loads(await call_fake_tool(tools, "browse_studies", page=1))  # type: ignore[arg-type]
        self.assertIn("error", result)

    async def test_browse_pages_pool(self) -> None:
        import json

        from medical_deep_research.agentic_tools import STUDY_PAGE_SIZE

        tools = self._build_tools_with_bridge()[0]
        await self._seed_multi(tools)
        page1 = json.loads(await call_fake_tool(tools, "get_studies", context="clinical"))  # type: ignore[arg-type]
        page2 = json.loads(await call_fake_tool(tools, "browse_studies", page=2))  # type: ignore[arg-type]
        self.assertEqual(page2["shown"], 20 - STUDY_PAGE_SIZE)
        self.assertFalse(page2["has_more"])
        idx1 = {s["idx"] for s in page1["studies"]}
        idx2 = {s["idx"] for s in page2["studies"]}
        self.assertEqual(idx1 & idx2, set())  # stable, disjoint indices across pages
        self.assertEqual(len(idx1 | idx2), 20)

    async def test_browse_filters_by_level_and_source(self) -> None:
        import json

        tools = self._build_tools_with_bridge()[0]
        await self._seed_multi(tools, sources=("PubMed", "OpenAlex"))
        by_level = json.loads(await call_fake_tool(tools, "browse_studies", evidence_level="Level II"))  # type: ignore[arg-type]
        self.assertTrue(by_level["studies"])
        self.assertTrue(all(s["evidence_level"] == "Level II" for s in by_level["studies"]))
        self.assertEqual(by_level["filtered_total"], by_level["counts_by_evidence_level"]["Level II"])

        by_source = json.loads(await call_fake_tool(tools, "browse_studies", source="OpenAlex"))  # type: ignore[arg-type]
        self.assertEqual(by_source["filtered_total"], 5)
        self.assertTrue(all("OpenAlex" in s["sources"] for s in by_source["studies"]))

    async def test_browse_does_not_reset_screening(self) -> None:
        import json

        tools, bridge = self._build_tools_with_bridge()
        await self._seed_multi(tools)
        await call_fake_tool(tools, "screen_studies", included_indices=[1, 2])
        screening_before = dict(bridge.screening)
        pool_before = len(bridge._pre_scored)
        await call_fake_tool(tools, "browse_studies", page=1)
        self.assertEqual(bridge.screening, screening_before)
        self.assertEqual(len(bridge._pre_scored), pool_before)
        self.assertEqual(pool_before, 2)

    async def test_screen_whitelist_drops_unlisted(self) -> None:
        import json

        tools, bridge = self._build_tools_with_bridge()
        await self._seed_multi(tools)
        result = json.loads(await call_fake_tool(tools, "screen_studies", included_indices=[1]))  # type: ignore[arg-type]
        self.assertEqual(result["included"], 1)
        self.assertEqual(result["not_selected"], 19)
        self.assertEqual(len(bridge._pre_scored), 1)

    async def test_screen_empty_includes_errors(self) -> None:
        import json

        tools, bridge = self._build_tools_with_bridge()
        await self._seed_multi(tools)
        result = json.loads(await call_fake_tool(tools, "screen_studies", included_indices=[]))  # type: ignore[arg-type]
        self.assertIn("error", result)
        self.assertEqual(len(bridge._pre_scored), 20)  # pool untouched

    async def test_screen_before_get_studies_errors(self) -> None:
        import json

        tools = self._build_tools()
        result = json.loads(await call_fake_tool(tools, "screen_studies", included_indices=[1]))  # type: ignore[arg-type]
        self.assertIn("error", result)

    async def test_screen_filters_pool_before_ranking(self) -> None:
        import json

        tools = self._build_tools()
        await self._seed_pool(tools)
        result = json.loads(
            await call_fake_tool(
                tools, "screen_studies", included_indices=[1], excluded_indices=[1], exclusion_reasons=["wrong population"]
            )  # type: ignore[arg-type]
        )
        # Whitelist: index 1 is included so it survives (the excluded_indices entry is
        # ignored for an included study); the single-study pool yields no exclusions.
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["included"], 1)
        self.assertEqual(result["excluded"], 0)

    async def test_appraise_normalizes_certainty(self) -> None:
        import json

        tools = self._build_tools()
        await self._seed_pool(tools)
        await call_fake_tool(tools, "finalize_ranking", ranked_indices=[1], rationale="r")
        result = json.loads(
            await call_fake_tool(
                tools,
                "appraise_evidence",
                findings=["Pain reduced", "Mortality unchanged"],
                certainties=["MODERATE", "uncertain"],
                rationales=["RCT", "few events"],
                reference_numbers_csv=["1", "1"],
            )  # type: ignore[arg-type]
        )
        # "MODERATE" normalizes to the bucket; "uncertain" is unparseable -> Low default.
        self.assertEqual(result["certainties"], ["Moderate", "Low"])


if __name__ == "__main__":
    unittest.main()
