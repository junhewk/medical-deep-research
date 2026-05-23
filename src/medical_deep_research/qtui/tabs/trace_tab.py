from __future__ import annotations

import asyncio
import html
import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import ApprovalRequest, ApprovalStatus, ResearchRun, ResearchStatus
from ...pdf_text import extract_pdf_text
from ...reading_service import ReadingService
from ...service import ResearchService
from ..theme import BORDER_DIM, SURFACE, SURFACE_SOFT, TEXT_MUTED, adjusted_point_size


class TraceTab(QWidget):
    """Live execution-event timeline for the selected run."""

    statusMessage = Signal(str)  # noqa: N815
    checkpointChanged = Signal(str)  # noqa: N815

    def __init__(
        self,
        t: Callable[[str], str],
        reading_service: ReadingService | None = None,
        service: ResearchService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._t = t
        self._reading_service = reading_service
        self._service = service
        self._run: ResearchRun | None = None
        self._pdf_approval: ApprovalRequest | None = None
        self._pdf_details: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel(self._t("execution_trace"))
        f = self._title.font()
        f.setBold(True)
        f.setPointSizeF(adjusted_point_size(f, 1))
        self._title.setFont(f)
        layout.addWidget(self._title)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self._count_label)

        self._pdf_panel = QFrame()
        self._pdf_panel.setObjectName("pdfCheckpointPanel")
        self._pdf_panel.setStyleSheet(
            "QFrame#pdfCheckpointPanel { "
            f"background: {SURFACE_SOFT}; border: none; border-radius: 7px; "
            "}"
        )
        self._pdf_layout = QVBoxLayout(self._pdf_panel)
        self._pdf_layout.setContentsMargins(10, 8, 10, 8)
        self._pdf_layout.setSpacing(6)
        self._pdf_panel.setVisible(False)
        layout.addWidget(self._pdf_panel)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {BORDER_DIM}; border-radius: 7px; background: {SURFACE}; }}"
            "QListWidget::item { border-bottom: 1px solid #edf2ef; padding: 6px 10px; }"
        )
        layout.addWidget(self._list, 1)

        self._empty = QLabel(self._t("waiting_events"))
        self._empty.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; padding: 8px;")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

    def set_pdf_checkpoint(self, run: ResearchRun, approvals: list[ApprovalRequest]) -> None:
        self._run = run
        self._pdf_approval = self._find_pdf_approval(approvals)
        self._pdf_details = self._approval_details(self._pdf_approval)
        self._rebuild_pdf_panel()

    def set_events(self, events: list) -> None:
        self._count_label.setText(f"{len(events)} {self._t('events')}")
        self._list.clear()

        if not events:
            self._empty.setVisible(True)
            self._list.setVisible(False)
            return

        self._empty.setVisible(False)
        self._list.setVisible(True)

        # Show the last 200 events to keep redraws snappy.
        for event in events[-200:]:
            meta_parts = [event.phase, event.event_type, f"{event.progress}%"]
            if event.tool_name:
                meta_parts.append(event.tool_name)
            if event.agent_name:
                meta_parts.append(event.agent_name)
            meta = " · ".join(meta_parts)
            text = f"{event.sequence:03d}   {event.message}\n        {meta}"
            item = QListWidgetItem(text)
            self._list.addItem(item)
        self._list.scrollToBottom()

    def retranslate(self) -> None:
        self._title.setText(self._t("execution_trace"))
        self._empty.setText(self._t("waiting_events"))
        self._rebuild_pdf_panel()

    def _find_pdf_approval(self, approvals: list[ApprovalRequest]) -> ApprovalRequest | None:
        for approval in approvals:
            if approval.status != ApprovalStatus.PENDING.value:
                continue
            details = self._approval_details(approval)
            if details.get("type") == "pdf_upload":
                return approval
        return None

    def _approval_details(self, approval: ApprovalRequest | None) -> dict[str, Any]:
        if not approval or not approval.details_json:
            return {}
        try:
            details = json.loads(approval.details_json)
        except json.JSONDecodeError:
            return {}
        return details if isinstance(details, dict) else {}

    def _clear_pdf_layout(self) -> None:
        while self._pdf_layout.count():
            item = self._pdf_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _rebuild_pdf_panel(self) -> None:
        self._clear_pdf_layout()
        if not self._run or not self._pdf_approval or not self._reading_service or not self._service:
            self._pdf_panel.setVisible(False)
            return

        rows = self._checkpoint_rows()
        if not rows:
            self._pdf_panel.setVisible(False)
            return

        self._pdf_panel.setVisible(True)
        title = QLabel(self._t("pdf_checkpoint_title"))
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        self._pdf_layout.addWidget(title)

        desc = QLabel(self._t("pdf_checkpoint_desc"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._pdf_layout.addWidget(desc)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for col, label in enumerate(("Ref", "Article", "PDF", "")):
            header = QLabel(label)
            header.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 700;")
            grid.addWidget(header, 0, col)

        for row_idx, row in enumerate(rows, start=1):
            rank = int(row["rank"])
            title_text = str(row.get("title") or f"Study #{rank}")
            if len(title_text) > 92:
                title_text = title_text[:89] + "..."

            ref = QLabel(str(rank))
            ref.setAlignment(Qt.AlignmentFlag.AlignTop)
            grid.addWidget(ref, row_idx, 0)

            article_cell = QWidget()
            article_layout = QVBoxLayout(article_cell)
            article_layout.setContentsMargins(0, 0, 0, 0)
            article_layout.setSpacing(2)
            title_label = QLabel(title_text)
            title_label.setToolTip(str(row.get("title") or ""))
            title_label.setWordWrap(True)
            article_layout.addWidget(title_label)
            meta_html = self._article_meta_html(row)
            if meta_html:
                meta_label = QLabel(meta_html)
                meta_label.setTextFormat(Qt.TextFormat.RichText)
                meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
                meta_label.setOpenExternalLinks(True)
                meta_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
                meta_label.setWordWrap(True)
                article_layout.addWidget(meta_label)
            grid.addWidget(article_cell, row_idx, 1)

            uploaded = bool(self._reading_service.get_fulltext(self._run.id, rank))
            status_label = QLabel(
                self._t("pdf_status_uploaded") if uploaded else self._t("pdf_status_missing")
            )
            status_label.setStyleSheet(
                "font-weight: 700; "
                + ("color: #167244;" if uploaded else "color: #9a6400;")
            )
            grid.addWidget(status_label, row_idx, 2)

            upload_btn = QPushButton(
                self._t("replace_pdf") if uploaded else self._t("upload_pdf")
            )
            upload_btn.clicked.connect(lambda _=False, r=rank: self._on_upload_pdf(r))
            grid.addWidget(upload_btn, row_idx, 3)

        grid.setColumnStretch(1, 1)
        self._pdf_layout.addWidget(grid_host)

        actions = QHBoxLayout()
        actions.addStretch(1)
        continue_btn = QPushButton(self._t("continue_with_pdfs"))
        continue_btn.clicked.connect(lambda: self._resolve_checkpoint(True))
        actions.addWidget(continue_btn)
        skip_btn = QPushButton(self._t("skip_fulltext_step"))
        skip_btn.clicked.connect(lambda: self._resolve_checkpoint(False))
        actions.addWidget(skip_btn)
        wrap = QWidget()
        wrap.setLayout(actions)
        self._pdf_layout.addWidget(wrap)

    def _checkpoint_rows(self) -> list[dict[str, Any]]:
        rows = self._pdf_details.get("studies")
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]

        ranks = self._pdf_details.get("missing_ranks") or self._pdf_details.get("ranks") or []
        rank_set = {int(rank) for rank in ranks if str(rank).isdigit()}
        if not rank_set or not self._reading_service or not self._run:
            return []
        studies = self._reading_service.get_ranked_studies(self._run.id)
        return [
            {
                "rank": study.reference_number,
                "title": study.title,
                "journal": study.journal,
                "year": study.publication_year,
                "doi": study.doi,
                "pmid": study.pmid,
                "pmcid": study.pmcid,
                "url": study.url,
            }
            for study in studies
            if study.reference_number in rank_set
        ]

    def _article_meta_html(self, row: dict[str, Any]) -> str:
        parts: list[str] = []
        doi = str(row.get("doi") or "").strip()
        if doi:
            escaped_doi = html.escape(doi, quote=True)
            parts.append(f'<a href="https://doi.org/{escaped_doi}">DOI: {html.escape(doi)}</a>')

        article_url = str(row.get("url") or "").strip()
        pmid = str(row.get("pmid") or "").strip()
        pmcid = str(row.get("pmcid") or "").strip()
        if not article_url and pmid:
            article_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if not article_url and pmcid:
            article_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
        if article_url:
            parts.append(f'<a href="{html.escape(article_url, quote=True)}">Article link</a>')

        return " · ".join(parts)

    def _on_upload_pdf(self, rank: int) -> None:
        if not self._run or not self._reading_service:
            return
        path, _ = QFileDialog.getOpenFileName(self, self._t("upload_pdf"), str(Path.home()), "PDF Files (*.pdf)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, self._t("trace"), str(exc))
            return
        if not data.startswith(b"%PDF-"):
            QMessageBox.warning(self, self._t("trace"), self._t("pdf_not_valid"))
            return

        run_id = self._run.id

        async def _do() -> None:
            try:
                text = await asyncio.to_thread(extract_pdf_text, path)
            except Exception as exc:
                text = f"[PDF parse error: {exc}]"
            if text:
                self._reading_service.store_fulltext(run_id, rank, text)
                self.statusMessage.emit(self._t("fulltext_fetched"))
                self._rebuild_pdf_panel()
                self.checkpointChanged.emit(run_id)
            else:
                self.statusMessage.emit(self._t("fulltext_failed"))

        asyncio.ensure_future(_do())

    def _resolve_checkpoint(self, approved: bool) -> None:
        if not self._pdf_approval or not self._service or not self._run:
            return
        is_live_run = self._run.status in {
            ResearchStatus.RUNNING.value,
            ResearchStatus.WAITING_FOR_PDFS.value,
        }
        self._service.resolve_approval(self._pdf_approval.id, approved)
        if is_live_run:
            message = self._t("pdf_checkpoint_continued") if approved else self._t("pdf_checkpoint_skipped")
        else:
            message = self._t("pdf_checkpoint_stale")
        self.statusMessage.emit(message)
        self.checkpointChanged.emit(self._run.id)
