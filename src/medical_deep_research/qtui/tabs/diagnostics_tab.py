from __future__ import annotations

import json
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import adjusted_point_size
from ..widgets.badge import (
    BadgePill,
    bool_badge,
    exec_badge_kind,
    exec_label,
    text_badge,
)


class DiagnosticsTab(QWidget):
    """Run-level diagnostics: badges + raw JSON dump."""

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel(self._t("run_diagnostics"))
        f = self._title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 1)); self._title.setFont(f)
        layout.addWidget(self._title)

        self._badges_holder = QWidget()
        self._badges_layout = QHBoxLayout(self._badges_holder)
        self._badges_layout.setContentsMargins(0, 0, 0, 0)
        self._badges_layout.setSpacing(4)
        layout.addWidget(self._badges_holder)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #6e7f91; font-size: 12px; font-family: monospace;")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet("font-size: 12px; color: #3f5268;")
        layout.addWidget(self._details_label)

        self._raw_json = QPlainTextEdit()
        self._raw_json.setReadOnly(True)
        self._raw_json.setStyleSheet(
            "QPlainTextEdit { font-family: monospace; font-size: 11px; "
            "background: #f8fafc; border: 1px solid #d6e1ea; }"
        )
        layout.addWidget(self._raw_json, 1)

        self._empty = QLabel(self._t("no_diagnostics"))
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #6e7f91; font-size: 12px;")
        layout.addWidget(self._empty)

    def set_diagnostics(self, diag: dict[str, Any] | None) -> None:
        # Reset
        while self._badges_layout.count():
            item = self._badges_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        if not diag:
            self._summary_label.setText("")
            self._details_label.setText("")
            self._raw_json.setPlainText("")
            self._empty.setVisible(True)
            return

        self._empty.setVisible(False)

        exec_mode = diag.get("execution_mode")
        self._badges_layout.addWidget(BadgePill(exec_label(exec_mode), exec_badge_kind(exec_mode)))
        eng = text_badge("Engine", diag.get("runtime_engine"))
        if eng:
            self._badges_layout.addWidget(eng)
        self._badges_layout.addWidget(bool_badge("SDK", diag.get("sdk_available")))
        self._badges_layout.addWidget(bool_badge("Key", diag.get("provider_credentials_present")))
        self._badges_layout.addWidget(bool_badge("Online", not diag.get("offline_mode", False)))
        search_keys = diag.get("search_credentials_present") or {}
        self._badges_layout.addWidget(bool_badge("Scopus", search_keys.get("scopus")))
        self._badges_layout.addStretch(1)

        self._summary_label.setText(
            f"{diag.get('runtime_name', '')} · {diag.get('model', '')}"
        )

        details = []
        if diag.get("ranked_results") is not None:
            details.append(f"Ranked results: {diag['ranked_results']}")
        if diag.get("tool_calls") is not None:
            details.append(f"Tool calls: {diag['tool_calls']}")
        if diag.get("report_source"):
            details.append(f"Report source: {diag['report_source']}")
        if diag.get("translation_status"):
            details.append(f"Translation: {diag['translation_status']}")
        if diag.get("search_sources_executed"):
            details.append("Search sources: " + ", ".join(diag["search_sources_executed"]))
        warnings = []
        for key in ("error_message", "post_submit_error_message", "sdk_stderr_tail", "fallback_reason", "translation_error"):
            val = diag.get(key)
            if val:
                warnings.append(f"⚠ {key.replace('_', ' ')}: {val}")

        text = "\n".join(details)
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        self._details_label.setText(text)

        self._raw_json.setPlainText(json.dumps(diag, indent=2))

    def retranslate(self) -> None:
        self._title.setText(self._t("run_diagnostics"))
        self._empty.setText(self._t("no_diagnostics"))
