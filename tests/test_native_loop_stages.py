from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from medical_deep_research.models import ArtifactType, EventType, RunRequest
from medical_deep_research.research.models import EvidenceStudy, SearchProviderResult, VerificationSummary
from medical_deep_research.runtime import (
    AppraisalOutput,
    AppraisedFinding,
    NativeSDKRuntime,
    RewindDecisionOutput,
    ScreeningExclusion,
    ScreeningOutput,
    SearchGuidanceOutput,
)


async def fake_search_source(source: str, query: str, **_kwargs: object) -> SearchProviderResult:
    studies = []
    if source == "PubMed":
        studies = [
            EvidenceStudy(
                source="PubMed",
                source_id=f"100{i}",
                title=f"Study {i} on the intervention",
                abstract="Randomized trial abstract.",
                journal="Journal of Clinical Anesthesia",
                publication_year="2024",
                pmid=f"100{i}",
                citation_count=10 + i,
                evidence_level="Level II" if i < 2 else "Level IV",
                publication_types=["Randomized Controlled Trial"],
                sources=["PubMed"],
            )
            for i in range(4)
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


class ScriptedNativeRuntime(NativeSDKRuntime):
    provider = "openai"
    runtime_name = "Scripted Native"
    runtime_engine = "scripted"
    native_agent_name = "Scripted Agent"
    max_search_iterations = 1

    @property
    def sdk_available(self) -> bool:
        return True

    def _should_fallback(self, request: RunRequest) -> bool:
        return False

    async def _run_structured_checkpoint(
        self,
        request: RunRequest,
        *,
        task_name: str,
        instructions: str,
        prompt: str,
        output_model: type,
    ) -> Any:
        if output_model is SearchGuidanceOutput:
            return SearchGuidanceOutput(strategy_summary="ok")
        if output_model is ScreeningOutput:
            # Exclude reference 3 with a reason; everything else included.
            return ScreeningOutput(
                included_reference_numbers=[1, 2, 4],
                exclusions=[ScreeningExclusion(reference_number=3, reason="Wrong population")],
                rationale="Kept the on-topic RCTs.",
            )
        if output_model is AppraisalOutput:
            return AppraisalOutput(
                findings=[
                    AppraisedFinding(
                        finding="The intervention reduces pain.",
                        certainty="Moderate",
                        rationale="RCT evidence with some imprecision.",
                        reference_numbers=[1],
                    )
                ],
                overall_note="Overall moderate certainty.",
            )
        if output_model is RewindDecisionOutput:
            return RewindDecisionOutput(should_rewind=False, rationale="Sufficient coverage.")
        raise AssertionError(f"Unexpected checkpoint output_model: {output_model}")


def make_request() -> RunRequest:
    return RunRequest(
        run_id="test-native-loop",
        query="Population: cardiac surgery; Intervention: ESPB; Comparison: PCA; Outcome: Pain score",
        query_type="pico",
        mode="detailed",
        provider="openai",
        model="gpt-5-mini",
        language="en",
        offline_mode=False,
    )


class NativeLoopStageTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self) -> list[Any]:
        with (
            patch("medical_deep_research.runtime.search_source", fake_search_source),
            patch("medical_deep_research.runtime.verify_studies", fake_verify_studies),
        ):
            return [event async for event in ScriptedNativeRuntime().stream_run(make_request())]

    async def test_screening_filters_renumbers_and_emits_artifacts(self) -> None:
        events = await self._run()

        screening_artifacts = [
            e for e in events if e.artifact_type == ArtifactType.SCREENING_DECISIONS
        ]
        self.assertEqual(len(screening_artifacts), 1)
        screening = screening_artifacts[0].artifact_json
        self.assertEqual(screening["included"], 3)
        self.assertEqual([ex["reference_number"] for ex in screening["excluded"]], [3])

        # Ranked artifact reflects screening: only 3 studies, renumbered 1..3.
        ranked_artifacts = [e for e in events if e.artifact_type == ArtifactType.RANKED_RESULTS]
        ranked = ranked_artifacts[-1].artifact_json["studies"]
        self.assertEqual(len(ranked), 3)
        self.assertEqual([s["reference_number"] for s in ranked], [1, 2, 3])

        appraisal_artifacts = [
            e for e in events if e.artifact_type == ArtifactType.APPRAISAL_SUMMARY
        ]
        self.assertEqual(len(appraisal_artifacts), 1)
        self.assertEqual(appraisal_artifacts[0].artifact_json["findings"][0]["certainty"], "Moderate")

    async def test_progress_is_monotonic_and_completes_at_100(self) -> None:
        events = await self._run()
        progresses = [e.progress for e in events]
        for earlier, later in zip(progresses, progresses[1:]):
            self.assertLessEqual(earlier, later)
        completed = [e for e in events if e.event_type == EventType.RUN_COMPLETED]
        self.assertEqual(completed[-1].progress, 100)

    async def test_screening_failure_includes_all(self) -> None:
        class FailingScreenRuntime(ScriptedNativeRuntime):
            async def _run_structured_checkpoint(self, request, *, task_name, instructions, prompt, output_model):  # type: ignore[no-untyped-def]
                if output_model is ScreeningOutput:
                    raise RuntimeError("provider down")
                return await super()._run_structured_checkpoint(
                    request, task_name=task_name, instructions=instructions, prompt=prompt, output_model=output_model
                )

        with (
            patch("medical_deep_research.runtime.search_source", fake_search_source),
            patch("medical_deep_research.runtime.verify_studies", fake_verify_studies),
        ):
            events = [event async for event in FailingScreenRuntime().stream_run(make_request())]

        screening = [e for e in events if e.artifact_type == ArtifactType.SCREENING_DECISIONS][0].artifact_json
        self.assertEqual(screening["included"], 4)  # nothing excluded on failure
        self.assertIn("error", screening)


if __name__ == "__main__":
    unittest.main()
