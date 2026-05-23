from __future__ import annotations

import asyncio
import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, load_settings
from ..persistence import AppDatabase
from ..reading_service import ReadingService
from ..service import ResearchService
from .i18n import t as _translate
from .sidebar import WorkspaceTabs
from .tabs.artifacts_tab import ArtifactsTab
from .tabs.diagnostics_tab import DiagnosticsTab
from .tabs.report_tab import ReportTab
from .tabs.studies_tab import StudiesTab
from .tabs.trace_tab import TraceTab
from .theme import (
    APP_BG,
    APP_QSS,
    BORDER_DIM,
    SURFACE,
    TEXT_MUTED,
    adjusted_point_size,
    default_font,
    load_embedded_fonts,
)
from .widgets.badge import BadgePill, status_badge_kind


class _RunHeader(QWidget):
    """Compact run status bar shown above the tab widget."""

    interruptClicked = Signal()  # noqa: N815
    cancelClicked = Signal()     # noqa: N815

    def __init__(self, t_fn, parent=None) -> None:
        super().__init__(parent)
        self._t = t_fn

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._query_label = QLabel("")
        self._query_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        self._query_label.setSizePolicy(self._query_label.sizePolicy().horizontalPolicy(),
                                       self._query_label.sizePolicy().verticalPolicy())
        self._query_label.setWordWrap(False)
        row.addWidget(self._query_label, 1)

        self._status_badge = BadgePill("pending", "neutral")
        row.addWidget(self._status_badge)

        self._runtime_badge = BadgePill("", "neutral")
        row.addWidget(self._runtime_badge)

        self._progress = QProgressBar()
        self._progress.setMinimumWidth(120)
        self._progress.setMaximumWidth(180)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        row.addWidget(self._progress)

        self._interrupt_btn = QPushButton(self._t("interrupt"))
        self._interrupt_btn.clicked.connect(self.interruptClicked.emit)
        row.addWidget(self._interrupt_btn)

        self._cancel_btn = QPushButton(self._t("cancel"))
        self._cancel_btn.setProperty("role", "danger")
        self._cancel_btn.clicked.connect(self.cancelClicked.emit)
        row.addWidget(self._cancel_btn)

        self.setStyleSheet(
            f"_RunHeader {{ background: {SURFACE}; border: 1px solid {BORDER_DIM}; "
            "border-radius: 8px; }"
        )

    def set_run(self, run) -> None:
        # Truncate query for display
        query_text = run.query.replace("\n", " ").strip()
        if len(query_text) > 120:
            query_text = query_text[:117] + "…"
        self._query_label.setText(query_text)
        self._query_label.setToolTip(run.query)
        self._status_badge.setText(run.status)
        self._status_badge.set_kind(status_badge_kind(run.status))
        self._runtime_badge.setText(run.runtime_name)
        self._progress.setValue(int(run.progress or 0))
        is_running = run.status in {"running", "waiting_for_pdfs"}
        self._interrupt_btn.setEnabled(is_running)
        self._cancel_btn.setEnabled(is_running)

    def retranslate(self) -> None:
        self._interrupt_btn.setText(self._t("interrupt"))
        self._cancel_btn.setText(self._t("cancel"))


class MainWindow(QMainWindow):
    """Top-level Qt window."""

    serviceChange = Signal(str, str)  # noqa: N815 — (run_id, change_type)

    def __init__(
        self,
        service: ResearchService,
        reading_service: ReadingService | None,
        settings: Settings,
    ) -> None:
        super().__init__()
        self._service = service
        self._reading_service = reading_service
        self._settings = settings
        self._lang = service.get_language()
        self._selected_run_id: str | None = None
        self._refresh_pending = False

        self.setWindowTitle(settings.app_name)
        self.resize(1280, 860)

        self._build_status_bar()
        self._build_layout()

        # Wire async listener: service callback fires the Signal (thread-safe).
        service.add_ui_listener(self._on_service_listener)
        self.serviceChange.connect(self._on_service_change)

        # Initial population
        self._refresh_run_list()
        self._render_detail_placeholder()
        self._status.showMessage(self._t("ready"))

    # ---- translation helper ----
    def _t(self, key: str) -> str:
        return _translate(self._lang, key)

    # ---- layout ----

    def _build_layout(self) -> None:
        central = QWidget()
        central.setObjectName("centralRoot")
        central.setStyleSheet(f"QWidget#centralRoot {{ background: {APP_BG}; }}")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._workspace_tabs = WorkspaceTabs(self._service, self._t)
        self._workspace_tabs.startRun.connect(self._on_start_run)
        self._workspace_tabs.languageChanged.connect(self._on_language_changed)
        self._workspace_tabs.runSelected.connect(self._on_run_selected_from_workspace)
        self._workspace_tabs.runsRefreshRequested.connect(self._refresh_run_list)
        self._workspace_tabs.quitRequested.connect(self.close)
        outer.addWidget(self._workspace_tabs, 1)

        # Run detail tab
        self._main_holder = QStackedWidget()

        # Placeholder page
        self._placeholder = self._build_placeholder()
        self._main_holder.addWidget(self._placeholder)

        # Run-detail page
        self._detail_page = QWidget()
        self._detail_page.setObjectName("detailPage")
        self._detail_page.setStyleSheet(f"QWidget#detailPage {{ background: {APP_BG}; }}")
        detail_layout = QVBoxLayout(self._detail_page)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        detail_layout.setSpacing(8)

        self._run_header = _RunHeader(self._t)
        self._run_header.interruptClicked.connect(self._on_interrupt)
        self._run_header.cancelClicked.connect(self._on_cancel)
        detail_layout.addWidget(self._run_header)

        self._tabs = QTabWidget()
        self._trace_tab = TraceTab(self._t, self._reading_service, self._service)
        self._trace_tab.statusMessage.connect(self._status.showMessage)
        self._trace_tab.checkpointChanged.connect(lambda _run_id: self._do_refresh())
        self._artifacts_tab = ArtifactsTab(self._t)
        self._report_tab = ReportTab(self._t)
        self._report_tab.statusMessage.connect(self._status.showMessage)
        self._diagnostics_tab = DiagnosticsTab(self._t)
        self._studies_tab = StudiesTab(self._reading_service, self._service, self._t)
        self._studies_tab.statusMessage.connect(self._status.showMessage)

        self._tabs.addTab(self._trace_tab, self._t("trace"))
        self._tabs.addTab(self._artifacts_tab, self._t("artifacts"))
        self._tabs.addTab(self._report_tab, self._t("report_title"))
        self._tabs.addTab(self._diagnostics_tab, self._t("diagnostics"))
        self._tabs.addTab(self._studies_tab, self._t("studies"))
        self._tabs.setTabVisible(4, False)  # Studies tab hidden until eligible

        detail_layout.addWidget(self._tabs, 1)
        self._main_holder.addWidget(self._detail_page)
        self._workspace_tabs.addTab(self._main_holder, self._t("run_detail"))

    def _build_placeholder(self) -> QWidget:
        w = QWidget()
        w.setObjectName("placeholderPage")
        w.setStyleSheet(f"QWidget#placeholderPage {{ background: {APP_BG}; }}")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(self._t("select_run"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = title.font()
        f.setPointSizeF(adjusted_point_size(f, 4))
        title.setFont(f)
        title.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(title)

        desc = QLabel(self._t("select_run_desc"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        desc.setMaximumWidth(480)
        layout.addWidget(desc)

        self._placeholder_title = title
        self._placeholder_desc = desc
        return w

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)

    # ---- service listener (called from asyncio task, in same loop as Qt) ----

    def _on_service_listener(self, run_id: str, change_type: str) -> None:
        # Bridge to the Qt thread via a Signal (safe even if called off-thread)
        self.serviceChange.emit(run_id, change_type)

    def _on_service_change(self, run_id: str, change_type: str) -> None:
        # Coalesce rapid bursts of events into a single refresh
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(150, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh_run_list()
        if self._selected_run_id is not None:
            self._refresh_detail(self._selected_run_id, keep_tab=True)

    def _refresh_run_list(self) -> None:
        per_page = self._workspace_tabs.run_list_per_page()
        offset = self._workspace_tabs.run_list_offset()
        runs = self._service.list_runs(limit=per_page, offset=offset)
        total = self._service.count_runs()
        self._workspace_tabs.set_runs(runs, total)

    # ---- run actions ----

    def _on_start_run(self, payload: dict[str, Any]) -> None:
        try:
            run = self._service.create_run(
                query=payload["query"],
                query_type=payload["query_type"],
                provider=payload["provider"],
                model=payload["model"],
                query_payload=payload.get("query_payload"),
            )
        except Exception as exc:
            QMessageBox.critical(self, self._t("app_title"), str(exc))
            return
        self._selected_run_id = run.id
        self._refresh_run_list()
        self._workspace_tabs.select_run(run.id)
        self._refresh_detail(run.id)
        self._status.showMessage(self._t("run_started").format(short_id=run.id[:8]))

    def _on_run_selected_from_workspace(self, run_id: str) -> None:
        if run_id == self._selected_run_id:
            return
        self._selected_run_id = run_id
        self._refresh_detail(run_id)

    def _on_interrupt(self) -> None:
        if self._selected_run_id:
            self._service.interrupt_run(self._selected_run_id)

    def _on_cancel(self) -> None:
        if self._selected_run_id:
            self._service.cancel_run(self._selected_run_id)

    # ---- detail panel ----

    def _render_detail_placeholder(self) -> None:
        self._main_holder.setCurrentWidget(self._placeholder)

    def _refresh_detail(self, run_id: str, *, keep_tab: bool = False) -> None:
        run = self._service.get_run(run_id)
        if run is None:
            self._render_detail_placeholder()
            return

        artifacts = self._service.list_artifacts(run.id)
        events = self._service.list_events(run.id)
        approvals = self._service.list_approvals(run.id)
        diag = self._service.get_run_diagnostics(run.id)

        self._run_header.set_run(run)
        self._trace_tab.set_pdf_checkpoint(run, approvals)
        self._trace_tab.set_events(events)
        self._artifacts_tab.set_artifacts(artifacts)
        self._report_tab.set_report(run.result_markdown or "", run.id[:8])
        self._diagnostics_tab.set_diagnostics(diag)

        has_studies = (
            self._reading_service is not None
            and run.status == "completed"
            and any(a.artifact_type == "ranked_results" for a in artifacts)
        )
        self._tabs.setTabVisible(4, has_studies)
        self._studies_tab.set_run(run, has_studies)

        if not keep_tab:
            self._tabs.setCurrentIndex(0)

        self._main_holder.setCurrentWidget(self._detail_page)
        self._workspace_tabs.setCurrentWidget(self._main_holder)

    # ---- language ----

    def _on_language_changed(self, new_lang: str) -> None:
        self._lang = new_lang
        self.setWindowTitle(self._settings.app_name)
        self._tabs.setTabText(0, self._t("trace"))
        self._tabs.setTabText(1, self._t("artifacts"))
        self._tabs.setTabText(2, self._t("report_title"))
        self._tabs.setTabText(3, self._t("diagnostics"))
        self._tabs.setTabText(4, self._t("studies"))
        self._workspace_tabs.setTabText(
            self._workspace_tabs.indexOf(self._main_holder),
            self._t("run_detail"),
        )
        self._placeholder_title.setText(self._t("select_run"))
        self._placeholder_desc.setText(self._t("select_run_desc"))
        self._workspace_tabs.retranslate()
        self._run_header.retranslate()
        self._trace_tab.retranslate()
        self._artifacts_tab.retranslate()
        self._report_tab.retranslate()
        self._diagnostics_tab.retranslate()
        self._studies_tab.retranslate()
        self._status.showMessage(self._t("ready"))

    # ---- shutdown ----

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Cancel any in-flight research tasks so the loop can stop cleanly.
        for task in list(self._service._tasks.values()):
            if not task.done():
                task.cancel()
        event.accept()


def run_app(
    service: ResearchService | None = None,
    reading_service: ReadingService | None = None,
    settings: Settings | None = None,
) -> int:
    """Boot the Qt application with qasync event loop integration."""
    import qasync

    if settings is None:
        settings = load_settings()
    if service is None:
        database = AppDatabase(settings)
        database.create_all()
        database.bootstrap_defaults()
        database.import_legacy_data(settings.legacy_db_path)
        service = ResearchService(database)
        if reading_service is None:
            reading_service = ReadingService(database)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    load_embedded_fonts()
    app.setFont(default_font())
    app.setStyleSheet(APP_QSS)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(service, reading_service, settings)
    window.show()

    with loop:
        loop.run_forever()
    return 0
