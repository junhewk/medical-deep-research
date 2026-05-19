from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import ACCENT, SURFACE, TEXT_MUTED, adjusted_point_size
from ..widgets.markdown_view import MarkdownView

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$", re.MULTILINE)


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


def _clean_heading(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    return text.strip()


class ReportTab(QWidget):
    """Final markdown report viewer with outline, search, and export actions."""

    statusMessage = Signal(str)  # noqa: N815

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t
        self._report_text = ""
        self._run_short_id = ""
        self._headings: list[tuple[int, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        self._title = QLabel(self._t("report_title"))
        f = self._title.font()
        f.setBold(True)
        f.setPointSizeF(adjusted_point_size(f, 2))
        self._title.setFont(f)
        title_block.addWidget(self._title)

        self._stats = QLabel("")
        self._stats.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        title_block.addWidget(self._stats)
        header.addLayout(title_block)
        header.addStretch(1)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self._t("report_find"))
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(240)
        self._search.returnPressed.connect(self._find_next)
        header.addWidget(self._search)

        self._copy_btn = QPushButton(self._t("copy_report"))
        self._copy_btn.clicked.connect(self._on_copy_markdown)
        header.addWidget(self._copy_btn)

        self._copy_text_btn = QPushButton(self._t("copy_text"))
        self._copy_text_btn.clicked.connect(self._on_copy_text)
        header.addWidget(self._copy_text_btn)

        self._save_md_btn = QPushButton(self._t("download_markdown"))
        self._save_md_btn.clicked.connect(self._on_save_markdown)
        header.addWidget(self._save_md_btn)

        self._save_txt_btn = QPushButton(self._t("download_text"))
        self._save_txt_btn.clicked.connect(self._on_save_text)
        header.addWidget(self._save_txt_btn)

        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        outline_panel = QWidget()
        outline_layout = QVBoxLayout(outline_panel)
        outline_layout.setContentsMargins(0, 0, 0, 0)
        outline_layout.setSpacing(6)

        self._outline_title = QLabel(self._t("report_outline"))
        self._outline_title.setStyleSheet(f"color: {ACCENT}; font-weight: 700;")
        outline_layout.addWidget(self._outline_title)

        self._outline = QListWidget()
        self._outline.setProperty("role", "report-outline")
        self._outline.itemActivated.connect(self._jump_to_heading)
        self._outline.itemClicked.connect(self._jump_to_heading)
        outline_layout.addWidget(self._outline, 1)

        self._view = MarkdownView()
        self._view.setStyleSheet(
            f"QTextBrowser {{ background: {SURFACE}; border-radius: 8px; }}"
        )

        splitter.addWidget(outline_panel)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 820])
        layout.addWidget(splitter, 1)

    def set_report(self, markdown: str, run_short_id: str) -> None:
        self._report_text = markdown or ""
        self._run_short_id = run_short_id or ""
        self._view.set_markdown(self._report_text or f"_{self._t('report_not_started')}_")
        self._rebuild_outline()
        self._update_stats()

    def retranslate(self) -> None:
        self._title.setText(self._t("report_title"))
        self._outline_title.setText(self._t("report_outline"))
        self._search.setPlaceholderText(self._t("report_find"))
        self._copy_btn.setText(self._t("copy_report"))
        self._copy_text_btn.setText(self._t("copy_text"))
        self._save_md_btn.setText(self._t("download_markdown"))
        self._save_txt_btn.setText(self._t("download_text"))
        if not self._report_text:
            self._view.set_markdown(f"_{self._t('report_not_started')}_")
        self._rebuild_outline()
        self._update_stats()

    # ---- report rendering helpers ----

    def _rebuild_outline(self) -> None:
        self._outline.clear()
        self._headings = [
            (len(match.group(1)), _clean_heading(match.group(2)))
            for match in _HEADING_RE.finditer(self._report_text)
        ]

        if not self._headings:
            item = QListWidgetItem(self._t("report_no_outline"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._outline.addItem(item)
            return

        for level, heading in self._headings:
            label = f"{'  ' * max(0, level - 1)}{heading}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, heading)
            self._outline.addItem(item)

    def _update_stats(self) -> None:
        plain = plain_report_text(self._report_text)
        words = len(re.findall(r"\b[\w'-]+\b", plain))
        sections = len(self._headings)
        self._stats.setText(self._t("report_stats").format(words=words, sections=sections))

    def _jump_to_heading(self, item: QListWidgetItem) -> None:
        heading = item.data(Qt.ItemDataRole.UserRole)
        if not heading:
            return
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._view.setTextCursor(cursor)
        found = self._view.document().find(str(heading), cursor)
        if not found.isNull():
            self._view.setTextCursor(found)
            self._view.ensureCursorVisible()

    def _find_next(self) -> None:
        needle = self._search.text().strip()
        if not needle:
            return

        cursor = self._view.textCursor()
        found = self._view.document().find(needle, cursor)
        if found.isNull():
            cursor = self._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            found = self._view.document().find(needle, cursor)
        if not found.isNull():
            self._view.setTextCursor(found)
            self._view.ensureCursorVisible()

    # ---- actions ----

    def _on_copy_markdown(self) -> None:
        if not self._report_text.strip():
            self._show_warn(self._t("report_empty"))
            return
        QGuiApplication.clipboard().setText(self._report_text)
        self.statusMessage.emit(self._t("report_copied"))

    def _on_copy_text(self) -> None:
        text = plain_report_text(self._report_text)
        if not text:
            self._show_warn(self._t("report_empty"))
            return
        QGuiApplication.clipboard().setText(text)
        self.statusMessage.emit(self._t("report_text_copied"))

    def _on_save_markdown(self) -> None:
        self._save(self._report_text, ".md", "Markdown Files (*.md)")

    def _on_save_text(self) -> None:
        self._save(plain_report_text(self._report_text), ".txt", "Text Files (*.txt)")

    def _save(self, content: str, suffix: str, filter_str: str) -> None:
        if not content.strip():
            self._show_warn(self._t("report_empty"))
            return
        default_name = (
            f"medical-deep-research-{self._run_short_id}{suffix}"
            if self._run_short_id
            else f"report{suffix}"
        )
        downloads = Path.home() / "Downloads"
        default_dir = str(downloads) if downloads.exists() else str(Path.home())
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
