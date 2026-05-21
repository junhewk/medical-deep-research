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
            return [event async for event in AlwaysAvailableLocalRuntime().stream_run(make_request())]

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


if __name__ == "__main__":
    unittest.main()
