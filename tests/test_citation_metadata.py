from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from medical_deep_research.agentic_tools import _inject_reference_list
from medical_deep_research.research import (
    enrich_report_citations,
    format_vancouver_citation,
    render_reference_entries,
)
from medical_deep_research.research.models import ScoredStudy
from medical_deep_research.research.search import NCBI_BASE_URL, search_pubmed
from medical_deep_research.research.verification import (
    _apply_citation_meta,
    _esummary_entry_to_meta,
)


def _scored(**overrides: object) -> ScoredStudy:
    base: dict[str, object] = dict(
        source="pubmed",
        source_id="1",
        title="Some title",
        evidence_level_score=0.0,
        citation_score=0.0,
        recency_score=0.0,
        composite_score=0.0,
        reference_number=1,
    )
    base.update(overrides)
    return ScoredStudy(**base)


# --- PubMed XML parsing -------------------------------------------------------

ESEARCH_JSON = {"esearchresult": {"idlist": ["39242043"]}}

EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39242043</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <Volume>367</Volume>
            <Issue>3</Issue>
            <PubDate><Year>2024</Year><Month>Dec</Month></PubDate>
          </JournalIssue>
          <Title>Journal of affective disorders</Title>
          <ISOAbbreviation>J Affect Disord</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Social media use, mental health and sleep.</ArticleTitle>
        <Pagination><MedlinePgn>701-712</MedlinePgn></Pagination>
        <Abstract><AbstractText>Background and findings.</AbstractText></Abstract>
        <AuthorList>
          <Author><LastName>Ahmed</LastName><ForeName>Oli</ForeName></Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1016/j.jad.2024.08.193</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

EFETCH_XML_MEDLINE_DATE = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>1</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <Volume>34</Volume>
            <PubDate><MedlineDate>2024 Nov-Dec</MedlineDate></PubDate>
          </JournalIssue>
          <Title>Example Journal</Title>
          <ISOAbbreviation>Ex J</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Date fallback test.</ArticleTitle>
        <Pagination><MedlinePgn>10-20</MedlinePgn></Pagination>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _json_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", f"{NCBI_BASE_URL}/esearch.fcgi"))


def _xml_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, request=httpx.Request("GET", f"{NCBI_BASE_URL}/efetch.fcgi"))


class FakeAsyncClient:
    responses: list[httpx.Response] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, _url: str, *, params: dict[str, object]) -> httpx.Response:
        return FakeAsyncClient.responses.pop(0)


class PubMedParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_volume_issue_pages_abbrev(self) -> None:
        FakeAsyncClient.responses = [_json_response(ESEARCH_JSON), _xml_response(EFETCH_XML)]
        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_pubmed("adolescent social media", max_results=1)

        self.assertEqual(len(result.studies), 1)
        study = result.studies[0]
        self.assertEqual(study.volume, "367")
        self.assertEqual(study.issue, "3")
        self.assertEqual(study.pages, "701-712")
        self.assertEqual(study.journal_abbrev, "J Affect Disord")
        self.assertEqual(study.publication_year, "2024")
        self.assertEqual(study.doi, "10.1016/j.jad.2024.08.193")

    async def test_medline_date_year_fallback(self) -> None:
        FakeAsyncClient.responses = [
            _json_response({"esearchresult": {"idlist": ["1"]}}),
            _xml_response(EFETCH_XML_MEDLINE_DATE),
        ]
        with patch("medical_deep_research.research.search.httpx.AsyncClient", FakeAsyncClient):
            result = await search_pubmed("x", max_results=1)

        study = result.studies[0]
        self.assertEqual(study.publication_year, "2024")
        self.assertEqual(study.volume, "34")
        self.assertEqual(study.pages, "10-20")


# --- Vancouver rendering ------------------------------------------------------


class VancouverRenderTests(unittest.TestCase):
    def test_full_citation(self) -> None:
        study = _scored(
            title="Social media use, mental health and sleep: A systematic review with meta-analyses",
            authors=["Ahmed O", "Walsh EI", "Dawel A", "Alateeq K", "Espinoza Oyarce DA", "Cherbuin N"],
            journal="Journal of affective disorders",
            journal_abbrev="J Affect Disord",
            volume="367",
            pages="701-712",
            publication_year="2024",
            doi="10.1016/j.jad.2024.08.193",
            pmid="39242043",
        )
        self.assertEqual(
            format_vancouver_citation(study),
            "Ahmed O, Walsh EI, Dawel A, Alateeq K, Espinoza Oyarce DA, Cherbuin N. "
            "Social media use, mental health and sleep: A systematic review with meta-analyses. "
            "J Affect Disord. 2024;367:701-712. doi:10.1016/j.jad.2024.08.193. PMID: 39242043.",
        )

    def test_seventh_author_becomes_et_al(self) -> None:
        study = _scored(authors=[f"Sur{n} A" for n in range(7)], title="T", journal_abbrev="J", publication_year="2024")
        self.assertIn(", et al.", format_vancouver_citation(study))

    def test_missing_volume_pages_not_fabricated(self) -> None:
        study = _scored(
            title="No volume data",
            authors=["Smith A"],
            journal_abbrev="J Test",
            publication_year="2023",
            pmid="999",
        )
        rendered = format_vancouver_citation(study)
        self.assertEqual(rendered, "Smith A. No volume data. J Test. 2023. PMID: 999.")
        self.assertNotIn("(", rendered)  # no fabricated issue parentheses

    def test_reference_entries_numbered_by_reference_number(self) -> None:
        studies = [
            _scored(reference_number=1, title="A", journal_abbrev="J", publication_year="2020"),
            _scored(reference_number=2, title="B", journal_abbrev="J", publication_year="2021"),
        ]
        entries = render_reference_entries(studies)
        self.assertTrue(entries.startswith("[1] "))
        self.assertIn("\n\n[2] ", entries)


# --- esummary enrichment ------------------------------------------------------


class EnrichmentTests(unittest.IsolatedAsyncioTestCase):
    ESUMMARY_ENTRY = {
        "volume": "34",
        "issue": "5",
        "pages": "1511-1527",
        "pubdate": "2025 May",
        "source": "Eur Child Adolesc Psychiatry",
        "fulljournalname": "European child & adolescent psychiatry",
        "authors": [
            {"name": "Conte G", "authtype": "Author"},
            {"name": "Di Iorio G", "authtype": "Author"},
        ],
        "articleids": [{"idtype": "doi", "value": "10.1007/s00787-024-02858-0"}],
    }

    def test_esummary_entry_to_meta(self) -> None:
        meta = _esummary_entry_to_meta(self.ESUMMARY_ENTRY)
        self.assertEqual(meta["volume"], "34")
        self.assertEqual(meta["issue"], "5")
        self.assertEqual(meta["pages"], "1511-1527")
        self.assertEqual(meta["year"], "2025")
        self.assertEqual(meta["journal_abbrev"], "Eur Child Adolesc Psychiatry")
        self.assertEqual(meta["authors"], ["Conte G", "Di Iorio G"])
        self.assertEqual(meta["doi"], "10.1007/s00787-024-02858-0")

    def test_apply_citation_meta_fills_missing_and_canonicalizes_authors(self) -> None:
        study = _scored(authors=["Giuseppe Conte"], volume=None, issue=None, pages=None)
        _apply_citation_meta(study, _esummary_entry_to_meta(self.ESUMMARY_ENTRY))
        self.assertEqual(study.volume, "34")
        self.assertEqual(study.issue, "5")
        self.assertEqual(study.pages, "1511-1527")
        self.assertEqual(study.journal_abbrev, "Eur Child Adolesc Psychiatry")
        # canonical esummary authors overwrite the raw parsed authors
        self.assertEqual(study.authors, ["Conte G", "Di Iorio G"])

    def test_apply_citation_meta_canonical_wins_over_search_values(self) -> None:
        # Search-time values can be wrong (e.g. a DOI from a secondary provider that points at
        # a different paper); the authoritative esummary/Crossref record must win.
        study = _scored(volume="99", issue="9", pages="1-2", doi="10.9999/wrong.doi")
        _apply_citation_meta(study, _esummary_entry_to_meta(self.ESUMMARY_ENTRY))
        self.assertEqual(study.volume, "34")
        self.assertEqual(study.doi, "10.1007/s00787-024-02858-0")

    async def test_enrich_report_citations_uses_pmid_metadata(self) -> None:
        study = _scored(pmid="40000001", volume=None)
        with patch(
            "medical_deep_research.research.verification.fetch_pubmed_citation_metadata",
            new=AsyncMock(return_value={"40000001": _esummary_entry_to_meta(self.ESUMMARY_ENTRY)}),
        ):
            await enrich_report_citations([study], api_keys={}, offline_mode=False)
        self.assertEqual(study.volume, "34")
        self.assertEqual(study.pages, "1511-1527")

    async def test_enrich_report_citations_skips_when_offline(self) -> None:
        study = _scored(pmid="40000001", volume=None)
        fetch = AsyncMock()
        with patch("medical_deep_research.research.verification.fetch_pubmed_citation_metadata", new=fetch):
            await enrich_report_citations([study], api_keys={}, offline_mode=True)
        fetch.assert_not_awaited()
        self.assertIsNone(study.volume)


# --- deterministic reference injection ---------------------------------------


class ReferenceInjectionTests(unittest.TestCase):
    def test_replaces_model_written_references(self) -> None:
        study = _scored(
            reference_number=1,
            title="Real title",
            authors=["Ahmed O"],
            journal_abbrev="J Affect Disord",
            volume="367",
            pages="701-712",
            publication_year="2024",
            pmid="39242043",
        )
        report = (
            "# Report\n\n## Results\nFinding [1].\n\n"
            "## 7. References\n\n[1] Wrong Author. Made up title. Bad Journal. 2099;1(1):1-2.\n"
        )
        out = _inject_reference_list(report, [study])
        # original heading style preserved, fabricated citation replaced with verified one
        self.assertIn("## 7. References", out)
        self.assertIn("[1] Ahmed O. Real title. J Affect Disord. 2024;367:701-712. PMID: 39242043.", out)
        self.assertNotIn("Made up title", out)
        self.assertNotIn("2099", out)

    def test_appends_references_when_absent(self) -> None:
        study = _scored(reference_number=1, title="T", journal_abbrev="J", publication_year="2024", pmid="5")
        out = _inject_reference_list("# Report\n\n## Results\nFinding [1].", [study])
        self.assertIn("## References", out)
        self.assertIn("[1] T. J. 2024. PMID: 5.", out)


if __name__ == "__main__":
    unittest.main()
