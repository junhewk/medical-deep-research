from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import adjusted_point_size
from ..widgets.markdown_view import MarkdownView


def plain_report_text(markdown: str) -> str:
    text = re.sub(r"```[^\n`]*\n([\s\S]*?)```", r"\1", markdown)
    text = re.sub(r"```([\s\S]*?)```", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ReportTab(QWidget):
    """Final markdown report viewer with copy/save actions."""

    statusMessage = Signal(str)  # noqa: N815

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t
        self._report_text = ""
        self._run_short_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self._title = QLabel(self._t("report_title"))
        f = self._title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 1)); self._title.setFont(f)
        header.addWidget(self._title)
        header.addStretch(1)

        self._copy_btn = QPushButton(self._t("copy_report"))
        self._copy_btn.clicked.connect(self._on_copy)
        header.addWidget(self._copy_btn)

        self._save_md_btn = QPushButton(self._t("download_markdown"))
        self._save_md_btn.clicked.connect(self._on_save_markdown)
        header.addWidget(self._save_md_btn)

        self._save_txt_btn = QPushButton(self._t("download_text"))
        self._save_txt_btn.clicked.connect(self._on_save_text)
        header.addWidget(self._save_txt_btn)

        layout.addLayout(header)

        self._view = MarkdownView()
        layout.addWidget(self._view, 1)

    def set_report(self, markdown: str, run_short_id: str) -> None:
        self._report_text = markdown or ""
        self._run_short_id = run_short_id or ""
        self._view.set_markdown(self._report_text or f"_{self._t('report_not_started')}_")

    def retranslate(self) -> None:
        self._title.setText(self._t("report_title"))
        self._copy_btn.setText(self._t("copy_report"))
        self._save_md_btn.setText(self._t("download_markdown"))
        self._save_txt_btn.setText(self._t("download_text"))
        if not self._report_text:
            self._view.set_markdown(f"_{self._t('report_not_started')}_")

    # ---- actions ----

    def _on_copy(self) -> None:
        if not self._report_text.strip():
            self._show_warn(self._t("report_empty"))
            return
        QGuiApplication.clipboard().setText(self._report_text)
        self.statusMessage.emit(self._t("report_copied"))

    def _on_save_markdown(self) -> None:
        self._save(self._report_text, ".md", "Markdown Files (*.md)")

    def _on_save_text(self) -> None:
        self._save(plain_report_text(self._report_text), ".txt", "Text Files (*.txt)")

    def _save(self, content: str, suffix: str, filter_str: str) -> None:
        if not content.strip():
            self._show_warn(self._t("report_empty"))
            return
        default_name = f"medical-deep-research-{self._run_short_id}{suffix}" if self._run_short_id else f"report{suffix}"
        default_dir = str(Path.home() / "Downloads") if (Path.home() / "Downloads").exists() else str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("download_markdown") if suffix == ".md" else self._t("download_text"),
            f"{default_dir}/{default_name}",
            filter_str,
        )
        if not path:
            return
        try:
            Path(path).write_text(content, encoding="utf-8")
            self.statusMessage.emit(f"{self._t('report_saved')}: {path}")
        except OSError as exc:
            self._show_warn(str(exc))

    def _show_warn(self, message: str) -> None:
        QMessageBox.warning(self, self._t("report_title"), message)
