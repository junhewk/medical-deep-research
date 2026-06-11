"""Citation-graph traversal (snowballing) for systematic evidence search.

Backward snowballing fetches a study's reference list; forward snowballing
fetches the papers citing it.  Europe PMC's citation network is used when the
study has a PMID, with OpenAlex as fallback when only a DOI is available.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import httpx

from .models import EvidenceStudy, SearchProviderResult
from .search import (
    EUROPE_PMC_REST_BASE_URL,
    HTTP_TIMEOUT,
    OPENALEX_BASE_URL,
    POLITE_EMAIL,
    USER_AGENT,
    _clean_text,
    _normalize_doi,
    infer_evidence_level,
    is_landmark_journal,
    reconstruct_abstract,
)

SnowballDirection = Literal["references", "citations"]

_log = logging.getLogger(__name__)


def _europe_pmc_link_study(entry: dict, direction: SnowballDirection) -> EvidenceStudy:
    """Map one Europe PMC citation-network entry (slimmer than search results)."""
    title = _clean_text(entry.get("title")) or "Untitled"
    pmid = str(entry.get("id") or "") or None
    authors = [
        part.strip()
        for part in str(entry.get("authorString") or "").split(",")
        if part.strip()
    ]
    journal = _clean_text(entry.get("journalAbbreviation") or entry.get("journalTitle"))
    year = str(entry.get("pubYear")) if entry.get("pubYear") else None
    source = f"europe_pmc_{direction}"
    return EvidenceStudy(
        source=source,
        source_id=pmid or title,
        title=title,
        abstract=_clean_text(entry.get("abstractText")),
        authors=authors,
        journal=journal or "Europe PMC",
        publication_year=year,
        doi=_normalize_doi(entry.get("doi")),
        pmid=pmid,
        citation_count=int(entry.get("citedByCount") or 0),
        url=f"https://europepmc.org/article/MED/{pmid}" if pmid else None,
        evidence_level=infer_evidence_level(title, [str(entry.get("citationType") or "")]),
        is_landmark_journal=is_landmark_journal(journal),
        sources=[source],
    )


async def fetch_europe_pmc_links(
    pmid: str,
    direction: SnowballDirection,
    max_results: int = 15,
) -> list[EvidenceStudy]:
    url = f"{EUROPE_PMC_REST_BASE_URL}/MED/{pmid}/{direction}/1/{max(1, min(max_results, 100))}/json"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(url, params={"format": "json"})
        response.raise_for_status()
    payload = response.json()
    key = "referenceList" if direction == "references" else "citationList"
    inner_key = "reference" if direction == "references" else "citation"
    entries = (payload.get(key) or {}).get(inner_key) or []
    return [_europe_pmc_link_study(entry, direction) for entry in entries if isinstance(entry, dict)]


def _openalex_work_study(work: dict, direction: SnowballDirection) -> EvidenceStudy:
    ids = work.get("ids", {}) if isinstance(work.get("ids"), dict) else {}
    doi = _normalize_doi(work.get("doi") or ids.get("doi"))
    pmid_match = re.search(r"(\d+)$", ids.get("pmid") or "")
    pmcid_match = re.search(r"(PMC\d+)$", ids.get("pmcid") or "")
    journal = (work.get("primary_location") or {}).get("source") or {}
    journal = journal.get("display_name") if isinstance(journal, dict) else None
    title = work.get("title") or "Untitled"
    source = f"openalex_{direction}"
    return EvidenceStudy(
        source=source,
        source_id=str(work.get("id", title)).replace("https://openalex.org/", ""),
        title=title,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=[
            item.get("author", {}).get("display_name")
            for item in work.get("authorships", [])
            if item.get("author", {}).get("display_name")
        ],
        journal=journal or "Unknown",
        publication_date=work.get("publication_date"),
        publication_year=str(work.get("publication_year")) if work.get("publication_year") else None,
        doi=doi,
        pmid=pmid_match.group(1) if pmid_match else None,
        pmcid=pmcid_match.group(1) if pmcid_match else None,
        citation_count=int(work.get("cited_by_count") or 0),
        url=work.get("id"),
        evidence_level=infer_evidence_level(title, [str(work.get("type"))] if work.get("type") else []),
        is_landmark_journal=is_landmark_journal(journal),
        sources=[source],
    )


async def fetch_openalex_links(
    doi: str,
    direction: SnowballDirection,
    max_results: int = 15,
) -> list[EvidenceStudy]:
    limit = max(1, min(max_results, 50))
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers) as client:
        work_response = await client.get(
            f"{OPENALEX_BASE_URL}/https://doi.org/{doi}", params={"mailto": POLITE_EMAIL}
        )
        work_response.raise_for_status()
        work = work_response.json()
        if direction == "references":
            referenced = [
                str(item).replace("https://openalex.org/", "")
                for item in (work.get("referenced_works") or [])[:limit]
            ]
            if not referenced:
                return []
            batch_response = await client.get(
                OPENALEX_BASE_URL,
                params={
                    "filter": f"openalex_id:{'|'.join(referenced)}",
                    "per_page": str(limit),
                    "mailto": POLITE_EMAIL,
                },
            )
        else:
            work_id = str(work.get("id", "")).replace("https://openalex.org/", "")
            if not work_id:
                return []
            batch_response = await client.get(
                OPENALEX_BASE_URL,
                params={
                    "filter": f"cites:{work_id}",
                    "sort": "cited_by_count:desc",
                    "per_page": str(limit),
                    "mailto": POLITE_EMAIL,
                },
            )
        batch_response.raise_for_status()
    works = batch_response.json().get("results", [])
    return [_openalex_work_study(item, direction) for item in works if isinstance(item, dict)]


async def snowball(
    study: EvidenceStudy,
    direction: SnowballDirection,
    max_results: int = 15,
) -> SearchProviderResult:
    """Fetch the citation neighborhood of a study; Europe PMC first, OpenAlex fallback."""
    label = f"Snowball {direction}"
    query = f"{direction} of {study.pmid or study.doi or study.title}"
    studies: list[EvidenceStudy] = []
    errors: list[str] = []
    if study.pmid:
        try:
            studies = await fetch_europe_pmc_links(study.pmid, direction, max_results)
        except Exception as exc:
            errors.append(f"Europe PMC: {type(exc).__name__}: {exc}")
            _log.warning("Europe PMC snowball failed for PMID %s: %s", study.pmid, exc)
    if not studies and study.doi:
        try:
            studies = await fetch_openalex_links(study.doi, direction, max_results)
        except Exception as exc:
            errors.append(f"OpenAlex: {type(exc).__name__}: {exc}")
            _log.warning("OpenAlex snowball failed for DOI %s: %s", study.doi, exc)
    error = "; ".join(errors) if errors and not studies else None
    if not study.pmid and not study.doi:
        error = "Study has neither PMID nor DOI; citation network is unavailable."
    return SearchProviderResult(source=label, query=query, studies=studies, error=error)
