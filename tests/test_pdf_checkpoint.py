from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import select

from medical_deep_research.agentic_tools import AgenticEventBridge, tool_await_user_pdfs, tool_fetch_fulltext, tool_parse_pdf
from medical_deep_research.config import Settings
from medical_deep_research.models import (
    ApprovalRequest,
    ArtifactType,
    EventType,
    ResearchArtifact,
    ResearchRun,
    RunRequest,
)
from medical_deep_research.persistence import AppDatabase
from medical_deep_research.research.models import ScoredStudy
from medical_deep_research.service import ResearchService


class PdfCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_await_user_pdfs_creates_approval_and_continues_after_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                service = ResearchService(database)
                with database.session() as session:
                    session.add(
                        ResearchRun(
                            id="run-pdf-checkpoint",
                            query="diabetes education randomized trial",
                            query_type="free",
                            provider="openai",
                            model="gpt-5-mini",
                            runtime_name="test",
                        )
                    )
                    session.commit()

                bridge = AgenticEventBridge()
                bridge.ranked_studies = [
                    ScoredStudy(
                        source="pubmed",
                        source_id="123",
                        title="Diabetes education randomized trial",
                        journal="Test Journal",
                        publication_year="2025",
                        doi="10.1000/test",
                        pmid="123",
                        evidence_level="Level II",
                        citation_count=5,
                        sources=["pubmed"],
                        evidence_level_score=0.8,
                        citation_score=0.2,
                        recency_score=0.9,
                        composite_score=0.7,
                        reference_number=1,
                    )
                ]
                request = RunRequest(
                    run_id="run-pdf-checkpoint",
                    query="diabetes education randomized trial",
                    query_type="free",
                    mode="detailed",
                    provider="openai",
                    model="gpt-5-mini",
                    database_path=str(settings.db_path),
                )

                task = asyncio.create_task(tool_await_user_pdfs(request, bridge, [1], 0))
                event = await asyncio.wait_for(bridge.queue.get(), timeout=1)
                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual(event.event_type, EventType.APPROVAL_REQUESTED)
                await asyncio.sleep(0.1)
                self.assertFalse(task.done())

                with database.session() as session:
                    approval = session.exec(select(ApprovalRequest)).one()
                    session.add(
                        ResearchArtifact(
                            run_id="run-pdf-checkpoint",
                            artifact_type=ArtifactType.FULLTEXT_UPLOAD.value,
                            name="fulltext_study_1",
                            content_text="uploaded full text",
                        )
                    )
                    session.commit()
                    approval_id = approval.id

                service.resolve_approval(approval_id, approved=True)
                result = await asyncio.wait_for(task, timeout=2)

                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["uploaded_ranks"], [1])
                self.assertEqual(result["missing_ranks"], [])
            finally:
                database.close()

    async def test_fetch_fulltext_requires_discovered_pdf_to_download(self) -> None:
        async def fake_download(_rank: int, _urls: list[str]) -> tuple[bytes | None, str]:
            return None, "none"

        bridge = AgenticEventBridge()
        bridge.ranked_studies = [
            ScoredStudy(
                source="pubmed",
                source_id="123",
                title="Diabetes education randomized trial",
                journal="Test Journal",
                publication_year="2025",
                doi="10.1000/test",
                evidence_level="Level II",
                citation_count=5,
                sources=["pubmed"],
                evidence_level_score=0.8,
                citation_score=0.2,
                recency_score=0.9,
                composite_score=0.7,
                reference_number=1,
            )
        ]
        request = RunRequest(
            run_id="run-download-validation",
            query="diabetes education randomized trial",
            query_type="free",
            mode="detailed",
            provider="openai",
            model="gpt-5-mini",
        )

        with (
            patch("unpywall.Unpywall.get_pdf_link", return_value="https://example.test/paper.pdf"),
            patch("medical_deep_research.agentic_tools._download_pdf_bytes", new=fake_download),
        ):
            result = await tool_fetch_fulltext(request, bridge, allow_user_checkpoint=False)

        self.assertEqual(result["pdfs_found"], 0)
        self.assertEqual(result["discovered_pdf_ranks"], [1])
        self.assertEqual(result["download_failed_ranks"], [1])
        self.assertEqual(result["missing_pdf_ranks"], [1])
        self.assertNotIn(1, bridge._pdf_urls)

    async def test_fetch_fulltext_persists_parseable_download_for_later_parse_tool(self) -> None:
        async def fake_download(_rank: int, _urls: list[str]) -> tuple[bytes | None, str]:
            return b"%PDF-1.4\nfake pdf bytes", "direct_url"

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                with database.session() as session:
                    session.add(
                        ResearchRun(
                            id="run-parseable-download",
                            query="diabetes education randomized trial",
                            query_type="free",
                            provider="openai",
                            model="gpt-5-mini",
                            runtime_name="test",
                        )
                    )
                    session.commit()

                bridge = AgenticEventBridge()
                bridge.ranked_studies = [
                    ScoredStudy(
                        source="pubmed",
                        source_id="123",
                        title="Diabetes education randomized trial",
                        journal="Test Journal",
                        publication_year="2025",
                        doi="10.1000/test",
                        evidence_level="Level II",
                        citation_count=5,
                        sources=["pubmed"],
                        evidence_level_score=0.8,
                        citation_score=0.2,
                        recency_score=0.9,
                        relevance_score=0.8,
                        composite_score=0.7,
                        reference_number=1,
                    )
                ]
                request = RunRequest(
                    run_id="run-parseable-download",
                    query="diabetes education randomized trial",
                    query_type="free",
                    mode="detailed",
                    provider="openai",
                    model="gpt-5-mini",
                    database_path=str(settings.db_path),
                )

                with (
                    patch("unpywall.Unpywall.get_pdf_link", return_value="https://example.test/paper.pdf"),
                    patch("medical_deep_research.agentic_tools._download_pdf_bytes", new=fake_download),
                    patch("medical_deep_research.pdf_text.extract_pdf_text", return_value="downloaded full text"),
                ):
                    result = await tool_fetch_fulltext(request, bridge, allow_user_checkpoint=False)

                self.assertEqual(result["pdfs_found"], 1)
                self.assertEqual(result["validated_pdf_ranks"], [1])
                self.assertEqual(result["parse_failed_ranks"], [])
                self.assertEqual(result["missing_pdf_ranks"], [])

                with database.session() as session:
                    artifact = session.exec(
                        select(ResearchArtifact).where(
                            ResearchArtifact.run_id == "run-parseable-download",
                            ResearchArtifact.name == "fulltext_study_1",
                        )
                    ).one()
                    self.assertEqual(artifact.content_text, "downloaded full text")
                    self.assertIn("downloaded_pdf", artifact.content_json or "")

                fresh_bridge = AgenticEventBridge()
                fresh_bridge.ranked_studies = bridge.ranked_studies
                parsed = await tool_parse_pdf(request, fresh_bridge, 1, allow_user_checkpoint=False)
                self.assertEqual(parsed["source"], "downloaded_pdf")
                self.assertEqual(parsed["fulltext"], "downloaded full text")
            finally:
                database.close()

    async def test_europe_pmc_xml_short_circuits_pdf_chain(self) -> None:
        async def boom_download(_rank: int, _urls: list[str]) -> tuple[bytes | None, str]:
            raise AssertionError("PDF download must not run when XML succeeds")

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                with database.session() as session:
                    session.add(
                        ResearchRun(
                            id="run-xml-first",
                            query="diabetes education randomized trial",
                            query_type="free",
                            provider="openai",
                            model="gpt-5-mini",
                            runtime_name="test",
                        )
                    )
                    session.commit()

                bridge = AgenticEventBridge()
                bridge.ranked_studies = [
                    ScoredStudy(
                        source="pubmed",
                        source_id="123",
                        title="Diabetes education randomized trial",
                        journal="Test Journal",
                        publication_year="2025",
                        doi="10.1000/test",
                        pmcid="PMC9999999",
                        evidence_level="Level II",
                        citation_count=5,
                        sources=["pubmed"],
                        evidence_level_score=0.8,
                        citation_score=0.2,
                        recency_score=0.9,
                        relevance_score=0.8,
                        composite_score=0.7,
                        reference_number=1,
                    )
                ]
                request = RunRequest(
                    run_id="run-xml-first",
                    query="diabetes education randomized trial",
                    query_type="free",
                    mode="detailed",
                    provider="openai",
                    model="gpt-5-mini",
                    database_path=str(settings.db_path),
                )

                async def fake_xml(_pmcid: str) -> str:
                    return "Europe PMC full text body"

                with (
                    patch("medical_deep_research.agentic_tools.fetch_europe_pmc_fulltext_xml", new=fake_xml),
                    patch("medical_deep_research.agentic_tools._download_pdf_bytes", new=boom_download),
                ):
                    result = await tool_fetch_fulltext(request, bridge, allow_user_checkpoint=False)

                self.assertEqual(result["europe_pmc_xml_hits"], 1)
                self.assertEqual(result["pdfs_found"], 1)
                self.assertEqual(result["missing_pdf_ranks"], [])

                fresh_bridge = AgenticEventBridge()
                fresh_bridge.ranked_studies = bridge.ranked_studies
                parsed = await tool_parse_pdf(request, fresh_bridge, 1, allow_user_checkpoint=False)
                self.assertEqual(parsed["source"], "europe_pmc_xml")
                self.assertEqual(parsed["fulltext"], "Europe PMC full text body")
            finally:
                database.close()

    async def test_parse_pdf_download_failure_requests_user_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                service = ResearchService(database)
                with database.session() as session:
                    session.add(
                        ResearchRun(
                            id="run-parse-checkpoint",
                            query="diabetes education randomized trial",
                            query_type="free",
                            provider="openai",
                            model="gpt-5-mini",
                            runtime_name="test",
                        )
                    )
                    session.commit()

                bridge = AgenticEventBridge()
                bridge.ranked_studies = [
                    ScoredStudy(
                        source="pubmed",
                        source_id="123",
                        title="Diabetes education randomized trial",
                        journal="Test Journal",
                        publication_year="2025",
                        doi="10.1000/test",
                        pmid="123",
                        evidence_level="Level II",
                        citation_count=5,
                        sources=["pubmed"],
                        evidence_level_score=0.8,
                        citation_score=0.2,
                        recency_score=0.9,
                        composite_score=0.7,
                        reference_number=1,
                    )
                ]
                request = RunRequest(
                    run_id="run-parse-checkpoint",
                    query="diabetes education randomized trial",
                    query_type="free",
                    mode="detailed",
                    provider="openai",
                    model="gpt-5-mini",
                    database_path=str(settings.db_path),
                )

                task = asyncio.create_task(tool_parse_pdf(request, bridge, 1))
                tool_event = await asyncio.wait_for(bridge.queue.get(), timeout=1)
                self.assertEqual(tool_event.event_type, EventType.TOOL_CALLED)
                self.assertEqual(tool_event.tool_name, "await_user_pdfs")
                approval_event = await asyncio.wait_for(bridge.queue.get(), timeout=1)
                self.assertEqual(approval_event.event_type, EventType.APPROVAL_REQUESTED)
                self.assertFalse(task.done())

                with database.session() as session:
                    approval = session.exec(select(ApprovalRequest)).one()
                    session.add(
                        ResearchArtifact(
                            run_id="run-parse-checkpoint",
                            artifact_type=ArtifactType.FULLTEXT_UPLOAD.value,
                            name="fulltext_study_1",
                            content_text="uploaded full text after download failure",
                        )
                    )
                    session.commit()
                    approval_id = approval.id

                service.resolve_approval(approval_id, approved=True)
                checkpoint_result = await asyncio.wait_for(bridge.queue.get(), timeout=2)
                self.assertEqual(checkpoint_result.event_type, EventType.TOOL_RESULT)
                self.assertEqual(checkpoint_result.tool_name, "await_user_pdfs")
                result = await asyncio.wait_for(task, timeout=2)

                self.assertEqual(result["rank"], 1)
                self.assertEqual(result["source"], "user_upload")
                self.assertEqual(result["fulltext"], "uploaded full text after download failure")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
