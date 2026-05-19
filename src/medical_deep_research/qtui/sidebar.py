from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
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
    ACCENT_SOFT,
    BORDER_DIM,
    ERROR,
    SURFACE_SOFT,
    TEXT_MUTED,
    WARNING,
)
from .widgets.badge import (
    BadgePill,
    bool_badge,
    exec_badge_kind,
    exec_label,
    text_badge,
)


_PLAIN_CONFIG_FIELDS = {"local_base_url", "ollama_base_url"}


class WorkspaceTabs(QTabWidget):
    """Top-level workspace tabs for setup, run navigation, and app settings."""

    startRun = Signal(dict)          # noqa: N815 — emits form payload
    languageChanged = Signal(str)    # noqa: N815
    runSelected = Signal(str)        # noqa: N815
    runsRefreshRequested = Signal()  # noqa: N815
    quitRequested = Signal()         # noqa: N815

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
        self._query_type = "free"
        self._provider = "anthropic"
        self._model_by_provider = dict(DEFAULT_MODELS)
        self._model = self._model_by_provider["anthropic"]

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

        self._settings_group = self._build_research_settings()
        self._settings_page = self._wrap_page(self._settings_group)
        self.addTab(self._settings_page, self._t("research_settings"))

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
        self._quit_action = QAction(self._t("quit"), self)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self.quitRequested.emit)
        menu.addAction(self._quit_action)

        self._file_button.setMenu(menu)
        self._file_button.setText(self._t("file_menu"))
        self.setCornerWidget(self._file_button, Qt.Corner.TopRightCorner)

    def _wrap_page(self, widget: QWidget, *, scroll: bool = True) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        if not scroll:
            outer.addWidget(widget, 1)
            return page

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
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

    # ---- New Research form ----

    def _build_new_research(self) -> QGroupBox:
        group = QGroupBox(self._t("new_research"))
        v = QVBoxLayout(group)
        v.setSpacing(8)

        desc = QLabel(self._t("new_research_desc"))
        desc.setProperty("role", "section-desc")
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Query type radio group
        qt_row = QHBoxLayout()
        self._qt_group = QButtonGroup(self)
        self._qt_free = QRadioButton(self._t("free_form"))
        self._qt_pico = QRadioButton("PICO")
        self._qt_pcc  = QRadioButton("PCC")
        self._qt_free.setChecked(True)
        for rb, name in [(self._qt_free, "free"), (self._qt_pico, "pico"), (self._qt_pcc, "pcc")]:
            self._qt_group.addButton(rb)
            rb.toggled.connect(lambda checked, n=name: checked and self._set_query_type(n))
            qt_row.addWidget(rb)
        qt_row.addStretch(1)
        v.addLayout(qt_row)

        # Provider + language row
        pl_row = QHBoxLayout()
        self._provider_combo = QComboBox()
        for code, label in PROVIDER_LABELS.items():
            self._provider_combo.addItem(label, code)
        idx = self._provider_combo.findData(self._provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        pl_row.addWidget(QLabel(self._t("provider")))
        pl_row.addWidget(self._provider_combo, 1)

        self._language_combo = QComboBox()
        self._language_combo.addItem("English", "en")
        self._language_combo.addItem("한국어", "ko")
        idx = self._language_combo.findData(self._lang)
        if idx >= 0:
            self._language_combo.setCurrentIndex(idx)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        pl_row.addWidget(self._language_combo)
        v.addLayout(pl_row)

        # Structured input area (swaps based on query type)
        self._structured_holder = QWidget()
        self._structured_layout = QVBoxLayout(self._structured_holder)
        self._structured_layout.setContentsMargins(0, 0, 0, 0)
        self._structured_layout.setSpacing(6)
        v.addWidget(self._structured_holder)

        # Free-form textarea
        self._free_input = QPlainTextEdit()
        self._free_input.setPlaceholderText(
            "e.g. What is the evidence for SGLT2 inhibitors in heart failure with preserved ejection fraction?"
        )
        self._free_input.setMinimumHeight(80)
        self._free_input.setMaximumHeight(180)
        # PICO fields
        self._pico_p = QLineEdit(); self._pico_p.setPlaceholderText("Adults with HFpEF")
        self._pico_i = QLineEdit(); self._pico_i.setPlaceholderText("SGLT2 inhibitors")
        self._pico_c = QLineEdit(); self._pico_c.setPlaceholderText("Placebo or standard care")
        self._pico_o = QLineEdit(); self._pico_o.setPlaceholderText("Hospitalisation, mortality")
        # PCC fields
        self._pcc_p = QLineEdit(); self._pcc_p.setPlaceholderText("Elderly patients with diabetes")
        self._pcc_c = QLineEdit(); self._pcc_c.setPlaceholderText("Self-management strategies")
        self._pcc_ctx = QLineEdit(); self._pcc_ctx.setPlaceholderText("Primary care settings")
        self._rebuild_structured()

        # Model selector + warning
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._model_combo.editTextChanged.connect(self._on_model_text_changed)
        self._model_label = QLabel(self._t("model"))
        model_row = QHBoxLayout()
        model_row.addWidget(self._model_label)
        model_row.addWidget(self._model_combo, 1)
        v.addLayout(model_row)

        self._model_warning = QLabel("")
        self._model_warning.setStyleSheet(f"color: {ERROR}; font-size: 11px;")
        self._model_warning.setVisible(False)
        v.addWidget(self._model_warning)
        self._refresh_model_combo()

        # Start button
        self._start_btn = QPushButton(self._t("start_run"))
        self._start_btn.setProperty("role", "primary")
        self._start_btn.setMinimumHeight(36)
        self._start_btn.clicked.connect(self._on_start_clicked)
        v.addWidget(self._start_btn)

        return group

    def _rebuild_structured(self) -> None:
        # clear
        while self._structured_layout.count():
            item = self._structured_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        if self._query_type == "pico":
            for label, field in [
                (self._t("population"), self._pico_p),
                (self._t("intervention"), self._pico_i),
                (self._t("comparison"), self._pico_c),
                (self._t("outcome"), self._pico_o),
            ]:
                form = QFormLayout()
                form.setContentsMargins(0, 0, 0, 0)
                form.addRow(label, field)
                wrap = QWidget(); wrap.setLayout(form)
                self._structured_layout.addWidget(wrap)
        elif self._query_type == "pcc":
            for label, field in [
                (self._t("population"), self._pcc_p),
                (self._t("concept"), self._pcc_c),
                (self._t("context"), self._pcc_ctx),
            ]:
                form = QFormLayout()
                form.setContentsMargins(0, 0, 0, 0)
                form.addRow(label, field)
                wrap = QWidget(); wrap.setLayout(form)
                self._structured_layout.addWidget(wrap)
        else:
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.addRow(self._t("research_question"), self._free_input)
            wrap = QWidget(); wrap.setLayout(form)
            self._structured_layout.addWidget(wrap)

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
        model = self._model_combo.currentText().strip() or self._model
        if model:
            self._model = model
            self._model_by_provider[self._provider] = model

    def _refresh_model_combo(self) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        models = PROVIDER_MODELS.get(self._provider, {})
        api_keys = self._service.get_api_keys()
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
        self._model_warning.setText(self._t("set_api_key"))
        self._model_combo.blockSignals(False)

    def _on_start_clicked(self) -> None:
        qt = self._query_type
        payload: dict[str, Any] = {}
        if qt == "pico":
            p, i, c, o = (self._pico_p.text().strip(), self._pico_i.text().strip(),
                          self._pico_c.text().strip(), self._pico_o.text().strip())
            if not p or not i:
                self._show_form_error(self._t("pico_required"))
                return
            payload = {"population": p, "intervention": i, "comparison": c, "outcome": o}
            query = f"Population: {p}; Intervention: {i}; Comparison: {c}; Outcome: {o}"
        elif qt == "pcc":
            p, concept, ctx = (self._pcc_p.text().strip(), self._pcc_c.text().strip(),
                               self._pcc_ctx.text().strip())
            if not p or not concept:
                self._show_form_error(self._t("pcc_required"))
                return
            payload = {"population": p, "concept": concept, "context": ctx}
            query = f"Population: {p}; Concept: {concept}; Context: {ctx}"
        else:
            query = self._free_input.toPlainText().strip()
            if not query:
                self._show_form_error(self._t("query_required"))
                return

        # Use editable text if the combo is editable (local provider)
        model = self._model_combo.currentText() if self._model_combo.isEditable() else (self._model_combo.currentData() or self._model)

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
            border = ACCENT if is_selected else BORDER_DIM
            bg = ACCENT_SOFT if is_selected else SURFACE_SOFT
            card.setStyleSheet(
                "QWidget { "
                f"background: {bg}; border: 1px solid {border}; "
                "border-radius: 6px; padding: 6px; "
                "}"
            )
            cl = QVBoxLayout(card); cl.setSpacing(4); cl.setContentsMargins(8, 6, 8, 6)

            head = QHBoxLayout()
            title = QLabel(entry["provider"].title())
            f = title.font(); f.setBold(True); title.setFont(f)
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(BadgePill(exec_label(entry["active_execution_path"]),
                                     exec_badge_kind(entry["active_execution_path"])))
            cl.addLayout(head)

            sub = QLabel(entry["runtime_name"])
            sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            cl.addWidget(sub)

            badge_row = QHBoxLayout(); badge_row.setSpacing(4)
            engine_b = text_badge("Engine", entry.get("runtime_engine"))
            if engine_b: badge_row.addWidget(engine_b)
            badge_row.addWidget(bool_badge("SDK", entry["sdk_available"]))
            badge_row.addWidget(bool_badge("Key", entry["provider_credentials_present"]))
            badge_row.addWidget(bool_badge("Online", not entry["offline_mode"]))
            search_keys = entry.get("search_credentials_present") or {}
            badge_row.addWidget(bool_badge("Scopus", search_keys.get("scopus")))
            badge_row.addStretch(1)
            cl.addLayout(badge_row)

            if entry.get("fallback_reason"):
                fb = QLabel(entry["fallback_reason"])
                fb.setStyleSheet(f"color: {WARNING}; font-size: 11px;")
                fb.setWordWrap(True)
                cl.addWidget(fb)

            self._provider_status_layout.addWidget(card)

    # ---- API Keys panel ----

    def _build_api_keys(self) -> QGroupBox:
        group = QGroupBox(self._t("api_keys"))
        v = QVBoxLayout(group); v.setSpacing(6)
        desc = QLabel(self._t("api_keys_desc"))
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._key_fields: dict[str, QLineEdit] = {}
        stored = self._service.get_api_keys()
        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0)
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
        wrap = QWidget(); wrap.setLayout(form)
        v.addWidget(wrap)

        self._save_keys_btn = QPushButton(self._t("save_keys"))
        self._save_keys_btn.clicked.connect(self._on_save_keys)
        v.addWidget(self._save_keys_btn, alignment=Qt.AlignmentFlag.AlignRight)
        return group

    def _on_save_keys(self) -> None:
        for svc, field in self._key_fields.items():
            self._service.save_api_key(svc, field.text().strip())
        self._refresh_provider_status_cards()
        self._refresh_model_combo()
        self.runsRefreshRequested.emit()  # status bar message handled by MainWindow via signal? Use parent

    # ---- Research Settings panel ----

    def _build_research_settings(self) -> QGroupBox:
        group = QGroupBox(self._t("research_settings"))
        v = QVBoxLayout(group); v.setSpacing(6)

        desc = QLabel(self._t("years_lookback_desc"))
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        years_row = QFormLayout()
        self._years_input = QSpinBox()
        self._years_input.setRange(1, 50)
        self._years_input.setValue(self._service.get_recent_years_lookback())
        years_row.addRow(f"{self._t('years_lookback')}:", self._years_input)
        v.addLayout(years_row)

        scopus_desc = QLabel(self._t("scopus_view_desc"))
        scopus_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        scopus_desc.setWordWrap(True)
        v.addWidget(scopus_desc)

        scopus_row = QFormLayout()
        self._scopus_combo = QComboBox()
        self._scopus_combo.addItems(["STANDARD", "COMPLETE"])
        self._scopus_combo.setCurrentText(self._service.get_scopus_view())
        scopus_row.addRow(f"{self._t('scopus_view')}:", self._scopus_combo)
        v.addLayout(scopus_row)

        self._save_settings_btn = QPushButton(self._t("save_settings"))
        self._save_settings_btn.clicked.connect(self._on_save_settings)
        v.addWidget(self._save_settings_btn, alignment=Qt.AlignmentFlag.AlignRight)
        return group

    def _on_save_settings(self) -> None:
        self._service.set_recent_years_lookback(int(self._years_input.value()))
        self._service.set_scopus_view(self._scopus_combo.currentText())
        # MainWindow handles the toast; just no-op feedback here
        self._save_settings_btn.setText(self._t("settings_saved"))

    # ---- Retranslate ----

    def retranslate(self) -> None:
        """Re-apply labels when language changes."""
        self._new_research_group.setTitle(self._t("new_research"))
        self._provider_status_group.setTitle(self._t("provider_status"))
        self._api_keys_group.setTitle(self._t("api_keys"))
        self._settings_group.setTitle(self._t("research_settings"))
        self.setTabText(self.indexOf(self._new_research_page), self._t("new_research"))
        self.setTabText(self.indexOf(self._runs_page), self._t("research_runs"))
        self.setTabText(self.indexOf(self._provider_status_page), self._t("provider_status"))
        self.setTabText(self.indexOf(self._api_keys_page), self._t("api_keys"))
        self.setTabText(self.indexOf(self._settings_page), self._t("research_settings"))
        self._file_button.setText(self._t("file_menu"))
        self._quit_action.setText(self._t("quit"))
        self._qt_free.setText(self._t("free_form"))
        self._start_btn.setText(self._t("start_run"))
        self._save_keys_btn.setText(self._t("save_keys"))
        self._save_settings_btn.setText(self._t("save_settings"))
        self._rebuild_structured()
        self._run_list.retranslate()


Sidebar = WorkspaceTabs
