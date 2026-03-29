from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from .models import EvidenceStudy, SearchProviderResult


NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE_URL = "https://api.openalex.org/works"
SCOPUS_BASE_URL = "https://api.elsevier.com/content/search/scopus"
SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,title,abstract,year,authors,venue,citationCount,externalIds,publicationTypes,journal"
)
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
POLITE_EMAIL = "medical-deep-research@users.noreply.github.com"
LANDMARK_JOURNALS = {
    "new england journal of medicine",
    "nejm",
    "n engl j med",
    "lancet",
    "jama",
    "bmj",
    "circulation",
    "eur heart j",
    "european heart journal",
    "jacc",
    "journal of the american college of cardiology",
    "ann intern med",
    "annals of internal medicine",
    "nature medicine",
}


def is_landmark_journal(journal: str | None) -> bool:
    if not journal:
        return False
    lowered = journal.lower()
    return any(landmark in lowered for landmark in LANDMARK_JOURNALS)


def infer_evidence_level(title: str | None, publication_types: list[str] | None = None) -> str | None:
    lowered = (title or "").lower()
    types = [item.lower() for item in (publication_types or [])]
    if re.search(r"systematic\s*review|meta[\s-]?analysis", lowered):
        return "Level I"
    if "review" in types:
        return "Level I"
    if re.search(r"randomized|randomised|rct\b|clinical trial", lowered):
        return "Level II"
    if re.search(r"cohort|case[\s-]?control|prospective|retrospective", lowered):
        return "Level III"
    if re.search(r"case\s*(series|report)|cross-sectional", lowered):
        return "Level IV"
    return None


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    if not inverted_index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for position in positions:
            words.append((position, word))
    if not words:
        return None
    words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in words)


def _offline_result(source: str, query: str) -> SearchProviderResult:
    return SearchProviderResult(
        source=source,
        query=query,
        skipped=True,
        error="offline mode enabled",
    )


def _network_error(source: str, query: str, exc: Exception) -> SearchProviderResult:
    return SearchProviderResult(
        source=source,
        query=query,
        error=f"{type(exc).__name__}: {exc}",
    )


def _get_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _ebm_boosted_pubmed_query(query: str) -> str:
    """Wrap a PubMed query to prioritize high-evidence study types and recent years."""
    ebm_filter = (
        '("systematic review"[pt] OR "meta-analysis"[pt] OR '
        '"randomized controlled trial"[pt] OR "clinical trial"[pt] OR '
        '"review"[pt] OR "guideline"[pt] OR "practice guideline"[pt])'
    )
    recency = '("2019"[pdat] : "3000"[pdat])'
    # Use boolean preference: (EBM types AND recency AND query) OR (query alone)
    # PubMed "sort=relevance" will rank EBM+recent hits higher
    return f"(({query}) AND {ebm_filter} AND {recency}) OR ({query})"


async def search_pubmed(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("PubMed", query)

    boosted_query = _ebm_boosted_pubmed_query(query)
    params = {
        "db": "pubmed",
        "term": boosted_query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            search_response = await client.get(f"{NCBI_BASE_URL}/esearch.fcgi", params=params)
            search_response.raise_for_status()
            ids = search_response.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return SearchProviderResult(source="PubMed", query=query, studies=[])

            fetch_params = {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
            }
            if api_key:
                fetch_params["api_key"] = api_key
            fetch_response = await client.get(f"{NCBI_BASE_URL}/efetch.fcgi", params=fetch_params)
            fetch_response.raise_for_status()

        root = ET.fromstring(fetch_response.text)
        studies: list[EvidenceStudy] = []
        for article in root.findall(".//PubmedArticle"):
            pmid = _get_text(article.find(".//PMID"))
            title = _get_text(article.find(".//ArticleTitle")) or "Untitled"
            abstract_parts = [
                _get_text(part)
                for part in article.findall(".//Abstract/AbstractText")
                if _get_text(part)
            ]
            authors: list[str] = []
            for author in article.findall(".//AuthorList/Author"):
                last = _get_text(author.find("LastName"))
                fore = _get_text(author.find("ForeName"))
                collective = _get_text(author.find("CollectiveName"))
                name = collective or " ".join(part for part in [fore, last] if part)
                if name:
                    authors.append(name)
            journal = _get_text(article.find(".//Journal/Title")) or "Unknown"
            year = (
                _get_text(article.find(".//ArticleDate/Year"))
                or _get_text(article.find(".//JournalIssue/PubDate/Year"))
            )
            month = _get_text(article.find(".//ArticleDate/Month")) or _get_text(
                article.find(".//JournalIssue/PubDate/Month")
            )
            day = _get_text(article.find(".//ArticleDate/Day")) or _get_text(
                article.find(".//JournalIssue/PubDate/Day")
            )
            publication_date = "-".join(part for part in [year, month, day] if part) or year or None
            publication_types = [
                _get_text(item) for item in article.findall(".//PublicationTypeList/PublicationType") if _get_text(item)
            ]
            mesh_terms = [
                _get_text(item) for item in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName") if _get_text(item)
            ]
            doi = None
            for item in article.findall(".//ArticleIdList/ArticleId"):
                if item.attrib.get("IdType") == "doi":
                    doi = _get_text(item)
                    break
            studies.append(
                EvidenceStudy(
                    source="pubmed",
                    source_id=pmid or title,
                    title=title,
                    abstract=" ".join(abstract_parts) or None,
                    authors=authors,
                    journal=journal,
                    publication_date=publication_date,
                    publication_year=year or None,
                    doi=doi,
                    pmid=pmid or None,
                    citation_count=0,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                    evidence_level=infer_evidence_level(title, publication_types),
                    publication_types=publication_types,
                    mesh_terms=mesh_terms,
                    is_landmark_journal=is_landmark_journal(journal),
                    sources=["pubmed"],
                )
            )
        return SearchProviderResult(source="PubMed", query=query, studies=studies)
    except Exception as exc:
        return _network_error("PubMed", query, exc)


async def search_openalex(query: str, max_results: int = 8, *, offline_mode: bool = False) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("OpenAlex", query)

    params = {
        "search": query,
        "filter": "type:article,from_publication_date:2015-01-01",
        "sort": "relevance_score:desc",
        "per_page": str(max_results),
        "mailto": POLITE_EMAIL,
    }
    headers = {
        "User-Agent": f"MedicalDeepResearch/1.0 (mailto:{POLITE_EMAIL})",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
            response = await client.get(OPENALEX_BASE_URL, params=params)
            response.raise_for_status()
        works = response.json().get("results", [])
        studies: list[EvidenceStudy] = []
        for work in works:
            doi = work.get("doi") or work.get("ids", {}).get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")
            pmid_value = work.get("ids", {}).get("pmid")
            pmid_match = re.search(r"(\d+)$", pmid_value or "")
            pmid = pmid_match.group(1) if pmid_match else None
            journal = (work.get("primary_location") or {}).get("source") or {}
            journal = journal.get("display_name") if isinstance(journal, dict) else "Unknown"
            journal = journal or "Unknown"
            title = work.get("title") or "Untitled"
            studies.append(
                EvidenceStudy(
                    source="openalex",
                    source_id=str(work.get("id", title)).replace("https://openalex.org/", ""),
                    title=title,
                    abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
                    authors=[
                        item.get("author", {}).get("display_name")
                        for item in work.get("authorships", [])
                        if item.get("author", {}).get("display_name")
                    ],
                    journal=journal,
                    publication_date=work.get("publication_date"),
                    publication_year=str(work.get("publication_year")) if work.get("publication_year") else None,
                    doi=doi,
                    pmid=pmid,
                    citation_count=int(work.get("cited_by_count") or 0),
                    url=work.get("id"),
                    evidence_level=infer_evidence_level(title, [work.get("type")] if work.get("type") else []),
                    is_landmark_journal=is_landmark_journal(journal),
                    sources=["openalex"],
                )
            )
        return SearchProviderResult(source="OpenAlex", query=query, studies=studies)
    except Exception as exc:
        return _network_error("OpenAlex", query, exc)


async def search_semantic_scholar(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    fields_of_study: str | None = None,
    offline_mode: bool = False,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("Semantic Scholar", query)

    params = {
        "query": query,
        "limit": str(min(max_results, 100)),
        "fields": SEMANTIC_SCHOLAR_FIELDS,
        "year": "2015-",
        "fieldsOfStudy": fields_of_study or "Medicine",
    }
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
            response = await client.get(SEMANTIC_SCHOLAR_BASE_URL, params=params)
            response.raise_for_status()
        papers = response.json().get("data", [])
        studies: list[EvidenceStudy] = []
        for paper in papers:
            title = paper.get("title") or "Untitled"
            journal_name = (paper.get("journal") or {}).get("name") or paper.get("venue") or "Unknown"
            publication_types = paper.get("publicationTypes") or []
            studies.append(
                EvidenceStudy(
                    source="semantic_scholar",
                    source_id=paper.get("paperId") or title,
                    title=title,
                    abstract=paper.get("abstract"),
                    authors=[author.get("name") for author in paper.get("authors", []) if author.get("name")],
                    journal=journal_name,
                    publication_year=str(paper.get("year")) if paper.get("year") else None,
                    doi=(paper.get("externalIds") or {}).get("DOI"),
                    pmid=(paper.get("externalIds") or {}).get("PubMed"),
                    citation_count=int(paper.get("citationCount") or 0),
                    url=f"https://www.semanticscholar.org/paper/{paper.get('paperId')}" if paper.get("paperId") else None,
                    evidence_level=infer_evidence_level(title, publication_types),
                    publication_types=publication_types,
                    is_landmark_journal=is_landmark_journal(journal_name),
                    sources=["semantic_scholar"],
                )
            )
        return SearchProviderResult(source="Semantic Scholar", query=query, studies=studies)
    except Exception as exc:
        return _network_error("Semantic Scholar", query, exc)


async def search_cochrane(
    query: str,
    max_results: int = 6,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
) -> SearchProviderResult:
    del api_key
    result = await search_pubmed(
        f'{query} AND ("Cochrane Database Syst Rev"[Journal])',
        max_results=max_results,
        offline_mode=offline_mode,
    )
    result.source = "Cochrane"
    for study in result.studies:
        study.source = "cochrane"
        study.sources = ["cochrane"]
        study.evidence_level = "Level I"
    return result


async def search_scopus(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("Scopus", query)
    if not api_key:
        return SearchProviderResult(source="Scopus", query=query, skipped=True, error="Scopus API key not configured")

    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
    params = {
        "query": query,
        "count": str(max_results),
        "sort": "relevancy",
        "date": "2015-2026",
        "view": "COMPLETE",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
            response = await client.get(SCOPUS_BASE_URL, params=params)
            response.raise_for_status()
        entries = response.json().get("search-results", {}).get("entry", []) or []
        studies: list[EvidenceStudy] = []
        for entry in entries:
            identifier = str(entry.get("dc:identifier", "")).replace("SCOPUS_ID:", "")
            title = entry.get("dc:title") or "Untitled"
            journal = entry.get("prism:publicationName") or "Unknown"
            studies.append(
                EvidenceStudy(
                    source="scopus",
                    source_id=identifier or title,
                    title=title,
                    abstract=entry.get("dc:description"),
                    authors=[entry["dc:creator"]] if entry.get("dc:creator") else [],
                    journal=journal,
                    publication_date=entry.get("prism:coverDate"),
                    doi=entry.get("prism:doi"),
                    citation_count=int(entry.get("citedby-count") or 0),
                    url=next(
                        (link.get("@href") for link in entry.get("link", []) if link.get("@ref") == "scopus"),
                        None,
                    ),
                    evidence_level=infer_evidence_level(title),
                    is_landmark_journal=is_landmark_journal(journal),
                    sources=["scopus"],
                )
            )
        return SearchProviderResult(source="Scopus", query=query, studies=studies)
    except Exception as exc:
        return _network_error("Scopus", query, exc)


async def search_source(
    source: str,
    query: str,
    *,
    api_keys: dict[str, str] | None = None,
    max_results: int = 8,
    offline_mode: bool = False,
    domain: str | None = None,
) -> SearchProviderResult:
    key_map = api_keys or {}
    if source == "PubMed":
        return await search_pubmed(query, max_results=max_results, api_key=key_map.get("ncbi"), offline_mode=offline_mode)
    if source == "OpenAlex":
        return await search_openalex(query, max_results=max_results, offline_mode=offline_mode)
    if source == "Semantic Scholar":
        fields = "Medicine" if domain == "clinical" else None
        return await search_semantic_scholar(
            query,
            max_results=max_results,
            api_key=key_map.get("semantic_scholar") or key_map.get("semanticscholar"),
            fields_of_study=fields,
            offline_mode=offline_mode,
        )
    if source == "Cochrane":
        return await search_cochrane(query, max_results=max_results, api_key=key_map.get("cochrane"), offline_mode=offline_mode)
    if source == "Scopus":
        return await search_scopus(query, max_results=max_results, api_key=key_map.get("scopus"), offline_mode=offline_mode)
    return SearchProviderResult(source=source, query=query, skipped=True, error="Unsupported source")


def flatten_studies(results: list[SearchProviderResult]) -> list[EvidenceStudy]:
    studies: list[EvidenceStudy] = []
    for result in results:
        studies.extend(result.studies)
    return studies

