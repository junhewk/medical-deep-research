from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from medical_deep_research.models import EventType, RunRequest
from medical_deep_research.runtime import build_runtime


DEFAULT_QUERY = "Population: cardiac surgery; Intervention: ESPB; Comparison: PCA; Outcome: Pain score"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _api_keys_from_env() -> dict[str, str]:
    keys = {
        "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
        "ncbi": os.getenv("MDR_NCBI_API_KEY", ""),
        "scopus": os.getenv("MDR_SCOPUS_API_KEY", ""),
        "semantic_scholar": os.getenv("MDR_SEMANTIC_SCHOLAR_API_KEY", ""),
    }
    return {name: value for name, value in keys.items() if value}


async def run_eval(args: argparse.Namespace) -> int:
    api_keys = _api_keys_from_env()
    if not api_keys.get("anthropic"):
        print("ANTHROPIC_API_KEY is required for the Anthropic route eval.", file=sys.stderr)
        return 2

    runtime = build_runtime("anthropic")
    request = RunRequest(
        run_id="anthropic-route-eval",
        query=args.query,
        query_type=args.query_type,
        mode="detailed",
        provider="anthropic",
        model=args.model,
        api_keys=api_keys,
        offline_mode=False,
    )

    events = [event async for event in runtime.stream_run(request)]
    completed = [event for event in events if event.event_type == EventType.RUN_COMPLETED]
    if not completed:
        print("No run_completed event was emitted.", file=sys.stderr)
        return 1

    final = completed[-1]
    extra: dict[str, Any] = final.extra or {}
    summary = {
        "execution_mode": extra.get("execution_mode"),
        "tool_calls": extra.get("tool_calls"),
        "had_error": extra.get("had_error"),
        "error_message": extra.get("error_message"),
        "fallback_reason": extra.get("fallback_reason"),
        "search_sources_executed": extra.get("search_sources_executed"),
        "source_counts": extra.get("source_counts"),
        "ranked_results": extra.get("ranked_results"),
        "report_source": extra.get("report_source"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    failures: list[str] = []
    if extra.get("execution_mode") != "native_sdk_agentic":
        failures.append(f"expected native_sdk_agentic, got {extra.get('execution_mode')!r}")
    if not extra.get("tool_calls"):
        failures.append("expected at least one Anthropic tool call")
    sources = set(extra.get("search_sources_executed") or [])
    if not ({"PubMed", "OpenAlex"} & sources):
        failures.append("expected PubMed or OpenAlex search execution")
    if not extra.get("ranked_results"):
        failures.append("expected ranked_results > 0")
    report = final.report_markdown or ""
    if "not executed" in report or "deterministic fallback" in report.lower():
        failures.append("final report indicates fallback or unexecuted databases")
    if extra.get("had_error"):
        failures.append(f"agentic route had error: {extra.get('error_message')}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print("Anthropic route eval passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an opt-in Anthropic agentic route smoke eval.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--query-type", default="pico", choices=["free", "pico", "pcc"])
    parser.add_argument("--model", default=os.getenv("MDR_EVAL_ANTHROPIC_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    return asyncio.run(run_eval(args))


if __name__ == "__main__":
    raise SystemExit(main())
