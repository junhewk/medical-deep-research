from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import (
    ACCENT,
    ACCENT_SOFT,
    BORDER_DIM,
    SURFACE_SOFT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    adjusted_point_size,
)
from ..widgets.badge import BadgePill, EvidenceBadge
from ..widgets.markdown_view import MarkdownView


_TOOL_PROMPTS = {
    "tool_structure": "Summarize the structure of this paper: what are the main sections, what claim does each section make, and how do they connect?",
    "tool_findings": "What are the key findings and results? List each with its statistical evidence (p-values, confidence intervals, effect sizes).",
}


class _ChatMessageWidget(QFrame):
    def __init__(self, role: str, text: str) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        is_user = role == "user"
        bg = ACCENT_SOFT if is_user else SURFACE_SOFT
        border = ACCENT if is_user else BORDER_DIM
        self.setStyleSheet(
            "_ChatMessageWidget { "
            f"background: {bg}; "
            f"border: 1px solid {border}; border-left: 3px solid {border}; "
            "border-radius: 6px; "
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        view = MarkdownView()
        view.setStyleSheet("QTextBrowser { border: none; background: transparent; }")
        view.set_markdown(text)
        # Fit height to content
        view.document().setTextWidth(self.width() - 20)
        h = int(view.document().size().height()) + 8
        view.setFixedHeight(max(40, h))
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view = view
        layout.addWidget(view)


class StudiesTab(QWidget):
    """Study list (left) + detail panel + streaming chat (right)."""

    statusMessage = Signal(str)  # noqa: N815

    def __init__(
        self,
        reading_service,
        service,
        t: Callable[[str], str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._reading_service = reading_service
        self._service = service
        self._t = t
        self._run = None
        self._session = None
        self._studies: list = []
        self._selected_ref: int | None = None
        self._scope: str | None = None
        self._streaming = False
        self._streaming_msg: MarkdownView | None = None
        self._stream_task: asyncio.Task | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Empty-state label
        self._empty = QLabel(self._t("studies_not_available"))
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px; padding: 32px;")
        layout.addWidget(self._empty)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter, 1)
        self._splitter.setVisible(False)

        # ----- Left: study list -----
        self._study_list = QListWidget()
        self._study_list.setMaximumWidth(260)
        self._study_list.setMinimumWidth(180)
        self._study_list.itemSelectionChanged.connect(self._on_study_selected)
        self._splitter.addWidget(self._study_list)

        # ----- Middle: paper detail -----
        self._detail_holder = QScrollArea()
        self._detail_holder.setWidgetResizable(True)
        self._detail_holder.setFrameShape(QScrollArea.Shape.NoFrame)
        self._detail_inner = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_inner)
        self._detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail_layout.setSpacing(8)
        self._detail_holder.setWidget(self._detail_inner)
        self._splitter.addWidget(self._detail_holder)
        self._splitter.setStretchFactor(1, 2)

        # ----- Right: chat -----
        self._chat_holder = QWidget()
        chat_layout = QVBoxLayout(self._chat_holder)
        chat_layout.setContentsMargins(8, 8, 8, 8)
        chat_layout.setSpacing(6)

        # Tool buttons row
        self._tool_row = QHBoxLayout()
        self._tool_row.setSpacing(4)
        for key, prompt in _TOOL_PROMPTS.items():
            btn = QPushButton(self._t(key))
            btn.clicked.connect(lambda _, p=prompt: self._send_message(p))
            self._tool_row.addWidget(btn)
        self._export_btn = QPushButton(self._t("export_notes"))
        self._export_btn.clicked.connect(self._on_export_notes)
        self._tool_row.addWidget(self._export_btn)
        self._tool_row.addStretch(1)
        chat_layout.addLayout(self._tool_row)

        # Scope label
        self._scope_label = QLabel("")
        self._scope_label.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: 700;")
        chat_layout.addWidget(self._scope_label)

        # Chat scroll area
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_inner = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_inner)
        self._chat_layout.setContentsMargins(4, 4, 4, 4)
        self._chat_layout.setSpacing(6)
        self._chat_layout.addStretch(1)
        self._chat_scroll.setWidget(self._chat_inner)
        chat_layout.addWidget(self._chat_scroll, 1)

        # Input row
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("…")
        self._input.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self._input, 1)
        self._send_btn = QPushButton(self._t("send"))
        self._send_btn.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self._send_btn)
        chat_layout.addLayout(input_row)

        self._splitter.addWidget(self._chat_holder)
        self._splitter.setStretchFactor(2, 2)
        self._splitter.setSizes([200, 400, 400])

    # ---- public API ----

    def set_run(self, run, has_studies: bool) -> None:
        # Cancel any pending stream
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            self._stream_task = None

        self._run = run
        self._studies = []
        self._selected_ref = None
        self._scope = None
        self._streaming = False
        self._clear_chat()
        self._clear_detail()
        self._study_list.clear()

        if not has_studies or self._reading_service is None or run is None:
            self._empty.setVisible(True)
            self._splitter.setVisible(False)
            return

        session = self._reading_service.get_or_create_session(run.id)
        studies = self._reading_service.get_ranked_studies(run.id) if session else []
        if not session or not studies:
            self._empty.setVisible(True)
            self._splitter.setVisible(False)
            return

        self._session = session
        self._studies = studies
        self._empty.setVisible(False)
        self._splitter.setVisible(True)

        for study in studies:
            ref = study.reference_number or 0
            text = f"[{ref}] {study.title}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self._study_list.addItem(item)

    def retranslate(self) -> None:
        self._empty.setText(self._t("studies_not_available"))
        self._export_btn.setText(self._t("export_notes"))
        self._send_btn.setText(self._t("send"))
        for i in range(self._tool_row.count()):
            w = self._tool_row.itemAt(i).widget()
            if isinstance(w, QPushButton) and w is not self._export_btn:
                # Tool button order matches _TOOL_PROMPTS keys
                pass
        # Rebuild tool buttons to translate labels
        # Clear and rebuild — easier than tracking mappings
        for i in reversed(range(self._tool_row.count())):
            item = self._tool_row.itemAt(i)
            w = item.widget()
            if w is not None and w is not self._export_btn:
                w.setParent(None)
        # Re-insert before export
        idx = self._tool_row.indexOf(self._export_btn)
        for offset, (key, prompt) in enumerate(_TOOL_PROMPTS.items()):
            btn = QPushButton(self._t(key))
            btn.clicked.connect(lambda _, p=prompt: self._send_message(p))
            self._tool_row.insertWidget(idx + offset, btn)
        self._refresh_scope_label()

    # ---- study selection ----

    def _on_study_selected(self) -> None:
        items = self._study_list.selectedItems()
        if not items or not self._run:
            return
        ref = items[0].data(Qt.ItemDataRole.UserRole)
        if ref == self._selected_ref:
            return
        self._selected_ref = ref
        self._scope = f"study:{ref}"
        self._refresh_detail()
        self._reload_chat()

    def _refresh_scope_label(self) -> None:
        if not self._scope:
            self._scope_label.setText("")
            return
        if self._scope.startswith("study:"):
            self._scope_label.setText(f"{self._t('discussing_study')} #{self._scope.split(':')[1]}")
        else:
            self._scope_label.setText(self._t("all_studies"))

    def _clear_detail(self) -> None:
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _refresh_detail(self) -> None:
        self._clear_detail()
        if self._selected_ref is None or self._run is None:
            return
        study = next((s for s in self._studies if s.reference_number == self._selected_ref), None)
        if study is None:
            return

        title = QLabel(study.title)
        title.setWordWrap(True)
        f = title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 2)); title.setFont(f)
        self._detail_layout.addWidget(title)

        authors = ", ".join(study.authors[:5])
        if len(study.authors) > 5:
            authors += " et al."
        authors_lbl = QLabel(authors)
        authors_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        authors_lbl.setWordWrap(True)
        self._detail_layout.addWidget(authors_lbl)

        journal_lbl = QLabel(f"{study.journal or 'N/A'}, {study.publication_year or 'N/A'}")
        journal_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-style: italic;")
        self._detail_layout.addWidget(journal_lbl)

        # Badge row
        badge_row = QHBoxLayout(); badge_row.setSpacing(4)
        badge_row.addWidget(EvidenceBadge(study.evidence_level))
        badge_row.addWidget(BadgePill(f"Score {study.composite_score:.2f}", "neutral"))
        badge_row.addWidget(BadgePill(f"{study.citation_count} cit.", "neutral"))
        if study.pmid:
            badge_row.addWidget(BadgePill(f"PMID {study.pmid}", "neutral"))
        if study.doi:
            doi_btn = QPushButton(f"DOI: {study.doi}")
            doi_btn.setProperty("role", "link")
            doi_btn.clicked.connect(lambda _=False, url=f"https://doi.org/{study.doi}": QDesktopServices.openUrl(url))
            badge_row.addWidget(doi_btn)
        badge_row.addStretch(1)
        wrap = QWidget(); wrap.setLayout(badge_row)
        self._detail_layout.addWidget(wrap)

        # Abstract
        if study.abstract:
            abstract_title = QLabel("Abstract")
            f = abstract_title.font(); f.setBold(True); abstract_title.setFont(f)
            self._detail_layout.addWidget(abstract_title)
            abstract_view = QLabel(study.abstract)
            abstract_view.setWordWrap(True)
            abstract_view.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
            abstract_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._detail_layout.addWidget(abstract_view)

        # Full text or fetch action
        fulltext = self._reading_service.get_fulltext(self._run.id, self._selected_ref)
        if fulltext:
            ft_title = QLabel("Full Text")
            f = ft_title.font(); f.setBold(True); ft_title.setFont(f)
            self._detail_layout.addWidget(ft_title)
            ft_view = MarkdownView()
            ft_view.set_markdown(fulltext)
            ft_view.setMinimumHeight(300)
            self._detail_layout.addWidget(ft_view, 1)
        else:
            actions_row = QHBoxLayout()
            ft_btn = QPushButton(self._t("fetch_fulltext"))
            ft_btn.clicked.connect(lambda: self._on_fetch_fulltext(ft_btn))
            actions_row.addWidget(ft_btn)
            pdf_btn = QPushButton(self._t("open_pdf"))
            pdf_btn.clicked.connect(self._on_open_pdf)
            actions_row.addWidget(pdf_btn)
            actions_row.addStretch(1)
            wrap2 = QWidget(); wrap2.setLayout(actions_row)
            self._detail_layout.addWidget(wrap2)

        self._detail_layout.addStretch(1)

    # ---- fulltext fetching ----

    def _on_fetch_fulltext(self, button: QPushButton) -> None:
        if self._run is None or self._selected_ref is None:
            return
        button.setText(self._t("fetching_fulltext"))
        button.setEnabled(False)
        run_id = self._run.id
        ref = self._selected_ref
        api_keys = self._service.get_api_keys()

        async def _do() -> None:
            ok = await self._reading_service.fetch_fulltext_on_demand(run_id, ref, api_keys)
            if ok:
                self.statusMessage.emit(self._t("fulltext_fetched"))
                self._refresh_detail()
            else:
                self.statusMessage.emit(self._t("fulltext_failed"))
                button.setText(self._t("fetch_fulltext"))
                button.setEnabled(True)

        asyncio.ensure_future(_do())

    def _on_open_pdf(self) -> None:
        if self._run is None or self._selected_ref is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, self._t("open_pdf"), str(Path.home()), "PDF Files (*.pdf)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, self._t("studies"), str(exc))
            return
        if not data.startswith(b"%PDF-"):
            QMessageBox.warning(self, self._t("studies"), "Not a valid PDF")
            return

        run_id = self._run.id
        ref = self._selected_ref

        async def _do() -> None:
            text = ""
            tmp_in = None
            tmp_dir = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fp:
                    fp.write(data)
                    tmp_in = fp.name
                try:
                    import glob
                    import opendataloader_pdf  # type: ignore
                    tmp_dir = tempfile.mkdtemp()
                    await asyncio.to_thread(
                        opendataloader_pdf.convert,
                        input_path=[tmp_in],
                        output_dir=tmp_dir,
                        format="markdown",
                    )
                    md_files = glob.glob(f"{tmp_dir}/**/*.md", recursive=True)
                    if md_files:
                        text = Path(md_files[0]).read_text(encoding="utf-8")
                except ImportError:
                    text = "[opendataloader-pdf not installed]"
                except Exception as exc:  # pragma: no cover - depends on optional lib
                    text = f"[PDF parse error: {exc}]"
            finally:
                if tmp_in:
                    try: Path(tmp_in).unlink()
                    except OSError: pass

            if text:
                self._reading_service.store_fulltext(run_id, ref, text)
                self.statusMessage.emit(self._t("fulltext_fetched"))
                self._refresh_detail()
            else:
                self.statusMessage.emit(self._t("fulltext_failed"))

        asyncio.ensure_future(_do())

    # ---- chat ----

    def _clear_chat(self) -> None:
        # Remove all items except the trailing stretch
        for i in reversed(range(self._chat_layout.count() - 1)):
            item = self._chat_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._streaming_msg = None

    def _reload_chat(self) -> None:
        self._clear_chat()
        self._refresh_scope_label()
        if self._session is None or self._scope is None or self._run is None:
            return
        history = self._reading_service.get_chat_history(self._session.id, self._scope)
        for msg in history:
            self._append_chat_message(msg.role, msg.content)

        # If no history, auto-open the discussion
        if not history and not self._streaming:
            self._stream_task = asyncio.ensure_future(self._auto_open_discussion())

    def _append_chat_message(self, role: str, text: str) -> None:
        msg = _ChatMessageWidget(role, text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, msg)
        # Scroll to bottom
        scrollbar = self._chat_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_send_clicked(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._send_message(text)

    def _send_message(self, text: str) -> None:
        if self._streaming or self._session is None or self._scope is None or self._run is None:
            return
        self._stream_task = asyncio.ensure_future(self._do_send(text))

    async def _do_send(self, text: str) -> None:
        self._streaming = True
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)
        self._append_chat_message("user", text)
        # Streaming assistant bubble
        streaming_widget = _ChatMessageWidget("assistant", "")
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, streaming_widget)
        view = streaming_widget._view
        accumulated = ""
        try:
            async for chunk in self._reading_service.ask(
                session_id=self._session.id,
                scope=self._scope,
                user_message=text,
                run_id=self._run.id,
                provider=self._run.provider,
                model=self._run.model,
                api_keys=self._service.get_api_keys(),
            ):
                accumulated += chunk
                view.set_markdown(accumulated)
                # Resize the bubble to fit content
                view.document().setTextWidth(streaming_widget.width() - 20)
                h = int(view.document().size().height()) + 8
                view.setFixedHeight(max(40, h))
                scrollbar = self._chat_scroll.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except asyncio.CancelledError:
            return
        except Exception as exc:
            view.set_markdown(f"*Error: {exc}*")
        finally:
            self._streaming = False
            self._send_btn.setEnabled(True)
            self._input.setEnabled(True)

    async def _auto_open_discussion(self) -> None:
        if self._session is None or self._scope is None or self._run is None:
            return
        self._streaming = True
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)
        streaming_widget = _ChatMessageWidget("assistant", "")
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, streaming_widget)
        view = streaming_widget._view
        accumulated = ""
        try:
            async for chunk in self._reading_service.open_discussion(
                session_id=self._session.id,
                scope=self._scope,
                run_id=self._run.id,
                provider=self._run.provider,
                model=self._run.model,
                api_keys=self._service.get_api_keys(),
            ):
                accumulated += chunk
                view.set_markdown(accumulated)
                view.document().setTextWidth(streaming_widget.width() - 20)
                h = int(view.document().size().height()) + 8
                view.setFixedHeight(max(40, h))
                scrollbar = self._chat_scroll.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except asyncio.CancelledError:
            return
        except Exception as exc:
            view.set_markdown(f"*Error: {exc}*")
        finally:
            self._streaming = False
            self._send_btn.setEnabled(True)
            self._input.setEnabled(True)

    def _on_export_notes(self) -> None:
        if self._session is None or self._scope is None or self._run is None:
            return
        notes = self._reading_service.export_notes(self._session.id, self._scope, self._run.id)
        if not notes.strip():
            QMessageBox.information(self, self._t("export_notes"), self._t("no_notes"))
            return
        QGuiApplication.clipboard().setText(notes)
        self.statusMessage.emit(self._t("notes_copied"))
