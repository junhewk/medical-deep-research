from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..service import DEFAULT_MODELS, ResearchService
from .i18n import API_KEY_SERVICES, PROVIDER_LABELS, PROVIDER_MODELS
from .run_list import RunListPanel
from .theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER_DIM,
    ERROR,
    SURFACE,
    SURFACE_SOFT,
    TEXT_MUTED,
    TEXT_SECONDARY,
)
from .widgets.badge import (
    BadgePill,
    exec_badge_kind,
    exec_label,
    text_badge,
)


_PLAIN_CONFIG_FIELDS = {"local_base_url", "ollama_base_url"}


def _provider_flag_badge(label: str, value: object) -> BadgePill:
    if value is True:
        return BadgePill(f"{label}: ready", "active")
    if value is False:
        return BadgePill(f"{label}: missing", "warn")
    return BadgePill(f"{label}: n/a", "neutral")


class WorkspaceTabs(QTabWidget):
    """Top-level workspace tabs for setup, run navigation, and app settings."""

    startRun = Signal(dict)          # noqa: N815 — emits form payload
    languageChanged = Signal(str)    # noqa: N815
    runSelected = Signal(str)        # noqa: N815
    runsRefreshRequested = Signal()  # noqa: N815
    quitRequested = Signal()         # noqa: N815
    checkUpdatesRequested = Signal()  # noqa: N815
    autoUpdatesChanged = Signal(bool)  # noqa: N815

    def __init__(
        self,
        service: ResearchService,
        t: Callable[[str], str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._t = t
        self._lang = service.get_language()

        # form state
        self._query_type = "pico"
        self._provider = "anthropic"
        self._model_by_provider = dict(DEFAULT_MODELS)
        self._model = self._model_by_provider["anthropic"]
        self._free_text = ""
        self._pico_values = {
            "population": "",
            "intervention": "",
            "comparison": "",
            "outcome": "",
        }
        self._pcc_values = {
            "population": "",
            "concept": "",
            "context": "",
        }
        self._free_input: QPlainTextEdit | None = None
        self._pico_p: QLineEdit | None = None
        self._pico_i: QLineEdit | None = None
        self._pico_c: QLineEdit | None = None
        self._pico_o: QLineEdit | None = None
        self._pcc_p: QLineEdit | None = None
        self._pcc_c: QLineEdit | None = None
        self._pcc_ctx: QLineEdit | None = None
        self._codex_auth_title_label: QLabel | None = None
        self._codex_status_label: QLabel | None = None
        self._codex_login_btn: QPushButton | None = None
        self._codex_device_btn: QPushButton | None = None
        self._codex_logout_btn: QPushButton | None = None
        self._codex_download_btn: QPushButton | None = None
        self._codex_runtime_available = True
        self._codex_runtime_download_url: str | None = None

        self._install_corner_file_menu()

        # Sections
        self._new_research_group = self._build_new_research()
        self._new_research_page = self._wrap_page(self._new_research_group)
        self.addTab(self._new_research_page, self._t("new_research"))

        self._provider_status_group = self._build_provider_status()
        self._provider_status_page = self._wrap_page(self._provider_status_group)
        self.addTab(self._provider_status_page, self._t("provider_status"))

        self._api_keys_group = self._build_api_keys()
        self._api_keys_page = self._wrap_page(self._api_keys_group)
        self.addTab(self._api_keys_page, self._t("api_keys"))

        # Run list (not in a group box — it's the primary navigation list)
        self._run_list = RunListPanel(self._t)
        self._run_list.runSelected.connect(self.runSelected.emit)
        self._run_list.pageChanged.connect(self.runsRefreshRequested.emit)
        self._runs_page = self._wrap_page(self._run_list, scroll=False)
        self.insertTab(1, self._runs_page, self._t("research_runs"))

    def _install_corner_file_menu(self) -> None:
        self._file_button = QToolButton(self)
        self._file_button.setProperty("role", "tab-corner")
        self._file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(self._file_button)
        self._check_updates_action = QAction(self._t("check_updates"), self)
        self._check_updates_action.triggered.connect(self.checkUpdatesRequested.emit)
        menu.addAction(self._check_updates_action)
        self._auto_updates_action = QAction(self._t("auto_check_updates"), self)
        self._auto_updates_action.setCheckable(True)
        self._auto_updates_action.setChecked(self._service.auto_updates_enabled())
        self._auto_updates_action.toggled.connect(self.autoUpdatesChanged.emit)
        menu.addAction(self._auto_updates_action)
        menu.addSeparator()
        self._quit_action = QAction(self._t("quit"), self)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self.quitRequested.emit)
        menu.addAction(self._quit_action)

        self._file_button.setMenu(menu)
        self._file_button.setText(self._t("file_menu"))
        self.setCornerWidget(self._file_button, Qt.Corner.TopRightCorner)

    def _wrap_page(self, widget: QWidget, *, scroll: bool = True) -> QWidget:
        page = QWidget()
        page.setObjectName("workspacePage")
        page.setAutoFillBackground(True)
        page.setStyleSheet(f"QWidget#workspacePage {{ background: {APP_BG}; }}")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        if not scroll:
            outer.addWidget(widget, 1)
            return page

        scroll = QScrollArea()
        scroll.setObjectName("workspaceScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea#workspaceScroll { "
            f"background: {APP_BG}; border: none; "
            "}"
        )
        scroll.viewport().setStyleSheet(f"background: {APP_BG};")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("workspaceContent")
        content.setAutoFillBackground(True)
        content.setStyleSheet(f"QWidget#workspaceContent {{ background: {APP_BG}; }}")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if widget.objectName() == "researchPanel":
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        else:
            layout.addWidget(widget)
        layout.addStretch(1)
        return page

    # ---- public API ----

    def current_language(self) -> str:
        return self._lang

    def set_runs(self, runs: list[Any], total: int) -> None:
        self._run_list.set_runs(runs, total)

    def select_run(self, run_id: str) -> None:
        self._run_list.select_run(run_id)

    def run_list_offset(self) -> int:
        return self._run_list.offset

    def run_list_per_page(self) -> int:
        return self._run_list.per_page

    def refresh_provider_diagnostics(self) -> None:
        self._refresh_provider_status_cards()

    def set_auto_updates_supported(self, supported: bool) -> None:
        self._auto_updates_action.setEnabled(supported)

    # ---- New Research form ----

    def _build_new_research(self) -> QGroupBox:
        group = QGroupBox("")
        group.setObjectName("researchPanel")
        group.setMinimumWidth(760)
        group.setMaximumWidth(980)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(group)
        v.setContentsMargins(22, 18, 22, 20)
        v.setSpacing(14)

        self._new_research_title_label = QLabel(self._t("new_research"))
        self._new_research_title_label.setProperty("role", "section-title")
        v.addWidget(self._new_research_title_label)

        self._new_research_desc_label = QLabel(self._t("new_research_desc"))
        self._new_research_desc_label.setProperty("role", "section-desc")
        self._new_research_desc_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        self._new_research_desc_label.setWordWrap(True)
        v.addWidget(self._new_research_desc_label)

        # Query type radio group
        qt_row = QHBoxLayout()
        self._qt_group = QButtonGroup(self)
        self._qt_pico = QRadioButton("PICO")
        self._qt_pcc  = QRadioButton("PCC")
        self._qt_free = QRadioButton(self._t("free_form"))
        self._qt_pico.setChecked(True)
        for rb, name in [(self._qt_pico, "pico"), (self._qt_pcc, "pcc"), (self._qt_free, "free")]:
            self._qt_group.addButton(rb)
            rb.toggled.connect(lambda checked, n=name: checked and self._set_query_type(n))
            qt_row.addWidget(rb)
        qt_row.addStretch(1)
        v.addLayout(qt_row)

        # Provider + language row
        pl_row = QHBoxLayout()
        pl_row.setSpacing(10)
        self._provider_combo = QComboBox()
        for code, label in PROVIDER_LABELS.items():
            self._provider_combo.addItem(label, code)
        idx = self._provider_combo.findData(self._provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_label = QLabel(self._t("provider"))
        self._provider_label.setFixedWidth(128)
        self._provider_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pl_row.addWidget(self._provider_label)
        pl_row.addWidget(self._provider_combo, 1)

        self._language_combo = QComboBox()
        self._language_combo.addItem("English", "en")
        self._language_combo.addItem("한국어", "ko")
        idx = self._language_combo.findData(self._lang)
        if idx >= 0:
            self._language_combo.setCurrentIndex(idx)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._language_combo.setMinimumWidth(128)
        pl_row.addWidget(self._language_combo)
        v.addLayout(pl_row)

        # Structured input area (swaps based on query type)
        self._structured_holder = QWidget()
        self._structured_holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._structured_layout = QVBoxLayout(self._structured_holder)
        self._structured_layout.setContentsMargins(0, 0, 0, 0)
        self._structured_layout.setSpacing(8)
        v.addWidget(self._structured_holder)

        self._rebuild_structured()

        # Model selector + warning
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._model_combo.editTextChanged.connect(self._on_model_text_changed)
        self._model_label = QLabel(self._t("model"))
        self._model_label.setFixedWidth(128)
        self._model_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_row.addWidget(self._model_label)
        model_row.addWidget(self._model_combo, 1)
        v.addLayout(model_row)

        self._model_warning = QLabel("")
        self._model_warning.setStyleSheet(f"color: {ERROR}; font-size: 12px;")
        self._model_warning.setVisible(False)
        v.addWidget(self._model_warning)
        self._refresh_model_combo()

        self._add_research_settings(v)

        # Start button
        self._start_btn = QPushButton(self._t("start_run"))
        self._start_btn.setObjectName("startResearchButton")
        self._start_btn.setProperty("role", "primary")
        self._start_btn.setMinimumHeight(38)
        self._start_btn.setMinimumWidth(230)
        self._start_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._start_btn.setStyleSheet(
            "QPushButton#startResearchButton { "
            f"background-color: {ACCENT}; color: #ffffff; "
            f"border: 1px solid {ACCENT_HOVER}; border-radius: 6px; "
            "padding: 9px 18px; font-weight: 700; "
            "}"
            "QPushButton#startResearchButton:hover { "
            f"background-color: {ACCENT_HOVER}; "
            "}"
            "QPushButton#startResearchButton:disabled { "
            "background-color: #9db8b4; border-color: #9db8b4; color: #f8fafc; "
            "}"
        )
        self._start_btn.clicked.connect(self._on_start_clicked)
        start_row = QHBoxLayout()
        start_row.addStretch(1)
        start_row.addWidget(self._start_btn)
        v.addLayout(start_row)

        return group

    def _add_research_settings(self, parent: QVBoxLayout) -> None:
        self._settings_title_label = QLabel(self._t("research_settings"))
        self._settings_title_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 700;")
        parent.addWidget(self._settings_title_label)

        self._years_desc_label = QLabel(self._t("years_lookback_desc"))
        self._years_desc_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._years_desc_label.setWordWrap(True)
        parent.addWidget(self._years_desc_label)

        self._years_input = QSpinBox()
        self._years_input.setRange(1, 50)
        self._years_input.setValue(self._service.get_recent_years_lookback())
        self._years_label = self._add_settings_row(parent, self._t("years_lookback"), self._years_input)
        self._years_input.valueChanged.connect(lambda _value: self._persist_research_settings())

        self._scopus_desc_label = QLabel(self._t("scopus_view_desc"))
        self._scopus_desc_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._scopus_desc_label.setWordWrap(True)
        parent.addWidget(self._scopus_desc_label)

        self._scopus_combo = QComboBox()
        self._scopus_combo.addItems(["STANDARD", "COMPLETE"])
        self._scopus_combo.setCurrentText(self._service.get_scopus_view())
        self._scopus_label = self._add_settings_row(parent, self._t("scopus_view"), self._scopus_combo)
        self._scopus_combo.currentTextChanged.connect(lambda _text: self._persist_research_settings())

    def _add_settings_row(self, parent: QVBoxLayout, label_text: str, field: QWidget) -> QLabel:
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        label = QLabel(label_text)
        label.setFixedWidth(128)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, field.sizePolicy().verticalPolicy())
        row.addWidget(label)
        row.addWidget(field, 1)
        parent.addWidget(wrap)
        return label

    def _rebuild_structured(self) -> None:
        self._capture_structured_values()

        # clear
        while self._structured_layout.count():
            item = self._structured_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._free_input = None
        self._pico_p = self._pico_i = self._pico_c = self._pico_o = None
        self._pcc_p = self._pcc_c = self._pcc_ctx = None

        if self._query_type == "pico":
            self._pico_p = QLineEdit(self._pico_values["population"])
            self._pico_p.setPlaceholderText("Adults with HFpEF")
            self._pico_i = QLineEdit(self._pico_values["intervention"])
            self._pico_i.setPlaceholderText("SGLT2 inhibitors")
            self._pico_c = QLineEdit(self._pico_values["comparison"])
            self._pico_c.setPlaceholderText("Placebo or standard care")
            self._pico_o = QLineEdit(self._pico_values["outcome"])
            self._pico_o.setPlaceholderText("Hospitalisation, mortality")
            for label, field in [
                (self._t("population"), self._pico_p),
                (self._t("intervention"), self._pico_i),
                (self._t("comparison"), self._pico_c),
                (self._t("outcome"), self._pico_o),
            ]:
                self._add_input_row(label, field)
        elif self._query_type == "pcc":
            self._pcc_p = QLineEdit(self._pcc_values["population"])
            self._pcc_p.setPlaceholderText("Elderly patients with diabetes")
            self._pcc_c = QLineEdit(self._pcc_values["concept"])
            self._pcc_c.setPlaceholderText("Self-management strategies")
            self._pcc_ctx = QLineEdit(self._pcc_values["context"])
            self._pcc_ctx.setPlaceholderText("Primary care settings")
            for label, field in [
                (self._t("population"), self._pcc_p),
                (self._t("concept"), self._pcc_c),
                (self._t("context"), self._pcc_ctx),
            ]:
                self._add_input_row(label, field)
        else:
            self._free_input = QPlainTextEdit()
            self._free_input.setPlaceholderText(
                "e.g. What is the evidence for SGLT2 inhibitors in heart failure with preserved ejection fraction?"
            )
            self._free_input.setPlainText(self._free_text)
            self._free_input.setMinimumHeight(80)
            self._free_input.setMaximumHeight(180)
            self._add_input_row(self._t("research_question"), self._free_input)

    def _add_input_row(self, label_text: str, field: QWidget) -> None:
        """Add a native-looking, full-width row to the first-page form."""
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        wrap.setMinimumHeight(36)

        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        label = QLabel(label_text)
        label.setFixedWidth(128)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, field.sizePolicy().verticalPolicy())
        if isinstance(field, QLineEdit):
            field.setMinimumHeight(34)

        row.addWidget(label)
        row.addWidget(field, 1)
        self._structured_layout.addWidget(wrap)

    def _safe_line_text(self, field: QLineEdit | None) -> str:
        if field is None:
            return ""
        try:
            return field.text()
        except RuntimeError:
            return ""

    def _safe_plain_text(self, field: QPlainTextEdit | None) -> str:
        if field is None:
            return ""
        try:
            return field.toPlainText()
        except RuntimeError:
            return ""

    def _capture_structured_values(self) -> None:
        if self._free_input is not None:
            self._free_text = self._safe_plain_text(self._free_input)
        if self._pico_p is not None:
            self._pico_values = {
                "population": self._safe_line_text(self._pico_p),
                "intervention": self._safe_line_text(self._pico_i),
                "comparison": self._safe_line_text(self._pico_c),
                "outcome": self._safe_line_text(self._pico_o),
            }
        if self._pcc_p is not None:
            self._pcc_values = {
                "population": self._safe_line_text(self._pcc_p),
                "concept": self._safe_line_text(self._pcc_c),
                "context": self._safe_line_text(self._pcc_ctx),
            }

    def _set_query_type(self, name: str) -> None:
        self._query_type = name
        self._rebuild_structured()

    def _on_provider_changed(self, _index: int) -> None:
        self._remember_current_model()
        self._provider = self._provider_combo.currentData() or "anthropic"
        self._model = self._model_by_provider.get(
            self._provider,
            DEFAULT_MODELS.get(self._provider, self._model),
        )
        self._refresh_model_combo()
        self._refresh_provider_status_cards()

    def _on_language_changed(self, _index: int) -> None:
        new_lang = self._language_combo.currentData() or "en"
        if new_lang == self._lang:
            return
        self._lang = new_lang
        self._service.set_language(new_lang)
        self.languageChanged.emit(new_lang)

    def _on_model_changed(self, _index: int) -> None:
        self._remember_current_model()

    def _on_model_text_changed(self, _text: str) -> None:
        self._remember_current_model()

    def _remember_current_model(self) -> None:
        if not hasattr(self, "_model_combo"):
            return
        model = self._current_model_id()
        if model:
            self._model = model
            self._model_by_provider[self._provider] = model

    def _provider_models(self) -> dict[str, str]:
        try:
            models = self._service.get_model_options(self._provider)
        except Exception:
            models = {}
        return models or PROVIDER_MODELS.get(self._provider, {})

    def _current_model_id(self) -> str:
        text = self._model_combo.currentText().strip()
        data = self._model_combo.currentData()
        models = self._provider_models()

        if isinstance(data, str) and data in models and text in {data, models[data]}:
            return data
        if text in models:
            return text
        for code, label in models.items():
            if text == label:
                return code
        return text or self._model

    def _refresh_model_combo(self) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        models = self._provider_models()
        api_keys = self._service.get_api_keys()
        if self._provider == "codex":
            has_key = self._service.has_codex_auth_cache()
        else:
            has_key = self._provider in api_keys and bool(api_keys[self._provider].strip())
        default = self._model_by_provider.get(self._provider) or DEFAULT_MODELS.get(self._provider, self._model)
        if models:
            for code, label in models.items():
                self._model_combo.addItem(label, code)
            if default not in models:
                self._model_combo.addItem(default, default)
            idx = self._model_combo.findData(default)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            self._model_combo.setCurrentText(default)
            self._model = default
        else:
            self._model_combo.addItem(default, default)
            self._model_combo.setCurrentText(default)
            self._model = default

        self._model_combo.setEditable(True)
        disabled = not has_key and self._provider != "local"
        self._model_combo.setEnabled(not disabled)
        self._model_warning.setVisible(disabled)
        self._model_warning.setText(self._t("set_codex_auth") if self._provider == "codex" else self._t("set_api_key"))
        self._model_combo.blockSignals(False)

    def _on_start_clicked(self) -> None:
        qt = self._query_type
        payload: dict[str, Any] = {}
        if qt == "pico":
            if not all((self._pico_p, self._pico_i, self._pico_c, self._pico_o)):
                self._rebuild_structured()
            p, i, c, o = (self._pico_p.text().strip(), self._pico_i.text().strip(),
                          self._pico_c.text().strip(), self._pico_o.text().strip())
            if not p or not i:
                self._show_form_error(self._t("pico_required"))
                return
            payload = {"population": p, "intervention": i, "comparison": c, "outcome": o}
            query = f"Population: {p}; Intervention: {i}; Comparison: {c}; Outcome: {o}"
        elif qt == "pcc":
            if not all((self._pcc_p, self._pcc_c, self._pcc_ctx)):
                self._rebuild_structured()
            p, concept, ctx = (self._pcc_p.text().strip(), self._pcc_c.text().strip(),
                               self._pcc_ctx.text().strip())
            if not p or not concept:
                self._show_form_error(self._t("pcc_required"))
                return
            payload = {"population": p, "concept": concept, "context": ctx}
            query = f"Population: {p}; Concept: {concept}; Context: {ctx}"
        else:
            if self._free_input is None:
                self._rebuild_structured()
            query = self._free_input.toPlainText().strip()
            if not query:
                self._show_form_error(self._t("query_required"))
                return

        model = self._current_model_id()
        self._persist_research_settings()

        self.startRun.emit({
            "query": query,
            "query_type": qt,
            "provider": self._provider,
            "model": model,
            "query_payload": payload or None,
        })

    def _show_form_error(self, message: str) -> None:
        self._model_warning.setText(message)
        self._model_warning.setVisible(True)

    # ---- Provider Status panel ----

    def _build_provider_status(self) -> QGroupBox:
        group = QGroupBox(self._t("provider_status"))
        self._provider_status_layout = QVBoxLayout(group)
        self._provider_status_layout.setSpacing(6)
        self._refresh_provider_status_cards()
        return group

    def _refresh_provider_status_cards(self) -> None:
        # Clear
        while self._provider_status_layout.count():
            item = self._provider_status_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        diagnostics = self._service.get_provider_diagnostics()
        for entry in diagnostics:
            is_selected = entry["provider"] == self._provider
            card = QWidget()
            card.setObjectName("providerCard")
            border = ACCENT if is_selected else BORDER_DIM
            bg = SURFACE if is_selected else SURFACE_SOFT
            card.setStyleSheet(
                "QWidget#providerCard { "
                f"background: {bg}; border: 1px solid {border}; "
                "border-radius: 6px; padding: 6px; "
                "}"
            )
            cl = QVBoxLayout(card)
            cl.setSpacing(4)
            cl.setContentsMargins(8, 6, 8, 6)

            head = QHBoxLayout()
            title = QLabel(PROVIDER_LABELS.get(entry["provider"], entry["provider"].title()))
            f = title.font()
            f.setBold(True)
            title.setFont(f)
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(BadgePill(exec_label(entry["active_execution_path"]),
                                     exec_badge_kind(entry["active_execution_path"])))
            cl.addLayout(head)

            sub = QLabel(entry["runtime_name"])
            sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
            cl.addWidget(sub)

            badge_row = QHBoxLayout()
            badge_row.setSpacing(4)
            engine_b = text_badge("Engine", entry.get("runtime_engine"))
            if engine_b:
                badge_row.addWidget(engine_b)
            badge_row.addWidget(_provider_flag_badge("SDK", entry["sdk_available"]))
            badge_row.addWidget(_provider_flag_badge("Key", entry["provider_credentials_present"]))
            badge_row.addWidget(_provider_flag_badge("Online", not entry["offline_mode"]))
            search_keys = entry.get("search_credentials_present") or {}
            badge_row.addWidget(_provider_flag_badge("Scopus", search_keys.get("scopus")))
            badge_row.addStretch(1)
            cl.addLayout(badge_row)

            if entry.get("fallback_reason"):
                fb = QLabel(entry["fallback_reason"])
                fb.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
                fb.setWordWrap(True)
                cl.addWidget(fb)

            self._provider_status_layout.addWidget(card)

    # ---- API Keys panel ----

    def _build_api_keys(self) -> QGroupBox:
        group = QGroupBox(self._t("api_keys"))
        v = QVBoxLayout(group)
        v.setSpacing(6)
        self._api_keys_desc_label = QLabel(self._t("api_keys_desc"))
        self._api_keys_desc_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._api_keys_desc_label.setWordWrap(True)
        v.addWidget(self._api_keys_desc_label)
        self._add_codex_auth_controls(v)

        self._key_fields: dict[str, QLineEdit] = {}
        stored = self._service.get_api_keys()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        for svc, label in API_KEY_SERVICES:
            le = QLineEdit(stored.get(svc, ""))
            le.setEchoMode(QLineEdit.EchoMode.Normal if svc in _PLAIN_CONFIG_FIELDS else QLineEdit.EchoMode.Password)
            le.setPlaceholderText("…")
            if svc in _PLAIN_CONFIG_FIELDS:
                le.setPlaceholderText("http://127.0.0.1:11434/v1")
            elif svc == "local":
                le.setPlaceholderText("optional")
            self._key_fields[svc] = le
            form.addRow(f"{label}:", le)
        wrap = QWidget()
        wrap.setLayout(form)
        v.addWidget(wrap)

        self._save_keys_btn = QPushButton(self._t("save_keys"))
        self._save_keys_btn.clicked.connect(self._on_save_keys)
        v.addWidget(self._save_keys_btn, alignment=Qt.AlignmentFlag.AlignRight)
        return group

    def _add_codex_auth_controls(self, parent: QVBoxLayout) -> None:
        self._codex_auth_title_label = QLabel(self._t("codex_auth"))
        self._codex_auth_title_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 700;")
        parent.addWidget(self._codex_auth_title_label)

        self._codex_status_label = QLabel(
            self._t("codex_auth_ready_unknown")
            if self._service.has_codex_auth_cache()
            else self._t("codex_auth_missing")
        )
        self._codex_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._codex_status_label.setWordWrap(True)
        parent.addWidget(self._codex_status_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._codex_login_btn = QPushButton(self._t("codex_login_browser"))
        self._codex_device_btn = QPushButton(self._t("codex_login_device"))
        self._codex_logout_btn = QPushButton(self._t("codex_logout"))
        self._codex_download_btn = QPushButton(self._t("codex_download_runtime"))
        self._codex_login_btn.clicked.connect(self._on_codex_login_browser)
        self._codex_device_btn.clicked.connect(self._on_codex_login_device)
        self._codex_logout_btn.clicked.connect(self._on_codex_logout)
        self._codex_download_btn.clicked.connect(self._on_codex_download_runtime)
        row.addWidget(self._codex_login_btn)
        row.addWidget(self._codex_device_btn)
        row.addWidget(self._codex_logout_btn)
        row.addWidget(self._codex_download_btn)
        row.addStretch(1)
        self._codex_download_btn.setVisible(False)
        parent.addLayout(row)
        self._refresh_codex_auth_status()

    def _schedule_async(self, coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            return
        loop.create_task(coro)

    def _set_codex_auth_buttons_enabled(self, enabled: bool) -> None:
        for button in (self._codex_login_btn, self._codex_device_btn):
            if button is not None:
                button.setEnabled(enabled and self._codex_runtime_available)
        if self._codex_logout_btn is not None:
            self._codex_logout_btn.setEnabled(
                enabled and self._codex_runtime_available and self._service.has_codex_auth_cache()
            )
        if self._codex_download_btn is not None:
            self._codex_download_btn.setEnabled(bool(self._codex_runtime_download_url))

    def _apply_codex_auth_status(self, status: Any) -> None:
        if self._codex_status_label is None:
            return
        self._codex_runtime_available = bool(getattr(status, "runtime_available", True))
        self._codex_runtime_download_url = getattr(status, "runtime_download_url", None)
        if self._codex_download_btn is not None:
            self._codex_download_btn.setVisible(not self._codex_runtime_available)
        if not self._codex_runtime_available:
            error = getattr(status, "runtime_error", None) or getattr(status, "error", None) or "unknown"
            text = self._t("codex_runtime_missing").format(error=error)
            self._codex_status_label.setStyleSheet(f"color: {ERROR}; font-size: 12px;")
        elif status.error:
            text = self._t("codex_auth_error").format(error=status.error)
            self._codex_status_label.setStyleSheet(f"color: {ERROR}; font-size: 12px;")
        elif status.account_email:
            plan = status.plan_type or "unknown"
            text = self._t("codex_auth_ready").format(email=status.account_email, plan=plan)
            self._codex_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        elif status.configured:
            text = self._t("codex_auth_ready_unknown")
            self._codex_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        else:
            text = self._t("codex_auth_missing")
            self._codex_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._codex_status_label.setText(text)
        self._set_codex_auth_buttons_enabled(True)

    def _codex_error_status(self, exc: Exception) -> SimpleNamespace:
        runtime_status = self._service.get_codex_runtime_status()
        return SimpleNamespace(
            configured=self._service.has_codex_auth_cache(),
            account_email=None,
            plan_type=None,
            error=f"{type(exc).__name__}: {exc}",
            runtime_available=runtime_status.available,
            runtime_error=runtime_status.error,
            runtime_download_url=runtime_status.download_url,
        )

    def _refresh_codex_auth_status(self, *, force: bool = False) -> None:
        del force
        if self._codex_status_label is not None:
            self._codex_status_label.setText(self._t("codex_auth_checking"))
        self._schedule_async(self._load_codex_auth_status())

    async def _load_codex_auth_status(self) -> None:
        status = await self._service.get_codex_auth_status(refresh=False)
        self._apply_codex_auth_status(status)
        self._refresh_provider_status_cards()
        self._refresh_model_combo()

    def _on_codex_login_browser(self) -> None:
        self._schedule_async(self._login_codex_browser())

    def _on_codex_login_device(self) -> None:
        self._schedule_async(self._login_codex_device())

    def _on_codex_logout(self) -> None:
        self._schedule_async(self._logout_codex())

    def _on_codex_download_runtime(self) -> None:
        if self._codex_runtime_download_url:
            QDesktopServices.openUrl(QUrl(self._codex_runtime_download_url))

    async def _login_codex_browser(self) -> None:
        self._set_codex_auth_buttons_enabled(False)
        try:
            status = await self._service.login_codex_browser(
                open_url=lambda url: QDesktopServices.openUrl(QUrl(url))
            )
            self._apply_codex_auth_status(status)
        except Exception as exc:
            self._apply_codex_auth_status(self._codex_error_status(exc))
        finally:
            self._set_codex_auth_buttons_enabled(True)
            self._refresh_provider_status_cards()
            self._refresh_model_combo()

    async def _login_codex_device(self) -> None:
        self._set_codex_auth_buttons_enabled(False)

        def show_code(url: str, code: str) -> None:
            QDesktopServices.openUrl(QUrl(url))
            QMessageBox.information(
                self,
                self._t("codex_device_title"),
                self._t("codex_device_message").format(url=url, code=code),
            )

        try:
            status = await self._service.login_codex_device_code(on_code=show_code)
            self._apply_codex_auth_status(status)
        except Exception as exc:
            self._apply_codex_auth_status(self._codex_error_status(exc))
        finally:
            self._set_codex_auth_buttons_enabled(True)
            self._refresh_provider_status_cards()
            self._refresh_model_combo()

    async def _logout_codex(self) -> None:
        self._set_codex_auth_buttons_enabled(False)
        try:
            status = await self._service.logout_codex()
            self._apply_codex_auth_status(status)
        except Exception as exc:
            self._apply_codex_auth_status(self._codex_error_status(exc))
        finally:
            self._set_codex_auth_buttons_enabled(True)
            self._refresh_provider_status_cards()
            self._refresh_model_combo()

    def _on_save_keys(self) -> None:
        for svc, field in self._key_fields.items():
            self._service.save_api_key(svc, field.text().strip())
        self._refresh_provider_status_cards()
        self._refresh_model_combo()
        self.runsRefreshRequested.emit()  # status bar message handled by MainWindow via signal? Use parent

    # ---- Research Settings ----

    def _persist_research_settings(self) -> None:
        self._service.set_recent_years_lookback(int(self._years_input.value()))
        self._service.set_scopus_view(self._scopus_combo.currentText())

    # ---- Retranslate ----

    def retranslate(self) -> None:
        """Re-apply labels when language changes."""
        self._new_research_group.setTitle("")
        self._provider_status_group.setTitle(self._t("provider_status"))
        self._api_keys_group.setTitle(self._t("api_keys"))
        self.setTabText(self.indexOf(self._new_research_page), self._t("new_research"))
        self.setTabText(self.indexOf(self._runs_page), self._t("research_runs"))
        self.setTabText(self.indexOf(self._provider_status_page), self._t("provider_status"))
        self.setTabText(self.indexOf(self._api_keys_page), self._t("api_keys"))
        self._file_button.setText(self._t("file_menu"))
        self._quit_action.setText(self._t("quit"))
        self._check_updates_action.setText(self._t("check_updates"))
        self._auto_updates_action.setText(self._t("auto_check_updates"))
        self._new_research_title_label.setText(self._t("new_research"))
        self._new_research_desc_label.setText(self._t("new_research_desc"))
        self._provider_label.setText(self._t("provider"))
        self._model_label.setText(self._t("model"))
        self._api_keys_desc_label.setText(self._t("api_keys_desc"))
        if self._codex_auth_title_label is not None:
            self._codex_auth_title_label.setText(self._t("codex_auth"))
        if self._codex_login_btn is not None:
            self._codex_login_btn.setText(self._t("codex_login_browser"))
        if self._codex_device_btn is not None:
            self._codex_device_btn.setText(self._t("codex_login_device"))
        if self._codex_logout_btn is not None:
            self._codex_logout_btn.setText(self._t("codex_logout"))
        if self._codex_download_btn is not None:
            self._codex_download_btn.setText(self._t("codex_download_runtime"))
        self._settings_title_label.setText(self._t("research_settings"))
        self._years_label.setText(self._t("years_lookback"))
        self._years_desc_label.setText(self._t("years_lookback_desc"))
        self._scopus_label.setText(self._t("scopus_view"))
        self._scopus_desc_label.setText(self._t("scopus_view_desc"))
        self._qt_free.setText(self._t("free_form"))
        self._start_btn.setText(self._t("start_run"))
        self._save_keys_btn.setText(self._t("save_keys"))
        self._rebuild_structured()
        self._refresh_codex_auth_status()
        self._run_list.retranslate()


Sidebar = WorkspaceTabs
