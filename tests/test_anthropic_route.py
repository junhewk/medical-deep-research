from __future__ import annotations

import sys
import types
import unittest
from collections.abc import AsyncIterator, Callable
from contextlib import contextmanager
from unittest.mock import patch

from medical_deep_research.models import EventType, RunRequest
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult, VerificationSummary
from medical_deep_research.runtime import AnthropicRuntime


class AlwaysAvailableAnthropicRuntime(AnthropicRuntime):
    @property
    def sdk_available(self) -> bool:
        return True


class FakeClaudeAgentOptions:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class FakeHookMatcher:
    def __init__(self, hooks: list[Callable[..., object]]) -> None:
        self.hooks = hooks


class FakeResultMessage:
    def __init__(self, result: str | None = None, is_error: bool = False, errors: list[str] | None = None) -> None:
        self.result = result
        self.is_error = is_error
        self.errors = errors or []


def fake_tool(name: str, _description: str, _schema: dict[str, object]) -> Callable[[Callable[..., object]], Callable[..., object]]:
    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        setattr(func, "_sdk_tool_name", name)
        return func

    return decorator


def fake_create_sdk_mcp_server(name: str, tools: list[Callable[..., object]]) -> dict[str, object]:
    return {
        "name": name,
        "tools": tools,
        "tools_by_name": {getattr(tool, "_sdk_tool_name"): tool for tool in tools},
    }


@contextmanager
def fake_claude_sdk(query_impl: Callable[..., AsyncIterator[FakeResultMessage]]) -> object:
    sdk_module = types.ModuleType("claude_agent_sdk")
    sdk_module.ClaudeAgentOptions = FakeClaudeAgentOptions
    sdk_module.create_sdk_mcp_server = fake_create_sdk_mcp_server
    sdk_module.query = query_impl
    sdk_module.tool = fake_tool

    types_module = types.ModuleType("claude_agent_sdk.types")
    types_module.HookMatcher = FakeHookMatcher
    types_module.ResultMessage = FakeResultMessage

    previous_sdk = sys.modules.get("claude_agent_sdk")
    previous_types = sys.modules.get("claude_agent_sdk.types")
    sys.modules["claude_agent_sdk"] = sdk_module
    sys.modules["claude_agent_sdk.types"] = types_module
    try:
        yield
    finally:
        if previous_sdk is None:
            sys.modules.pop("claude_agent_sdk", None)
        else:
            sys.modules["claude_agent_sdk"] = previous_sdk
        if previous_types is None:
            sys.modules.pop("claude_agent_sdk.types", None)
        else:
            sys.modules["claude_agent_sdk.types"] = previous_types


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


async def call_fake_tool(options: object, server_name: str, tool_name: str, args: dict[str, object]) -> object:
    namespaced = f"mcp__{server_name}__{tool_name}"
    for matcher in options.hooks.get("PreToolUse", []):
        await matcher.hooks[0]({"tool_name": namespaced, "tool_input": args}, None, None)
    tool = options.mcp_servers[server_name]["tools_by_name"][tool_name]
    result = await tool(args)
    for matcher in options.hooks.get("PostToolUse", []):
        await matcher.hooks[0]({"tool_name": namespaced, "tool_response": result}, None, None)
    return result


def make_request() -> RunRequest:
    return RunRequest(
        run_id="test-run",
        query="Population: cardiac surgery; Intervention: ESPB; Comparison: PCA; Outcome: Pain score",
        query_type="pico",
        mode="detailed",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        api_keys={"anthropic": "test-key"},
        offline_mode=False,
    )


class AnthropicRouteTests(unittest.IsolatedAsyncioTestCase):
    async def collect_events(self, query_impl: Callable[..., AsyncIterator[FakeResultMessage]]) -> list[object]:
        with (
            fake_claude_sdk(query_impl),
            patch("medical_deep_research.runtime.search_source", fake_search_source),
            patch("medical_deep_research.runtime.verify_studies", fake_verify_studies),
            patch("medical_deep_research.agentic_tools.search_source", fake_search_source),
            patch("medical_deep_research.agentic_tools.verify_studies", fake_verify_studies),
        ):
            runtime = AlwaysAvailableAnthropicRuntime()
            return [event async for event in runtime.stream_run(make_request())]

    async def test_no_tool_calls_runs_deterministic_fallback(self) -> None:
        async def no_op_query(**_kwargs: object) -> AsyncIterator[FakeResultMessage]:
            if False:
                yield FakeResultMessage()

        events = await self.collect_events(no_op_query)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        self.assertGreaterEqual(len(completed), 1)
        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertTrue(final.extra["agentic_fallback"])
        self.assertIn("completed without calling any research tools", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)
        self.assertNotIn("not executed", final.report_markdown or "")

    async def test_sdk_error_before_tools_runs_deterministic_fallback_with_reason(self) -> None:
        async def error_query(**_kwargs: object) -> AsyncIterator[FakeResultMessage]:
            if False:
                yield FakeResultMessage()
            raise RuntimeError("missing claude binary")

        events = await self.collect_events(error_query)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertIn("RuntimeError: missing claude binary", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)

    async def test_planning_only_run_falls_back_before_empty_report(self) -> None:
        async def planning_only_query(**kwargs: object) -> AsyncIterator[FakeResultMessage]:
            options = kwargs["options"]
            await call_fake_tool(options, "literature", "plan_search", {"query": make_request().query, "query_type": "pico"})
            yield FakeResultMessage(result="Planning finished but no searches were executed.")

        events = await self.collect_events(planning_only_query)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "deterministic_fallback")
        self.assertIn("completed without executing any search tools", final.extra["fallback_reason"])
        self.assertGreater(final.extra["ranked_results"], 0)

    async def test_tool_using_agentic_run_reports_tool_counts(self) -> None:
        report = (
            "# Research Report\n\n"
            "This report is based on searched evidence for ESPB after cardiac surgery. "
            "The included randomized evidence suggests lower pain scores compared with PCA alone. "
            "References are restricted to the collected search result [1]."
        )

        async def successful_query(**kwargs: object) -> AsyncIterator[FakeResultMessage]:
            options = kwargs["options"]
            await call_fake_tool(options, "literature", "plan_search", {"query": make_request().query, "query_type": "pico"})
            await call_fake_tool(options, "literature", "search_pubmed", {"query": "cardiac surgery ESPB PCA pain", "max_results": 3})
            await call_fake_tool(options, "evidence", "get_studies", {"context": "clinical"})
            await call_fake_tool(options, "evidence", "finalize_ranking", {"ranked_indices": [1], "rationale": "Most relevant RCT."})
            await call_fake_tool(options, "evidence", "verify_studies", {})
            await call_fake_tool(options, "evidence", "submit_report", {"report_markdown": report})
            yield FakeResultMessage(result=report)

        events = await self.collect_events(successful_query)
        completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]

        final = completed[-1]
        self.assertEqual(final.extra["execution_mode"], "native_sdk_agentic")
        self.assertFalse(final.extra["had_error"])
        self.assertGreater(final.extra["tool_calls"], 0)
        self.assertEqual(final.extra["ranked_results"], 1)
        self.assertEqual(final.extra["search_sources_executed"], ["PubMed"])
        self.assertEqual(final.extra["report_source"], "submitted_report")


if __name__ == "__main__":
    unittest.main()
