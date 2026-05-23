from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ..theme import ACCENT, ACCENT_SOFT, BORDER_DIM, ERROR, SUCCESS, TEXT_MUTED, TEXT_SECONDARY, WARNING

_BADGE_STYLES = {
    "success": f"background: #e7f6ef; color: {SUCCESS}; border: 1px solid #bfe5d2;",
    "warn":    f"background: #fff4de; color: {WARNING}; border: 1px solid #f5d39a;",
    "error":   f"background: #fff0ef; color: {ERROR}; border: 1px solid #f4c7c3;",
    "neutral": f"background: #f2f4f7; color: {TEXT_SECONDARY}; border: 1px solid {BORDER_DIM};",
    "active":  f"background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid #b7dad5;",
}

_EVIDENCE_STYLES = {
    "I":   f"background: #e7f6ef; color: {SUCCESS}; border: 1px solid #bfe5d2;",
    "II":  f"background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid #b7dad5;",
    "III": f"background: #fff4de; color: {WARNING}; border: 1px solid #f5d39a;",
    "IV":  "background: #fff0e6; color: #9a4315; border: 1px solid #f5c7a8;",
    "V":   "background: #f1f5f9; color: #536579; border: 1px solid #d9e4ec;",
    "NA":  f"background: #f2f4f7; color: {TEXT_MUTED}; border: 1px solid {BORDER_DIM};",
}


class BadgePill(QLabel):
    def __init__(self, text: str, kind: str = "neutral") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        style = _BADGE_STYLES.get(kind, _BADGE_STYLES["neutral"])
        self.setStyleSheet(
            "QLabel { "
            f"{style} "
            "font-weight: 700; font-size: 12px; "
            "padding: 2px 8px; border-radius: 9px; "
            "}"
        )


class EvidenceBadge(QLabel):
    def __init__(self, level: str | None) -> None:
        super().__init__(level or "N/A")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        key = "NA"
        if level:
            for roman in ("I", "II", "III", "IV", "V"):
                if roman in level:
                    key = roman
                    break
        style = _EVIDENCE_STYLES[key]
        self.setStyleSheet(
            "QLabel { "
            f"{style} "
            "font-weight: 800; font-size: 12px; "
            "padding: 2px 8px; border-radius: 9px; "
            "}"
        )


def status_badge_kind(status: str) -> str:
    return {
        "running":     "active",
        "waiting_for_pdfs": "warn",
        "completed":   "success",
        "failed":      "error",
        "cancelled":   "warn",
        "interrupted": "warn",
        "pending":     "neutral",
    }.get(status, "neutral")


def exec_badge_kind(mode: str | None) -> str:
    if mode in {"native_sdk", "native_sdk_agentic"}:
        return "success"
    if mode in {"deterministic_fallback", "deterministic"}:
        return "warn"
    return "neutral"


def exec_label(mode: str | None) -> str:
    mapping = {
        "native_sdk": "Native SDK",
        "native_sdk_agentic": "Agentic",
        "deterministic_fallback": "Fallback",
        "deterministic": "Deterministic",
    }
    return mapping.get(mode or "", (mode or "unknown").replace("_", " ").title())


def bool_badge(label: str, value: object) -> BadgePill:
    if value is True:
        return BadgePill(f"{label}: yes", "success")
    if value is False:
        return BadgePill(f"{label}: no", "error")
    return BadgePill(f"{label}: ?", "neutral")


def text_badge(label: str, value: object) -> BadgePill | None:
    if not value:
        return None
    return BadgePill(f"{label}: {str(value).replace('_', ' ')}", "neutral")
