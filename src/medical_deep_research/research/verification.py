from __future__ import annotations

import httpx

from .models import ScoredStudy, VerificationDetail, VerificationSummary
from .search import HTTP_TIMEOUT, NCBI_BASE_URL


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
