"""Europe PMC full-text retrieval (JATS XML → plain text).

For open-access PMC articles, Europe PMC serves the full text as JATS XML.
Parsing that directly avoids the less reliable Unpaywall → PDF → pdfminer
chain (publisher 403s, scanned PDFs).  It is used as the first full-text
source, with the PDF pipeline kept as a fallback.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .search import EUROPE_PMC_REST_BASE_URL, USER_AGENT

_log = logging.getLogger(__name__)

# JATS elements whose textual content is noise for synthesis.
_SKIP_TAGS = {"table-wrap", "fig", "table", "graphic", "inline-formula", "disp-formula"}


def _block_text(element: ET.Element) -> str:
    """Recursively collect readable text, skipping tables/figures/formulae."""
    parts: list[str] = []
    if element.text and element.text.strip():
        parts.append(element.text.strip())
    for child in element:
        tag = child.tag.split("}")[-1]
        if tag not in _SKIP_TAGS:
            inner = _block_text(child)
            if inner:
                parts.append(inner)
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return " ".join(parts)


def _extract_body_text(xml_text: str) -> str | None:
    root = ET.fromstring(xml_text)
    body = root.find(".//body")
    if body is None:
        return None
    blocks: list[str] = []
    # Section titles and paragraphs, in document order.
    for element in body.iter():
        tag = element.tag.split("}")[-1]
        if tag in ("title", "p"):
            text = _block_text(element)
            if text:
                blocks.append(f"## {text}" if tag == "title" else text)
    cleaned = "\n\n".join(block for block in blocks if block.strip())
    return cleaned or None


async def fetch_europe_pmc_fulltext_xml(pmcid: str) -> str | None:
    """Return plain-text body of an OA article, or None if unavailable.

    Only ~50-70% of PMC articles are in the OA subset that serves fullTextXML;
    a None result simply means the caller should fall back to the PDF chain.
    """
    pmcid = pmcid if str(pmcid).upper().startswith("PMC") else f"PMC{pmcid}"
    url = f"{EUROPE_PMC_REST_BASE_URL}/{pmcid}/fullTextXML"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
        return _extract_body_text(response.text)
    except Exception as exc:  # noqa: BLE001 - fall back to the PDF chain on any failure
        _log.info("[FULLTEXT] Europe PMC XML failed for %s: %s", pmcid, exc)
        return None
