from __future__ import annotations

import re
from typing import Any

import httpx

from .models import ScoredStudy, VerificationDetail, VerificationSummary
from .search import HTTP_TIMEOUT, NCBI_BASE_URL, POLITE_EMAIL


def empty_verification_summary(note: str | None = None) -> VerificationSummary:
    notes = [note] if note else []
    return VerificationSummary(
        total_considered=0,
        verified_pmids=0,
        missing_pmids=0,
        missing_from_pubmed=0,
        details=[],
        notes=notes,
    )


async def verify_pmid_in_pubmed(pmid: str, api_key: str | None = None) -> tuple[bool | None, str | None]:
    params = {"db": "pubmed", "id": pmid, "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(f"{NCBI_BASE_URL}/esummary.fcgi", params=params)
        response.raise_for_status()
        result = response.json().get("result", {}).get(pmid)
        if not result or result.get("error"):
            return False, result.get("error") if result else "PMID not found in PubMed"
    return True, None


async def verify_pmids_in_pubmed(
    pmids: list[str],
    api_key: str | None = None,
) -> dict[str, tuple[bool | None, str | None]]:
    unique_pmids = list(dict.fromkeys(pmid for pmid in pmids if pmid))
    if not unique_pmids:
        return {}

    params = {"db": "pubmed", "id": ",".join(unique_pmids), "retmode": "json"}
    if api_key:
        params["api_key"] = api_key

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(f"{NCBI_BASE_URL}/esummary.fcgi", params=params)
        response.raise_for_status()

    payload = response.json().get("result", {})
    results: dict[str, tuple[bool | None, str | None]] = {}
    for pmid in unique_pmids:
        entry = payload.get(pmid)
        if not entry or entry.get("error"):
            issue = entry.get("error") if entry else "PMID not found in PubMed"
            results[pmid] = (False, issue)
        else:
            results[pmid] = (True, None)
    return results


def _extract_year(value: Any) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(\d{4})\b", str(value))
    return match.group(1) if match else None


def _esummary_entry_to_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """Map a PubMed esummary result entry to canonical citation fields."""
    meta: dict[str, Any] = {}
    if entry.get("volume"):
        meta["volume"] = str(entry["volume"]).strip()
    if entry.get("issue"):
        meta["issue"] = str(entry["issue"]).strip()
    if entry.get("pages"):
        meta["pages"] = str(entry["pages"]).strip()
    year = _extract_year(entry.get("pubdate")) or _extract_year(entry.get("epubdate"))
    if year:
        meta["year"] = year
    # esummary "source" is the NLM/ISO journal abbreviation; fulljournalname is the long title.
    if entry.get("source"):
        meta["journal_abbrev"] = str(entry["source"]).strip()
    if entry.get("fulljournalname"):
        meta["journal"] = str(entry["fulljournalname"]).strip()
    authors = [
        str(author["name"]).strip()
        for author in (entry.get("authors") or [])
        if isinstance(author, dict) and author.get("name")
    ]
    if authors:
        meta["authors"] = authors
    for article_id in entry.get("articleids") or []:
        if isinstance(article_id, dict) and article_id.get("idtype") == "doi" and article_id.get("value"):
            meta.setdefault("doi", str(article_id["value"]).strip())
    return meta


async def fetch_pubmed_citation_metadata(
    pmids: list[str],
    api_key: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch canonical citation metadata for PMIDs via PubMed esummary."""
    unique_pmids = list(dict.fromkeys(pmid for pmid in pmids if pmid))
    if not unique_pmids:
        return {}
    params = {"db": "pubmed", "id": ",".join(unique_pmids), "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(f"{NCBI_BASE_URL}/esummary.fcgi", params=params)
        response.raise_for_status()
    payload = response.json().get("result", {})
    out: dict[str, dict[str, Any]] = {}
    for pmid in unique_pmids:
        entry = payload.get(pmid)
        if entry and not entry.get("error"):
            out[pmid] = _esummary_entry_to_meta(entry)
    return out


def _crossref_author(author: dict[str, Any]) -> str:
    family = str(author.get("family") or "").strip()
    given = str(author.get("given") or "").strip()
    if not family:
        return str(author.get("name") or "").strip()
    initials = "".join(
        part[0].upper() for part in re.split(r"[\s.\-]+", given) if part and part[0].isalpha()
    )
    return f"{family} {initials}".strip()


async def fetch_crossref_citation_metadata(doi: str) -> dict[str, Any] | None:
    """Fetch canonical citation metadata for a DOI via the Crossref REST API."""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip())
    if not doi:
        return None
    headers = {"User-Agent": f"medical-deep-research/1.0 (mailto:{POLITE_EMAIL})"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(f"https://api.crossref.org/works/{doi}", headers=headers)
        if response.status_code != 200:
            return None
        message = response.json().get("message", {})
    meta: dict[str, Any] = {}
    if message.get("volume"):
        meta["volume"] = str(message["volume"]).strip()
    if message.get("issue"):
        meta["issue"] = str(message["issue"]).strip()
    if message.get("page"):
        meta["pages"] = str(message["page"]).strip()
    for date_key in ("published-print", "published", "issued", "published-online"):
        date_parts = (message.get(date_key) or {}).get("date-parts")
        if date_parts and date_parts[0] and date_parts[0][0]:
            meta["year"] = str(date_parts[0][0])
            break
    short_title = message.get("short-container-title") or []
    full_title = message.get("container-title") or []
    if short_title:
        meta["journal_abbrev"] = short_title[0]
    if full_title:
        meta["journal"] = full_title[0]
    authors = [author for author in (_crossref_author(a) for a in message.get("author") or []) if author]
    if authors:
        meta["authors"] = authors
    return meta or None


def _apply_citation_meta(study: ScoredStudy, meta: dict[str, Any] | None) -> None:
    # meta comes from the authoritative record (PubMed esummary keyed by PMID, or Crossref
    # keyed by the study's DOI), so it WINS over the heterogeneous, sometimes-wrong values
    # captured at search time (we have seen mismatched DOIs/years from secondary providers).
    if not meta:
        return
    if meta.get("volume"):
        study.volume = meta["volume"]
    if meta.get("issue"):
        study.issue = meta["issue"]
    if meta.get("pages"):
        study.pages = meta["pages"]
    if meta.get("journal_abbrev"):
        study.journal_abbrev = meta["journal_abbrev"]
    if meta.get("year"):
        study.publication_year = meta["year"]
    if meta.get("doi"):
        study.doi = meta["doi"]
    if meta.get("journal"):
        study.journal = meta["journal"]
    # esummary/Crossref authors are canonical and already in "Surname Initials" form.
    if meta.get("authors"):
        study.authors = meta["authors"]


async def enrich_report_citations(
    studies: list[ScoredStudy],
    *,
    api_keys: dict[str, str] | None = None,
    offline_mode: bool = False,
) -> None:
    """Fill missing volume/issue/pages/year/journal-abbrev/authors for the cited studies
    by re-fetching the canonical PubMed (esummary) / Crossref record. Mutates studies in
    place; only empty fields are filled. Network failures fall back to existing values."""
    if offline_mode or not studies:
        return
    ncbi_key = (api_keys or {}).get("ncbi")
    pmid_meta: dict[str, dict[str, Any]] = {}
    pmids = [study.pmid for study in studies if study.pmid]
    if pmids:
        try:
            pmid_meta = await fetch_pubmed_citation_metadata(pmids, api_key=ncbi_key)
        except Exception:  # pragma: no cover - defensive network path
            pmid_meta = {}
    for study in studies:
        meta = pmid_meta.get(study.pmid or "")
        if not meta and study.doi:
            try:
                meta = await fetch_crossref_citation_metadata(study.doi)
            except Exception:  # pragma: no cover - defensive network path
                meta = None
        _apply_citation_meta(study, meta)


async def verify_studies(
    studies: list[ScoredStudy],
    *,
    api_keys: dict[str, str] | None = None,
    offline_mode: bool = False,
    limit: int = 8,
) -> VerificationSummary:
    key_map = api_keys or {}
    details: list[VerificationDetail] = []
    verified_pmids = 0
    missing_pmids = 0
    missing_from_pubmed = 0
    notes: list[str] = []
    considered = studies[:limit]
    pmids_to_verify = [study.pmid for study in considered if study.pmid]
    verification_map: dict[str, tuple[bool | None, str | None]] = {}

    if not offline_mode and pmids_to_verify:
        try:
            verification_map = await verify_pmids_in_pubmed(
                pmids_to_verify,
                api_key=key_map.get("ncbi"),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            issue = f"{type(exc).__name__}: {exc}"
            verification_map = {pmid: (None, issue) for pmid in pmids_to_verify}

    for study in considered:
        if not study.pmid:
            missing_pmids += 1
            details.append(
                VerificationDetail(
                    reference_number=study.reference_number,
                    title=study.title,
                    issue="No PMID available for verification",
                )
            )
            continue

        if offline_mode:
            details.append(
                VerificationDetail(
                    reference_number=study.reference_number,
                    title=study.title,
                    pmid=study.pmid,
                    exists_in_pubmed=None,
                    issue="Offline mode enabled; PubMed verification skipped",
                )
            )
            continue

        exists, raw_issue = verification_map.get(study.pmid or "", (False, "PMID not found in PubMed"))
        issue = raw_issue or "Unknown"

        if exists:
            verified_pmids += 1
        elif exists is False:
            missing_from_pubmed += 1
        details.append(
            VerificationDetail(
                reference_number=study.reference_number,
                title=study.title,
                pmid=study.pmid,
                exists_in_pubmed=exists,
                issue=issue,
            )
        )

    if offline_mode:
        notes.append("Offline mode prevented live PMID verification.")
    return VerificationSummary(
        total_considered=min(len(studies), limit),
        verified_pmids=verified_pmids,
        missing_pmids=missing_pmids,
        missing_from_pubmed=missing_from_pubmed,
        offline_mode=offline_mode,
        details=details,
        notes=notes,
    )


def render_verification_report(summary: VerificationSummary) -> str:
    lines = [
        "# Verification Report",
        "",
        f"- Studies checked: {summary.total_considered}",
        f"- Verified PMIDs: {summary.verified_pmids}",
        f"- Missing PMIDs: {summary.missing_pmids}",
        f"- Missing from PubMed: {summary.missing_from_pubmed}",
    ]
    if summary.notes:
        lines.append("")
        lines.extend(f"- {note}" for note in summary.notes)
    lines.append("")
    lines.append("## Details")
    lines.append("")
    for detail in summary.details:
        ref = f"[{detail.reference_number}] " if detail.reference_number else ""
        status = (
            "verified"
            if detail.exists_in_pubmed is True
            else "not found"
            if detail.exists_in_pubmed is False
            else "not checked"
        )
        issue = f" - {detail.issue}" if detail.issue else ""
        lines.append(f"- {ref}{detail.title} ({status}){issue}")
    return "\n".join(lines)
