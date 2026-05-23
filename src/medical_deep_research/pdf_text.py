from __future__ import annotations

from pathlib import Path


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract text from a PDF using the lightweight pdfminer.six parser."""
    try:
        from pdfminer.high_level import extract_text
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pdfminer.six is not installed; install the pdf extra to parse PDFs.") from exc

    text = extract_text(str(pdf_path)) or ""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()
