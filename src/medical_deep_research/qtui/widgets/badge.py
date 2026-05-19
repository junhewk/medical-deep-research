from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


_BADGE_STYLES = {
    "success": "background: #e7f6ef; color: #0f684c; border: 1px solid #bfe5d2;",
    "warn":    "background: #fff4de; color: #8a4d08; border: 1px solid #f5d39a;",
    "error":   "background: #fff0ef; color: #9f2018; border: 1px solid #f4c7c3;",
    "neutral": "background: #f1f5f9; color: #3f5268; border: 1px solid #d9e4ec;",
    "active":  "background: #e8f4fb; color: #1769aa; border: 1px solid #b9daed;",
}

_EVIDENCE_STYLES = {
    "I":   "background: #e7f6ef; color: #0f684c; border: 1px solid #bfe5d2;",
    "II":  "background: #e8f4fb; color: #1769aa; border: 1px solid #b9daed;",
    "III": "background: #fff4de; color: #8a4d08; border: 1px solid #f5d39a;",
    "IV":  "background: #fff0e6; color: #9a4315; border: 1px solid #f5c7a8;",
    "V":   "background: #f1f5f9; color: #536579; border: 1px solid #d9e4ec;",
    "NA":  "background: #f1f5f9; color: #6e7f91; border: 1px solid #d9e4ec;",
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
            "font-weight: 700; font-size: 11px; "
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
            "font-weight: 800; font-size: 11px; "
            "padding: 2px 8px; border-radius: 9px; "
            "}"
        )


def status_badge_kind(status: str) -> str:
    return {
        "running":     "active",
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
