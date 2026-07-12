from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import re
import xml.etree.ElementTree as ET

import httpx

from .connectors import canonical_source_name, is_rankable_evidence_study
from .http import RateLimit, get_json
from .models import EvidenceStudy, SearchProviderResult


NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE_URL = "https://api.openalex.org/works"
SCOPUS_BASE_URL = "https://api.elsevier.com/content/search/scopus"
SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
EUROPE_PMC_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_REST_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CROSSREF_BASE_URL = "https://api.crossref.org/works"
CLINICALTRIALS_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,title,abstract,year,authors,venue,citationCount,externalIds,publicationTypes,journal"
)
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
POLITE_EMAIL = "medical-deep-research@users.noreply.github.com"
USER_AGENT = f"MedicalDeepResearch/2.9.12 (mailto:{POLITE_EMAIL})"
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
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        message = f"{source} returned HTTP {status_code}; run continued without {source} results"
    else:
        message = str(exc).split(" for url ", 1)[0].strip()
        message = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return SearchProviderResult(
        source=source,
        query=query,
        error=message,
    )


def _clean_api_key(value: str | None) -> str:
    key = (value or "").strip().strip("\"'")
    key = key.lstrip("\ufeff").strip()
    header_match = re.match(r"^(?:x-els-apikey|x-api-key|api[-_\s]*key)\s*:\s*(.+)$", key, re.IGNORECASE)
    if header_match:
        key = header_match.group(1).strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return re.sub(r"\s+", "", key)


def _resolve_year_window(start_year: int | None) -> tuple[int, int]:
    end_year = datetime.now().year
    if start_year is None:
        start_year = end_year - 4  # default: last 5 years inclusive
    start_year = max(1900, min(end_year, int(start_year)))
    return start_year, end_year


def _scopus_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return "Scopus API key was rejected by Elsevier; skipped Scopus as if no API key was configured"
    if status_code == 429:
        return "Scopus quota or rate limit was reached; skipped Scopus as if no API key was configured"
    if 500 <= status_code <= 599:
        return f"Scopus returned HTTP {status_code} from Elsevier Search API; skipped Scopus as if no API key was configured"
    return f"Scopus returned HTTP {status_code} from Elsevier Search API; skipped Scopus as if no API key was configured"


def _scopus_keyed_skip(query: str, error: str) -> SearchProviderResult:
    return SearchProviderResult(source="Scopus", query=query, skipped=True, error=error)


async def _ncbi_get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, object],
    attempts: int = 3,
) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(attempts):
        response = await client.get(url, params=params)
        if response.status_code not in {429, 500, 502, 503, 504}:
            return response
        if attempt < attempts - 1:
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 1.0 + attempt
            except ValueError:
                delay = 1.0 + attempt
            await asyncio.sleep(min(delay, 5.0))
    assert response is not None
    return response


def _get_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
    return doi or None


def _first_string(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _crossref_date_parts(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return None
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return None
    return "-".join(str(part) for part in first if part is not None) or None


def _summary_article_id(summary: dict[str, object], id_type: str) -> str | None:
    for item in summary.get("articleids") or []:
        if not isinstance(item, dict):
            continue
        if item.get("idtype") == id_type and item.get("value"):
            return str(item["value"])
    return None


def _ebm_boosted_pubmed_query(query: str, start_year: int) -> str:
    """Wrap a PubMed query to prioritize high-evidence study types and recent years."""
    ebm_filter = (
        '("systematic review"[pt] OR "meta-analysis"[pt] OR '
        '"randomized controlled trial"[pt] OR "clinical trial"[pt] OR '
        '"review"[pt] OR "guideline"[pt] OR "practice guideline"[pt])'
    )
    recency = f'("{start_year}"[pdat] : "3000"[pdat])'
    # Use boolean preference: (EBM types AND recency AND query) OR (query alone)
    # PubMed "sort=relevance" will rank EBM+recent hits higher
    return f"(({query}) AND {ebm_filter} AND {recency}) OR ({query})"


async def search_pubmed(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("PubMed", query)

    start_year_value, _ = _resolve_year_window(start_year)
    boosted_query = _ebm_boosted_pubmed_query(query, start_year_value)
    params = {
        "db": "pubmed",
        "term": boosted_query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
        "tool": "medical-deep-research",
        "email": POLITE_EMAIL,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            search_response = await _ncbi_get_with_retries(
                client,
                f"{NCBI_BASE_URL}/esearch.fcgi",
                params=params,
            )
            search_response.raise_for_status()
            ids = search_response.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return SearchProviderResult(source="PubMed", query=query, studies=[])

            fetch_params = {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
                "tool": "medical-deep-research",
                "email": POLITE_EMAIL,
            }
            if api_key:
                fetch_params["api_key"] = api_key
            fetch_response = await _ncbi_get_with_retries(
                client,
                f"{NCBI_BASE_URL}/efetch.fcgi",
                params=fetch_params,
            )
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
            journal_abbrev = _get_text(article.find(".//Journal/ISOAbbreviation"))
            volume = _get_text(article.find(".//JournalIssue/Volume"))
            issue = _get_text(article.find(".//JournalIssue/Issue"))
            pages = _get_text(article.find(".//Pagination/MedlinePgn")) or _get_text(
                article.find(".//MedlinePgn")
            )
            if not pages:
                start_page = _get_text(article.find(".//Pagination/StartPage")) or _get_text(
                    article.find(".//StartPage")
                )
                end_page = _get_text(article.find(".//Pagination/EndPage")) or _get_text(
                    article.find(".//EndPage")
                )
                if start_page:
                    pages = f"{start_page}-{end_page}" if end_page else start_page
            year = (
                _get_text(article.find(".//ArticleDate/Year"))
                or _get_text(article.find(".//JournalIssue/PubDate/Year"))
            )
            if not year:
                # MedlineDate holds free-text dates like "2024 Nov-Dec" with no <Year> element.
                medline_date = _get_text(article.find(".//JournalIssue/PubDate/MedlineDate"))
                if medline_date:
                    year_match = re.search(r"\b(\d{4})\b", medline_date)
                    if year_match:
                        year = year_match.group(1)
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
            pmcid = None
            for item in article.findall("./PubmedData/ArticleIdList/ArticleId"):
                if item.attrib.get("IdType") == "doi":
                    doi = _get_text(item)
                elif item.attrib.get("IdType") == "pmc":
                    pmcid = _get_text(item)
            if not doi:
                for item in article.findall(".//Article/ELocationID"):
                    if item.attrib.get("EIdType") == "doi":
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
                    journal_abbrev=journal_abbrev or None,
                    volume=volume or None,
                    issue=issue or None,
                    pages=pages or None,
                    publication_date=publication_date,
                    publication_year=year or None,
                    doi=doi,
                    pmid=pmid or None,
                    pmcid=pmcid or None,
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


async def search_openalex(
    query: str,
    max_results: int = 8,
    *,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("OpenAlex", query)

    start_year_value, _ = _resolve_year_window(start_year)
    params = {
        "search": query,
        "filter": f"type:article,from_publication_date:{start_year_value}-01-01",
        "sort": "relevance_score:desc",
        "per_page": str(max_results),
        "mailto": POLITE_EMAIL,
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    try:
        payload = await get_json(
            OPENALEX_BASE_URL,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT,
            rate_limit=RateLimit(0.1),
            looks_valid=lambda data: isinstance(data, dict) and "results" in data,
        )
        works = payload.get("results", []) if isinstance(payload, dict) else []
        studies: list[EvidenceStudy] = []
        for work in works:
            ids = work.get("ids", {}) if isinstance(work.get("ids"), dict) else {}
            doi = _normalize_doi(work.get("doi") or ids.get("doi"))
            pmid_value = ids.get("pmid")
            pmid_match = re.search(r"(\d+)$", pmid_value or "")
            pmid = pmid_match.group(1) if pmid_match else None
            pmcid_value = ids.get("pmcid")
            pmcid_match = re.search(r"(PMC\d+)$", pmcid_value or "")
            pmcid = pmcid_match.group(1) if pmcid_match else None
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
                    pmcid=pmcid,
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
    start_year: int | None = None,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("Semantic Scholar", query)

    api_key = _clean_api_key(api_key)
    if not api_key:
        return SearchProviderResult(
            source="Semantic Scholar",
            query=query,
            skipped=True,
            error="Semantic Scholar API key not configured",
        )

    start_year_value, _ = _resolve_year_window(start_year)
    params = {
        "query": query,
        "limit": str(min(max_results, 100)),
        "fields": SEMANTIC_SCHOLAR_FIELDS,
        "year": f"{start_year_value}-",
    }
    requested_fields_of_study = fields_of_study or "Medicine"
    if requested_fields_of_study:
        params["fieldsOfStudy"] = requested_fields_of_study
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "x-api-key": api_key,
    }

    async def _get_with_retries(client: httpx.AsyncClient, request_params: dict[str, object]) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(4):
            response = await client.get(SEMANTIC_SCHOLAR_BASE_URL, params=request_params)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
            except ValueError:
                delay = 1.5 * (attempt + 1)
            await asyncio.sleep(min(delay, 10.0))
        assert response is not None
        return response

    def _parse_papers(response: httpx.Response) -> list[dict[str, object]]:
        payload = response.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return data if isinstance(data, list) else []

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
            response = await _get_with_retries(client, params)
            if response.status_code in {400, 422} and "fieldsOfStudy" in params:
                fallback_params = dict(params)
                fallback_params.pop("fieldsOfStudy", None)
                response = await _get_with_retries(client, fallback_params)
            response.raise_for_status()
            papers = _parse_papers(response)
            if not papers and "fieldsOfStudy" in params:
                fallback_params = dict(params)
                fallback_params.pop("fieldsOfStudy", None)
                response = await _get_with_retries(client, fallback_params)
                response.raise_for_status()
                papers = _parse_papers(response)
        studies: list[EvidenceStudy] = []
        for paper in papers:
            title = paper.get("title") or "Untitled"
            journal_name = (paper.get("journal") or {}).get("name") or paper.get("venue") or "Unknown"
            publication_types = paper.get("publicationTypes") or []
            external_ids = paper.get("externalIds") or {}
            studies.append(
                EvidenceStudy(
                    source="semantic_scholar",
                    source_id=paper.get("paperId") or title,
                    title=title,
                    abstract=paper.get("abstract"),
                    authors=[author.get("name") for author in paper.get("authors", []) if author.get("name")],
                    journal=journal_name,
                    publication_year=str(paper.get("year")) if paper.get("year") else None,
                    doi=external_ids.get("DOI"),
                    pmid=external_ids.get("PubMed"),
                    pmcid=external_ids.get("PubMedCentral") or external_ids.get("PMC"),
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
    start_year: int | None = None,
) -> SearchProviderResult:
    result = await search_pubmed(
        f'({query}) AND "Cochrane Database Syst Rev"[Journal]',
        max_results=max_results,
        api_key=api_key,
        offline_mode=offline_mode,
        start_year=start_year,
    )
    result.source = "Cochrane"
    for study in result.studies:
        study.source = "cochrane"
        study.sources = ["cochrane"]
        study.evidence_level = "Level I"
    return result


async def search_pmc(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("PMC", query)

    start_year_value, _ = _resolve_year_window(start_year)
    bounded_query = f'({query}) AND open access[filter] AND ("{start_year_value}"[pdat] : "3000"[pdat])'
    params = {
        "db": "pmc",
        "term": bounded_query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
        "tool": "medical-deep-research",
        "email": POLITE_EMAIL,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            search_response = await _ncbi_get_with_retries(
                client,
                f"{NCBI_BASE_URL}/esearch.fcgi",
                params=params,
            )
            search_response.raise_for_status()
            ids = search_response.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return SearchProviderResult(source="PMC", query=query, studies=[])

            common_params = {
                "db": "pmc",
                "id": ",".join(ids),
                "retmode": "json",
                "tool": "medical-deep-research",
                "email": POLITE_EMAIL,
            }
            if api_key:
                common_params["api_key"] = api_key
            summary_response = await _ncbi_get_with_retries(
                client,
                f"{NCBI_BASE_URL}/esummary.fcgi",
                params=common_params,
            )
            summary_response.raise_for_status()

        result = summary_response.json().get("result", {})
        studies: list[EvidenceStudy] = []
        for pmc_id in ids:
            summary = result.get(pmc_id) or {}
            title = _clean_text(str(summary.get("title") or "")) or "Untitled"
            authors = [
                item.get("name")
                for item in summary.get("authors") or []
                if isinstance(item, dict) and item.get("name")
            ]
            journal = str(summary.get("fulljournalname") or summary.get("source") or "PMC")
            pubdate = str(summary.get("pubdate") or "")
            year_match = re.search(r"\b(\d{4})\b", pubdate)
            publication_types = [str(value) for value in summary.get("pubtype") or []]
            pmid = _summary_article_id(summary, "pmid")
            doi = _normalize_doi(_summary_article_id(summary, "doi") or str(summary.get("elocationid") or ""))
            pmcid = _summary_article_id(summary, "pmcid")
            if not pmcid:
                pmcid = f"PMC{pmc_id}" if not str(pmc_id).upper().startswith("PMC") else str(pmc_id)
            studies.append(
                EvidenceStudy(
                    source="pmc",
                    source_id=pmcid,
                    title=title,
                    abstract=None,
                    authors=authors,
                    journal=journal,
                    publication_date=pubdate or None,
                    publication_year=year_match.group(1) if year_match else None,
                    doi=doi,
                    pmid=pmid,
                    pmcid=pmcid,
                    citation_count=0,
                    url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/",
                    evidence_level=infer_evidence_level(title, publication_types),
                    publication_types=publication_types,
                    is_landmark_journal=is_landmark_journal(journal),
                    sources=["pmc"],
                )
            )
        return SearchProviderResult(source="PMC", query=query, studies=studies)
    except Exception as exc:
        return _network_error("PMC", query, exc)


def europe_pmc_study_from_entry(entry: dict, *, preprint: bool = False) -> EvidenceStudy:
    """Map one Europe PMC REST result entry (search or citation network) to a study."""
    title = _clean_text(entry.get("title")) or "Untitled"
    source_id = entry.get("pmid") or entry.get("pmcid") or entry.get("id") or title
    authors = [
        part.strip()
        for part in str(entry.get("authorString") or "").split(",")
        if part.strip()
    ]
    publication_types = [
        item.strip()
        for item in str(entry.get("pubType") or "").split(";")
        if item.strip()
    ]
    pmcid = entry.get("pmcid")
    if pmcid and not str(pmcid).upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    url = f"https://europepmc.org/article/MED/{source_id}"
    fulltext_urls = entry.get("fullTextUrlList")
    if isinstance(fulltext_urls, dict):
        url_items = fulltext_urls.get("fullTextUrl")
        if isinstance(url_items, list) and url_items:
            first_url = url_items[0]
            if isinstance(first_url, dict) and first_url.get("url"):
                url = str(first_url["url"])
    abstract = _clean_text(entry.get("abstractText"))
    journal = _clean_text(entry.get("journalTitle"))
    if preprint:
        abstract = f"[PREPRINT — not peer reviewed] {abstract}" if abstract else "[PREPRINT — not peer reviewed]"
        journal = journal or "Preprint server (not peer reviewed)"
        publication_types = sorted(set(publication_types) | {"preprint"})
    source = "preprints" if preprint else "europe_pmc"
    return EvidenceStudy(
        source=source,
        source_id=str(source_id),
        title=title,
        abstract=abstract,
        authors=authors,
        journal=journal or "Europe PMC",
        publication_date=entry.get("firstPublicationDate"),
        publication_year=str(entry.get("pubYear")) if entry.get("pubYear") else None,
        doi=_normalize_doi(entry.get("doi")),
        pmid=entry.get("pmid"),
        pmcid=pmcid,
        citation_count=int(entry.get("citedByCount") or 0),
        url=url,
        evidence_level="Level V" if preprint else infer_evidence_level(title, publication_types),
        publication_types=publication_types,
        is_landmark_journal=False if preprint else is_landmark_journal(entry.get("journalTitle")),
        sources=[source],
    )


async def _search_europe_pmc_impl(
    query: str,
    max_results: int,
    *,
    offline_mode: bool,
    start_year: int | None,
    preprints: bool,
) -> SearchProviderResult:
    source_name = "Preprints" if preprints else "Europe PMC"
    if offline_mode:
        return _offline_result(source_name, query)

    start_year_value, end_year_value = _resolve_year_window(start_year)
    preprint_clause = "AND SRC:PPR" if preprints else "NOT SRC:PPR"
    europe_query = (
        f"({query}) AND FIRST_PDATE:[{start_year_value}-01-01 TO {end_year_value}-12-31] "
        f"{preprint_clause}"
    )
    params = {
        "query": europe_query,
        "format": "json",
        "resultType": "core",
        "pageSize": str(max_results),
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(EUROPE_PMC_BASE_URL, params=params)
            response.raise_for_status()
        results = response.json().get("resultList", {}).get("result", [])
        studies = [europe_pmc_study_from_entry(entry, preprint=preprints) for entry in results]
        return SearchProviderResult(source=source_name, query=query, studies=studies)
    except Exception as exc:
        return _network_error(source_name, query, exc)


async def search_europe_pmc(
    query: str,
    max_results: int = 8,
    *,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    return await _search_europe_pmc_impl(
        query,
        max_results,
        offline_mode=offline_mode,
        start_year=start_year,
        preprints=False,
    )


async def search_preprints(
    query: str,
    max_results: int = 8,
    *,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    """Search preprint servers (medRxiv/bioRxiv/etc.) via Europe PMC SRC:PPR.

    Results are explicitly labeled as preprints and forced to Level V so they
    can never outrank peer-reviewed evidence.
    """
    return await _search_europe_pmc_impl(
        query,
        max_results,
        offline_mode=offline_mode,
        start_year=start_year,
        preprints=True,
    )


async def search_crossref(
    query: str,
    max_results: int = 8,
    *,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("Crossref", query)

    start_year_value, end_year_value = _resolve_year_window(start_year)
    params = {
        "query.bibliographic": query,
        "filter": (
            f"from-pub-date:{start_year_value}-01-01,"
            f"until-pub-date:{end_year_value}-12-31,type:journal-article"
        ),
        "rows": str(max(1, min(max_results, 100))),
        "mailto": POLITE_EMAIL,
    }
    try:
        payload = await get_json(
            CROSSREF_BASE_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
            rate_limit=RateLimit(0.1),
            looks_valid=lambda data: isinstance(data, dict)
            and isinstance(data.get("message"), dict),
        )
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        items = message.get("items", []) if isinstance(message, dict) else []
        studies: list[EvidenceStudy] = []
        for item in items:
            doi = _normalize_doi(item.get("DOI"))
            title = _clean_text(_first_string(item.get("title"))) or "Untitled"
            authors = []
            for author in item.get("author") or []:
                if not isinstance(author, dict):
                    continue
                name = " ".join(
                    part for part in [author.get("given"), author.get("family")] if part
                ).strip()
                if name:
                    authors.append(name)
            pubdate = (
                _crossref_date_parts(item.get("published-print"))
                or _crossref_date_parts(item.get("published-online"))
                or _crossref_date_parts(item.get("issued"))
            )
            year_match = re.match(r"(\d{4})", pubdate or "")
            studies.append(
                EvidenceStudy(
                    source="crossref",
                    source_id=doi or str(item.get("URL") or title),
                    title=title,
                    abstract=_clean_text(_first_string(item.get("abstract"))),
                    authors=authors,
                    journal=_clean_text(_first_string(item.get("container-title"))) or "Crossref",
                    publication_date=pubdate,
                    publication_year=year_match.group(1) if year_match else None,
                    doi=doi,
                    citation_count=int(item.get("is-referenced-by-count") or 0),
                    url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
                    evidence_level=infer_evidence_level(title, [str(item.get("type") or "")]),
                    publication_types=[str(item.get("type") or "journal-article")],
                    is_landmark_journal=is_landmark_journal(_first_string(item.get("container-title"))),
                    sources=["crossref"],
                )
            )
        return SearchProviderResult(source="Crossref", query=query, studies=studies)
    except Exception as exc:
        return _network_error("Crossref", query, exc)


async def search_scopus(
    query: str,
    max_results: int = 8,
    *,
    api_key: str | None = None,
    offline_mode: bool = False,
    start_year: int | None = None,
    scopus_view: str = "STANDARD",
) -> SearchProviderResult:
    if offline_mode:
        return _offline_result("Scopus", query)
    api_key = _clean_api_key(api_key)
    if not api_key:
        return _scopus_keyed_skip(query, "Scopus API key not configured")

    start_year_value, end_year_value = _resolve_year_window(start_year)
    # Inline PUBYEAR clause; Scopus's `date=YYYY-YYYY` URL param triggers
    # an XSL transform 500 error in the Search API.
    bounded_query = (
        f"{query} AND PUBYEAR > {start_year_value - 1} AND PUBYEAR < {end_year_value + 1}"
    )

    requested_view = (scopus_view or "STANDARD").upper()
    if requested_view not in {"STANDARD", "COMPLETE"}:
        requested_view = "STANDARD"
    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
    params = {
        "query": bounded_query,
        "count": str(max_results),
        "sort": "relevancy",
        "view": requested_view,
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
            response = await client.get(SCOPUS_BASE_URL, params=params)
            if 500 <= response.status_code <= 599:
                fallback_params = {**params, "view": "STANDARD"}
                response = await client.get(SCOPUS_BASE_URL, params=fallback_params)
            if response.status_code >= 400:
                return _scopus_keyed_skip(query, _scopus_error_message(response.status_code))
        entries = response.json().get("search-results", {}).get("entry", []) or []
        studies: list[EvidenceStudy] = []
        for entry in entries:
            identifier = str(entry.get("dc:identifier", "")).replace("SCOPUS_ID:", "")
            title = entry.get("dc:title") or "Untitled"
            journal = entry.get("prism:publicationName") or "Unknown"
            cover_date = entry.get("prism:coverDate")
            year_match = re.match(r"(\d{4})", cover_date or "")
            publication_year = year_match.group(1) if year_match else None
            studies.append(
                EvidenceStudy(
                    source="scopus",
                    source_id=identifier or title,
                    title=title,
                    abstract=entry.get("dc:description"),
                    authors=[entry["dc:creator"]] if entry.get("dc:creator") else [],
                    journal=journal,
                    publication_date=cover_date,
                    publication_year=publication_year,
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
    except httpx.HTTPStatusError as exc:
        return _scopus_keyed_skip(query, _scopus_error_message(exc.response.status_code))
    except Exception as exc:
        fallback_error = str(exc).split(" for url ", 1)[0].strip()
        fallback_error = fallback_error or type(exc).__name__
        return _scopus_keyed_skip(
            query,
            f"Scopus API request failed ({type(exc).__name__}: {fallback_error}); skipped Scopus as if no API key was configured",
        )


_CLINICALTRIALS_FIELDS = ",".join(
    [
        "NCTId",
        "BriefTitle",
        "OverallStatus",
        "Phase",
        "StudyType",
        "DesignAllocation",
        "BriefSummary",
        "StartDate",
        "PrimaryCompletionDate",
        "LeadSponsorName",
        "Condition",
        "InterventionName",
        "ResultsFirstPostDate",
        "EnrollmentCount",
    ]
)


async def search_clinical_trials(
    query: str,
    max_results: int = 8,
    *,
    offline_mode: bool = False,
    start_year: int | None = None,
) -> SearchProviderResult:
    """Search the ClinicalTrials.gov registry (REST API v2, no key required).

    Registry records are not publications: they surface ongoing/completed
    trials, and registered-but-unpublished trials are a publication-bias
    signal for the report's Discussion section.
    """
    if offline_mode:
        return _offline_result("ClinicalTrials.gov", query)

    start_year_value, _ = _resolve_year_window(start_year)
    params = {
        "query.term": query,
        "pageSize": str(max(1, min(max_results, 100))),
        "fields": _CLINICALTRIALS_FIELDS,
        "filter.advanced": f"AREA[StartDate]RANGE[{start_year_value}-01-01,MAX]",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(CLINICALTRIALS_BASE_URL, params=params)
            response.raise_for_status()
        entries = response.json().get("studies", [])
        studies: list[EvidenceStudy] = []
        for entry in entries:
            protocol = entry.get("protocolSection") or {}
            identification = protocol.get("identificationModule") or {}
            status_module = protocol.get("statusModule") or {}
            design = protocol.get("designModule") or {}
            description = protocol.get("descriptionModule") or {}
            sponsor = ((protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name")
            conditions = (protocol.get("conditionsModule") or {}).get("conditions") or []
            interventions = [
                item.get("name")
                for item in ((protocol.get("armsInterventionsModule") or {}).get("interventions") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            nct_id = identification.get("nctId")
            if not nct_id:
                continue
            title = _clean_text(identification.get("briefTitle")) or "Untitled trial"
            status = str(status_module.get("overallStatus") or "UNKNOWN")
            phases = design.get("phases") or []
            phase = ", ".join(str(item) for item in phases) or None
            study_type = str(design.get("studyType") or "")
            allocation = str(((design.get("designInfo") or {}).get("allocation")) or "")
            randomized_interventional = study_type == "INTERVENTIONAL" and allocation == "RANDOMIZED"
            start_date = ((status_module.get("startDateStruct") or {}).get("date")) or None
            year_match = re.match(r"(\d{4})", start_date or "")
            has_results = bool(entry.get("hasResults")) or bool(
                (status_module.get("resultsFirstPostDateStruct") or {}).get("date")
            )
            summary_parts = [
                f"Registry record ({status}{f', {phase}' if phase else ''})."
            ]
            if conditions:
                summary_parts.append("Conditions: " + "; ".join(str(item) for item in conditions[:5]) + ".")
            if interventions:
                summary_parts.append("Interventions: " + "; ".join(interventions[:5]) + ".")
            brief_summary = _clean_text(description.get("briefSummary"))
            if brief_summary:
                summary_parts.append(brief_summary)
            studies.append(
                EvidenceStudy(
                    source="clinicaltrials",
                    source_id=str(nct_id),
                    title=title,
                    abstract=" ".join(summary_parts),
                    authors=[sponsor] if sponsor else [],
                    journal="ClinicalTrials.gov Registry",
                    publication_date=start_date,
                    publication_year=year_match.group(1) if year_match else None,
                    citation_count=0,
                    url=f"https://clinicaltrials.gov/study/{nct_id}",
                    evidence_level="Level II" if randomized_interventional else None,
                    publication_types=["registry_record", status] + ([phase] if phase else []),
                    sources=["clinicaltrials"],
                    trial_status=status,
                    trial_phase=phase,
                    has_published_results=has_results,
                )
            )
        return SearchProviderResult(source="ClinicalTrials.gov", query=query, studies=studies)
    except Exception as exc:
        return _network_error("ClinicalTrials.gov", query, exc)


SearchSourceHandler = Callable[
    [str, dict[str, str], int, bool, str | None, int | None, str],
    Awaitable[SearchProviderResult],
]


async def _search_pubmed_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del domain, scopus_view
    return await search_pubmed(
        query,
        max_results=max_results,
        api_key=key_map.get("ncbi"),
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_pmc_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del domain, scopus_view
    return await search_pmc(
        query,
        max_results=max_results,
        api_key=key_map.get("ncbi"),
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_europe_pmc_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del key_map, domain, scopus_view
    return await search_europe_pmc(
        query,
        max_results=max_results,
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_openalex_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del key_map, domain, scopus_view
    return await search_openalex(
        query,
        max_results=max_results,
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_crossref_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del key_map, domain, scopus_view
    return await search_crossref(
        query,
        max_results=max_results,
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_semantic_scholar_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del scopus_view
    fields = "Medicine" if domain == "clinical" else None
    return await search_semantic_scholar(
        query,
        max_results=max_results,
        api_key=key_map.get("semantic_scholar") or key_map.get("semanticscholar"),
        fields_of_study=fields,
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_cochrane_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del domain, scopus_view
    return await search_cochrane(
        query,
        max_results=max_results,
        api_key=key_map.get("cochrane") or key_map.get("ncbi"),
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_scopus_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del domain
    return await search_scopus(
        query,
        max_results=max_results,
        api_key=key_map.get("scopus"),
        offline_mode=offline_mode,
        start_year=start_year,
        scopus_view=scopus_view,
    )


async def _search_clinical_trials_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del key_map, domain, scopus_view
    return await search_clinical_trials(
        query,
        max_results=max_results,
        offline_mode=offline_mode,
        start_year=start_year,
    )


async def _search_preprints_source(
    query: str,
    key_map: dict[str, str],
    max_results: int,
    offline_mode: bool,
    domain: str | None,
    start_year: int | None,
    scopus_view: str,
) -> SearchProviderResult:
    del key_map, domain, scopus_view
    return await search_preprints(
        query,
        max_results=max_results,
        offline_mode=offline_mode,
        start_year=start_year,
    )


_SEARCH_SOURCE_HANDLERS: dict[str, SearchSourceHandler] = {
    "PubMed": _search_pubmed_source,
    "PMC": _search_pmc_source,
    "Europe PMC": _search_europe_pmc_source,
    "OpenAlex": _search_openalex_source,
    "Crossref": _search_crossref_source,
    "Semantic Scholar": _search_semantic_scholar_source,
    "Cochrane": _search_cochrane_source,
    "Scopus": _search_scopus_source,
    "ClinicalTrials.gov": _search_clinical_trials_source,
    "Preprints": _search_preprints_source,
}


async def search_source(
    source: str,
    query: str,
    *,
    api_keys: dict[str, str] | None = None,
    max_results: int = 8,
    offline_mode: bool = False,
    domain: str | None = None,
    start_year: int | None = None,
    scopus_view: str = "STANDARD",
) -> SearchProviderResult:
    key_map = api_keys or {}
    canonical = canonical_source_name(source)
    handler = _SEARCH_SOURCE_HANDLERS.get(canonical or "")
    if handler is None:
        return SearchProviderResult(source=source, query=query, skipped=True, error="Unsupported source")
    return await handler(
        query,
        key_map,
        max_results,
        offline_mode,
        domain,
        start_year,
        scopus_view,
    )


def flatten_studies(
    results: list[SearchProviderResult],
    *,
    rankable_only: bool = True,
) -> list[EvidenceStudy]:
    studies: list[EvidenceStudy] = []
    for result in results:
        if rankable_only:
            studies.extend(study for study in result.studies if is_rankable_evidence_study(study))
        else:
            studies.extend(result.studies)
    return studies
