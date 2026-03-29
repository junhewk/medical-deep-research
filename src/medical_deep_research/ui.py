from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from .service import DEFAULT_MODELS, ResearchService


_CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700;900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

:root {
    --bg-deep: #0a0f14;
    --bg-surface: #111921;
    --bg-card: #161f2a;
    --bg-card-hover: #1c2735;
    --border-dim: #1e2a38;
    --border-active: #2dd4a8;
    --text-primary: #e8edf3;
    --text-secondary: #7a8da3;
    --text-muted: #4a5d73;
    --accent: #2dd4a8;
    --accent-dim: rgba(45, 212, 168, 0.12);
    --accent-glow: rgba(45, 212, 168, 0.25);
    --warn: #f5a623;
    --error: #f45b69;
    --success: #2dd4a8;
}

body {
    background: var(--bg-deep) !important;
    color: var(--text-primary) !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}

.nicegui-content {
    background: var(--bg-deep) !important;
}

/* Header bar */
.mdr-header {
    background: linear-gradient(180deg, #0d1420 0%, var(--bg-deep) 100%) !important;
    border-bottom: 1px solid var(--border-dim) !important;
    padding: 0.75rem 1.5rem !important;
}
.mdr-header .mdr-title {
    font-family: 'Playfair Display', serif;
    font-weight: 700;
    font-size: 1.35rem;
    letter-spacing: 0.02em;
    color: var(--text-primary);
}
.mdr-header .mdr-subtitle {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    color: var(--text-muted);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

/* Cards */
.mdr-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-dim) !important;
    border-radius: 6px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.3) !important;
    color: var(--text-primary) !important;
}
.mdr-card:hover {
    border-color: #263445 !important;
}
.mdr-card-active {
    border-color: var(--border-active) !important;
    box-shadow: 0 0 0 1px var(--accent-dim), 0 2px 12px rgba(0,0,0,0.3) !important;
}

/* Section titles */
.mdr-section-title {
    font-family: 'Playfair Display', serif;
    font-weight: 500;
    font-size: 1.05rem;
    color: var(--text-primary);
    letter-spacing: 0.01em;
}
.mdr-section-desc {
    font-size: 0.78rem;
    color: var(--text-muted);
    font-weight: 300;
}

/* Form elements dark theme */
.mdr-card .q-field__label,
.mdr-card .q-field__native,
.mdr-card .q-field__prefix,
.mdr-card .q-field__suffix,
.mdr-card .q-select__dropdown-icon,
.mdr-card textarea,
.mdr-card input {
    color: var(--text-primary) !important;
}
.mdr-card .q-field--outlined .q-field__control:before {
    border-color: var(--border-dim) !important;
}
.mdr-card .q-field--outlined .q-field__control:hover:before {
    border-color: var(--text-muted) !important;
}
.mdr-card .q-field--focused .q-field__control:after {
    border-color: var(--accent) !important;
}
.mdr-card .q-field__label {
    color: var(--text-secondary) !important;
}

/* Primary button */
.mdr-btn-primary {
    background: linear-gradient(135deg, #1a9e80 0%, #2dd4a8 100%) !important;
    color: #0a0f14 !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    border-radius: 4px !important;
    text-transform: none !important;
    font-size: 0.85rem !important;
    box-shadow: 0 2px 8px rgba(45, 212, 168, 0.2) !important;
    transition: box-shadow 0.2s, transform 0.15s !important;
}
.mdr-btn-primary:hover {
    box-shadow: 0 4px 16px rgba(45, 212, 168, 0.35) !important;
    transform: translateY(-1px) !important;
}

/* Badges */
.mdr-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 3px;
}
.mdr-badge-success {
    background: rgba(45, 212, 168, 0.15);
    color: #2dd4a8;
    border: 1px solid rgba(45, 212, 168, 0.3);
}
.mdr-badge-warn {
    background: rgba(245, 166, 35, 0.15);
    color: #f5a623;
    border: 1px solid rgba(245, 166, 35, 0.3);
}
.mdr-badge-error {
    background: rgba(244, 91, 105, 0.15);
    color: #f45b69;
    border: 1px solid rgba(244, 91, 105, 0.3);
}
.mdr-badge-neutral {
    background: rgba(122, 141, 163, 0.12);
    color: var(--text-secondary);
    border: 1px solid rgba(122, 141, 163, 0.2);
}
.mdr-badge-active {
    background: rgba(45, 212, 168, 0.12);
    color: var(--accent);
    border: 1px solid rgba(45, 212, 168, 0.35);
    animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
    0%, 100% { box-shadow: 0 0 0 0 rgba(45, 212, 168, 0); }
    50% { box-shadow: 0 0 8px 2px rgba(45, 212, 168, 0.15); }
}

/* Run list items */
.mdr-run-item {
    padding: 0.6rem 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
    border: 1px solid transparent;
}
.mdr-run-item:hover {
    background: var(--bg-card-hover);
}
.mdr-run-item-selected {
    background: var(--accent-dim) !important;
    border-color: var(--border-active) !important;
}

/* Progress bar */
.mdr-progress .q-linear-progress__track {
    background: var(--border-dim) !important;
    opacity: 1 !important;
}
.mdr-progress .q-linear-progress__model {
    background: linear-gradient(90deg, #1a9e80, #2dd4a8, #4aedc4) !important;
}

/* Trace timeline */
.mdr-trace-item {
    border-left: 2px solid var(--border-dim);
    padding: 0.35rem 0 0.35rem 1rem;
    margin-left: 0.5rem;
    transition: border-color 0.2s;
}
.mdr-trace-item:hover {
    border-left-color: var(--accent);
}
.mdr-trace-seq {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--accent);
    min-width: 1.8rem;
    text-align: right;
    font-weight: 500;
}
.mdr-trace-msg {
    font-size: 0.8rem;
    color: var(--text-primary);
    line-height: 1.35;
}
.mdr-trace-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--text-muted);
}

/* Tab styling */
.mdr-tabs .q-tab {
    color: var(--text-secondary) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}
.mdr-tabs .q-tab--active {
    color: var(--accent) !important;
}
.mdr-tabs .q-tab-panel {
    padding: 0 !important;
}
.mdr-tabs .q-tab__indicator {
    background: var(--accent) !important;
}

/* Report markdown styling */
.mdr-report h1, .mdr-report h2, .mdr-report h3 {
    font-family: 'Playfair Display', serif;
    color: var(--text-primary);
    border-bottom: 1px solid var(--border-dim);
    padding-bottom: 0.4rem;
    margin-bottom: 0.8rem;
}
.mdr-report h1 { font-size: 1.4rem; font-weight: 700; }
.mdr-report h2 { font-size: 1.15rem; font-weight: 500; }
.mdr-report h3 { font-size: 0.95rem; font-weight: 500; border: none; }
.mdr-report p, .mdr-report li {
    font-size: 0.85rem;
    color: var(--text-secondary);
    line-height: 1.6;
}
.mdr-report strong { color: var(--text-primary); }
.mdr-report code {
    font-family: 'IBM Plex Mono', monospace;
    background: var(--bg-deep);
    padding: 0.1rem 0.35rem;
    border-radius: 2px;
    font-size: 0.78rem;
    color: var(--accent);
}
.mdr-report ul { padding-left: 1.2rem; }

/* Code blocks */
.mdr-card pre, .mdr-card code {
    background: var(--bg-deep) !important;
    color: var(--text-secondary) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    border-radius: 4px !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-deep); }
::-webkit-scrollbar-thumb { background: var(--border-dim); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* Provider diagnostic cards */
.mdr-diag-card {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-dim) !important;
    border-radius: 4px !important;
    padding: 0.65rem !important;
    box-shadow: none !important;
}
.mdr-diag-card-selected {
    border-color: var(--accent) !important;
    background: var(--accent-dim) !important;
}

/* Expansion panels */
.mdr-card .q-expansion-item__container {
    border: 1px solid var(--border-dim);
    border-radius: 4px;
    margin-bottom: 0.35rem;
}
.mdr-card .q-expansion-item__toggle {
    color: var(--text-primary) !important;
}
.mdr-card .q-item__label {
    color: var(--text-primary) !important;
    font-size: 0.8rem !important;
}
/* Collapsible section panels */
.mdr-card.q-expansion-item {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-dim) !important;
    border-radius: 6px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.3) !important;
}
.mdr-card.q-expansion-item .q-expansion-item__toggle {
    padding: 0.5rem 1rem !important;
}
.mdr-card.q-expansion-item .q-item__section--avatar {
    color: var(--text-muted) !important;
    min-width: 32px !important;
}
.mdr-card.q-expansion-item .q-item__label {
    font-family: 'Playfair Display', serif !important;
    font-weight: 500 !important;
    font-size: 1.05rem !important;
    color: var(--text-primary) !important;
}
.mdr-card.q-expansion-item .q-expansion-item__content {
    padding: 0 1rem 1rem !important;
}
"""


def _status_badge_class(status: str) -> str:
    mapping = {
        "running": "mdr-badge-active",
        "completed": "mdr-badge-success",
        "failed": "mdr-badge-error",
        "cancelled": "mdr-badge-warn",
        "interrupted": "mdr-badge-warn",
        "pending": "mdr-badge-neutral",
    }
    return mapping.get(status, "mdr-badge-neutral")


def _exec_badge_class(mode: str | None) -> str:
    if mode == "native_sdk" or mode == "native_sdk_agentic":
        return "mdr-badge-success"
    if mode in {"deterministic_fallback", "deterministic"}:
        return "mdr-badge-warn"
    return "mdr-badge-neutral"


def _exec_label(mode: str | None) -> str:
    mapping = {
        "native_sdk": "Native SDK",
        "native_sdk_agentic": "Agentic",
        "deterministic_fallback": "Fallback",
        "deterministic": "Deterministic",
    }
    return mapping.get(mode or "", (mode or "unknown").replace("_", " ").title())


PROVIDER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "claude-sonnet-4-6": "Claude Sonnet 4.6",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    },
    "openai": {
        "gpt-4.1-mini": "GPT-4.1 Mini",
        "gpt-5-mini": "GPT-5 Mini",
        "gpt-5": "GPT-5",
        "gpt-5.2": "GPT-5.2",
    },
    "google": {
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
        "gemini-3-flash-preview": "Gemini 3.0 Flash Preview",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
    },
}


_I18N: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "Medical Deep Research",
        "app_subtitle": "Agentic Evidence Synthesis Engine",
        "new_research": "New Research",
        "new_research_desc": "Enter a clinical or healthcare question",
        "query_type": "Query type",
        "free_form": "Free-form",
        "provider": "Provider",
        "language": "Language",
        "model": "Model",
        "start_run": "Start Research Run",
        "set_api_key": "Set API key below to enable",
        "provider_status": "Provider Status",
        "api_keys": "API Keys",
        "api_keys_desc": "Keys are stored locally in the database",
        "save_keys": "Save Keys",
        "research_runs": "Research Runs",
        "no_runs": "No runs yet.",
        "select_run": "Select a run to inspect",
        "select_run_desc": "Create a new research run or select an existing one from the sidebar to view its execution trace, artifacts, and final report.",
        "execution_trace": "Execution Trace",
        "events": "events",
        "waiting_events": "Waiting for events...",
        "no_artifacts": "No artifacts yet.",
        "report_title": "Report",
        "report_not_started": "_Report not started yet._",
        "run_diagnostics": "Run Diagnostics",
        "no_diagnostics": "No diagnostics available.",
        "population": "Population",
        "intervention": "Intervention",
        "comparison": "Comparison",
        "outcome": "Outcome",
        "concept": "Concept",
        "context": "Context",
        "research_question": "Research question",
        "query_required": "Query is required",
        "pico_required": "Population and Intervention are required for PICO",
        "pcc_required": "Population and Concept are required for PCC",
        "keys_saved": "API keys saved",
        "interrupt": "Interrupt",
        "cancel": "Cancel",
    },
    "ko": {
        "app_title": "Medical Deep Research",
        "app_subtitle": "에이전트 기반 근거 합성 엔진",
        "new_research": "새 연구",
        "new_research_desc": "임상 또는 보건의료 질문을 입력하세요",
        "query_type": "질문 유형",
        "free_form": "자유 형식",
        "provider": "제공자",
        "language": "언어",
        "model": "모델",
        "start_run": "연구 실행 시작",
        "set_api_key": "아래에서 API 키를 설정하세요",
        "provider_status": "제공자 상태",
        "api_keys": "API 키",
        "api_keys_desc": "키는 로컬 데이터베이스에 저장됩니다",
        "save_keys": "키 저장",
        "research_runs": "연구 기록",
        "no_runs": "연구 기록이 없습니다.",
        "select_run": "연구를 선택하세요",
        "select_run_desc": "새 연구를 시작하거나 사이드바에서 기존 연구를 선택하여 실행 추적, 산출물, 최종 보고서를 확인하세요.",
        "execution_trace": "실행 추적",
        "events": "이벤트",
        "waiting_events": "이벤트 대기 중...",
        "no_artifacts": "산출물이 없습니다.",
        "report_title": "보고서",
        "report_not_started": "_보고서가 아직 시작되지 않았습니다._",
        "run_diagnostics": "실행 진단",
        "no_diagnostics": "진단 정보가 없습니다.",
        "population": "대상 집단 (Population)",
        "intervention": "중재 (Intervention)",
        "comparison": "비교군 (Comparison)",
        "outcome": "결과 (Outcome)",
        "concept": "개념 (Concept)",
        "context": "맥락 (Context)",
        "research_question": "연구 질문",
        "query_required": "질문을 입력해야 합니다",
        "pico_required": "PICO 형식에는 대상 집단과 중재가 필요합니다",
        "pcc_required": "PCC 형식에는 대상 집단과 개념이 필요합니다",
        "keys_saved": "API 키가 저장되었습니다",
        "interrupt": "중단",
        "cancel": "취소",
    },
}


def _t(lang: str, key: str) -> str:
    return _I18N.get(lang, _I18N["en"]).get(key, _I18N["en"].get(key, key))


def _bool_badge(label: str, value: Any) -> None:
    if value is True:
        ui.html(f'<span class="mdr-badge mdr-badge-success">{label}: yes</span>')
    elif value is False:
        ui.html(f'<span class="mdr-badge mdr-badge-error">{label}: no</span>')
    else:
        ui.html(f'<span class="mdr-badge mdr-badge-neutral">{label}: ?</span>')


def build_ui(service: ResearchService) -> None:
    ui.add_css(_CUSTOM_CSS)

    def index() -> None:
        selected: dict[str, str | None] = {"run_id": None, "active_tab": "trace"}
        page_state: dict[str, int] = {"page": 0, "per_page": 15}

        def t(key: str) -> str:
            return _t(form_state.get("language", "en"), key)

        form_state: dict[str, Any] = {
            "query": "",
            "query_type": "free",
            "language": service.get_language(),
            "provider": "anthropic",
            "model": DEFAULT_MODELS["anthropic"],
            # PICO structured fields
            "pico_p": "",
            "pico_i": "",
            "pico_c": "",
            "pico_o": "",
            # PCC structured fields
            "pcc_p": "",
            "pcc_concept": "",
            "pcc_context": "",
        }

        def choose_run(run_id: str) -> None:
            selected["run_id"] = run_id
            detail_panel.refresh()

        def on_provider_change(provider: str) -> None:
            form_state["provider"] = provider
            models = PROVIDER_MODELS.get(provider)
            if models:
                form_state["model"] = next(iter(models))
            else:
                form_state["model"] = DEFAULT_MODELS.get(provider, "")
            model_selector.refresh()
            provider_diagnostics.refresh()

        async def start_run() -> None:
            qt = form_state["query_type"]
            query_payload: dict[str, Any] = {}
            if qt == "pico":
                p, i, c, o = (form_state["pico_p"].strip(), form_state["pico_i"].strip(),
                              form_state["pico_c"].strip(), form_state["pico_o"].strip())
                if not p and not i:
                    ui.notify(t("pico_required"), type="negative")
                    return
                query_payload = {"population": p, "intervention": i, "comparison": c, "outcome": o}
                query = f"Population: {p}; Intervention: {i}; Comparison: {c}; Outcome: {o}"
            elif qt == "pcc":
                p, concept, context = (form_state["pcc_p"].strip(), form_state["pcc_concept"].strip(),
                                       form_state["pcc_context"].strip())
                if not p and not concept:
                    ui.notify(t("pcc_required"), type="negative")
                    return
                query_payload = {"population": p, "concept": concept, "context": context}
                query = f"Population: {p}; Concept: {concept}; Context: {context}"
            else:
                query = form_state["query"].strip()
                if not query:
                    ui.notify(t("query_required"), type="negative")
                    return
            run = service.create_run(
                query=query,
                query_type=qt,
                provider=form_state["provider"],
                model=form_state["model"],
                query_payload=query_payload or None,
            )
            selected["run_id"] = run.id
            run_list.refresh()
            detail_panel.refresh()
            ui.notify(f"Run {run.id[:8]} started", type="positive")

        def interrupt_selected() -> None:
            if selected["run_id"]:
                service.interrupt_run(selected["run_id"])
                detail_panel.refresh()
                run_list.refresh()

        def cancel_selected() -> None:
            if selected["run_id"]:
                service.cancel_run(selected["run_id"])
                detail_panel.refresh()
                run_list.refresh()

        # -- Header --
        with ui.header().classes("mdr-header items-center justify-between"):
            with ui.row().classes("items-center gap-3"):
                ui.html(f'<span class="mdr-title">{t("app_title")}</span>')
            ui.html(f'<span class="mdr-subtitle">{t("app_subtitle")}</span>')

        # -- Main layout --
        with ui.row().classes("w-full items-start gap-5 p-5"):

            # ===== LEFT PANEL =====
            with ui.column().classes("w-[28rem] max-w-full gap-4"):

                # New Research form
                with ui.card().classes("mdr-card w-full p-5"):
                    ui.html(f'<div class="mdr-section-title">{t("new_research")}</div>')
                    ui.html(f'<div class="mdr-section-desc" style="margin-bottom:0.75rem">{t("new_research_desc")}</div>')

                    with ui.row().classes("w-full gap-3"):
                        ui.select(
                            {"free": t("free_form"), "pico": "PICO", "pcc": "PCC"},
                            label=t("query_type"),
                            value=form_state["query_type"],
                            on_change=lambda _: structured_input.refresh(),
                        ).props("outlined dark dense").bind_value(form_state, "query_type").classes("flex-1")

                        provider_select = ui.select(
                            {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "local": "Local (Ollama)"},
                            label=t("provider"),
                            value=form_state["provider"],
                            on_change=lambda e: on_provider_change(e.value),
                        ).props("outlined dark dense").classes("flex-1")
                        provider_select.bind_value(form_state, "provider")

                        def on_language_change(e: Any) -> None:
                            form_state["language"] = e.value
                            service.set_language(e.value)

                        ui.select(
                            {"en": "English", "ko": "한국어"},
                            label=t("language"),
                            value=form_state["language"],
                            on_change=on_language_change,
                        ).props("outlined dark dense").classes("w-24")

                    @ui.refreshable
                    def structured_input() -> None:
                        qt = form_state["query_type"]
                        if qt == "pico":
                            ui.input(label=t("population"), placeholder="e.g. Adults with HFpEF").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pico_p")
                            ui.input(label=t("intervention"), placeholder="e.g. SGLT2 inhibitors").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pico_i")
                            ui.input(label=t("comparison"), placeholder="e.g. Placebo or standard care").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pico_c")
                            ui.input(label=t("outcome"), placeholder="e.g. Hospitalisation, mortality").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pico_o")
                        elif qt == "pcc":
                            ui.input(label=t("population"), placeholder="e.g. Elderly patients with diabetes").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pcc_p")
                            ui.input(label=t("concept"), placeholder="e.g. Self-management strategies").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pcc_concept")
                            ui.input(label=t("context"), placeholder="e.g. Primary care settings").props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, "pcc_context")
                        else:
                            query_input = ui.textarea(
                                label=t("research_question"),
                                placeholder="e.g. What is the evidence for SGLT2 inhibitors in heart failure with preserved ejection fraction?",
                                value=form_state["query"],
                            ).props("autogrow outlined dark").classes("w-full")
                            query_input.bind_value(form_state, "query")

                    structured_input()

                    @ui.refreshable
                    def model_selector() -> None:
                        provider = form_state["provider"]
                        models = PROVIDER_MODELS.get(provider)
                        if models:
                            api_keys = service.get_api_keys()
                            has_key = provider in api_keys and bool(api_keys[provider].strip())
                            sel = ui.select(
                                models,
                                label="Model",
                                value=form_state["model"],
                            ).props("outlined dark dense").classes("w-full")
                            sel.bind_value(form_state, "model")
                            if not has_key and provider != "local":
                                sel.props("disable")
                                ui.html(
                                    f'<span style="font-size:0.7rem; color: var(--error)">'
                                    f'{t("set_api_key")}</span>'
                                )
                        else:
                            # Local / unknown provider: free-form input
                            local_input = ui.input(
                                label="Model", value=form_state["model"],
                            ).props("outlined dark dense").classes("w-full")
                            local_input.bind_value(form_state, "model")

                    model_selector()

                    ui.button(t("start_run"), on_click=start_run).classes("mdr-btn-primary w-full")

                # Provider diagnostics (collapsible)
                @ui.refreshable
                def provider_diagnostics() -> None:
                    diagnostics = service.get_provider_diagnostics()
                    with ui.expansion(t("provider_status"), icon="dns").classes("mdr-card w-full").props("dense"):
                        for entry in diagnostics:
                            is_selected = entry["provider"] == form_state["provider"]
                            card_cls = "mdr-diag-card mdr-diag-card-selected" if is_selected else "mdr-diag-card"
                            with ui.column().classes(f"{card_cls} w-full gap-1 mt-2"):
                                with ui.row().classes("w-full items-center justify-between"):
                                    ui.label(entry["provider"].title()).style(
                                        "font-weight:600; font-size:0.85rem; color: var(--text-primary)"
                                    )
                                    ui.html(
                                        f'<span class="mdr-badge {_exec_badge_class(entry["active_execution_path"])}">'
                                        f'{_exec_label(entry["active_execution_path"])}</span>'
                                    )
                                ui.label(entry["runtime_name"]).style(
                                    "font-size:0.72rem; color: var(--text-muted); font-family: 'IBM Plex Mono', monospace"
                                )
                                with ui.row().classes("flex-wrap gap-1 mt-1"):
                                    _bool_badge("SDK", entry["sdk_available"])
                                    _bool_badge("Key", entry["provider_credentials_present"])
                                    _bool_badge("Online", not entry["offline_mode"])
                                if entry.get("fallback_reason"):
                                    ui.label(entry["fallback_reason"]).style(
                                        "font-size:0.7rem; color: var(--warn); margin-top:0.25rem"
                                    )

                provider_diagnostics()

                # API Keys (collapsible)
                with ui.expansion(t("api_keys"), icon="key").classes("mdr-card w-full").props("dense"):
                    ui.html(f'<div class="mdr-section-desc" style="margin-bottom:0.5rem">{t("api_keys_desc")}</div>')
                    stored_keys = service.get_api_keys()
                    key_fields: dict[str, Any] = {}
                    for svc, label in [
                        ("openai", "OpenAI"),
                        ("anthropic", "Anthropic"),
                        ("google", "Google"),
                        ("ncbi", "NCBI (E-utilities)"),
                        ("scopus", "Scopus / Elsevier"),
                        ("semantic_scholar", "Semantic Scholar"),
                    ]:
                        key_fields[svc] = ui.input(
                            label=f"{label} API Key",
                            value=stored_keys.get(svc, ""),
                            password=True,
                            password_toggle_button=True,
                        ).props("outlined dark dense").classes("w-full")

                    def save_keys() -> None:
                        for svc, field in key_fields.items():
                            val = field.value.strip()
                            if val:
                                service.save_api_key(svc, val)
                        ui.notify(t("keys_saved"), type="positive")
                        provider_diagnostics.refresh()
                        model_selector.refresh()

                    ui.button(t("save_keys"), on_click=save_keys).props("outline size=sm").style(
                        "color: var(--accent); border-color: var(--accent); margin-top: 0.5rem"
                    )

                # Recent runs
                def prev_page() -> None:
                    if page_state["page"] > 0:
                        page_state["page"] -= 1
                        run_list.refresh()

                def next_page() -> None:
                    page_state["page"] += 1
                    run_list.refresh()

                @ui.refreshable
                def run_list() -> None:
                    pp = page_state["per_page"]
                    offset = page_state["page"] * pp
                    total = service.count_runs()
                    runs = service.list_runs(limit=pp, offset=offset)
                    with ui.card().classes("mdr-card w-full p-4"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.html(f'<div class="mdr-section-title">{t("research_runs")}</div>')
                            if total > 0:
                                ui.html(
                                    f'<span class="mdr-section-desc">'
                                    f'{offset + 1}–{min(offset + pp, total)} of {total}</span>'
                                )
                        if not runs:
                            ui.label(t("no_runs")).style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                            return
                        with ui.column().classes("w-full gap-1 mt-2"):
                            for run in runs:
                                is_sel = selected["run_id"] == run.id
                                item_cls = "mdr-run-item mdr-run-item-selected" if is_sel else "mdr-run-item"
                                with ui.row().classes(f"{item_cls} w-full items-center justify-between").on(
                                    "click", lambda _, rid=run.id: choose_run(rid)
                                ):
                                    with ui.column().classes("gap-0 min-w-0 flex-1"):
                                        ui.label(run.query[:80]).style(
                                            "font-size: 0.8rem; color: var(--text-primary); white-space: nowrap; "
                                            "overflow: hidden; text-overflow: ellipsis; max-width: 100%"
                                        )
                                        ui.label(
                                            f"{run.provider} / {run.model}"
                                        ).style("font-size: 0.65rem; color: var(--text-muted); font-family: 'IBM Plex Mono', monospace")
                                    ui.html(f'<span class="mdr-badge {_status_badge_class(run.status)}">{run.status}</span>')
                        if total > pp:
                            with ui.row().classes("w-full justify-center gap-2 mt-2"):
                                ui.button(icon="chevron_left", on_click=prev_page).props(
                                    "flat dense round" + (" disable" if page_state["page"] == 0 else "")
                                ).style("color: var(--text-secondary)")
                                ui.button(icon="chevron_right", on_click=next_page).props(
                                    "flat dense round" + (" disable" if offset + pp >= total else "")
                                ).style("color: var(--text-secondary)")

                run_list()

            # ===== RIGHT PANEL =====
            with ui.column().classes("min-w-0 flex-1 gap-4"):

                @ui.refreshable
                def detail_panel() -> None:
                    run_id = selected["run_id"]
                    run = service.get_run(run_id) if run_id else None
                    run_diag = service.get_run_diagnostics(run_id) if run_id else None

                    if run is None:
                        with ui.card().classes("mdr-card w-full p-8"):
                            with ui.column().classes("items-center gap-3"):
                                ui.html(
                                    '<div style="font-family: Playfair Display, serif; font-size: 1.3rem; '
                                    f'color: var(--text-muted); font-weight: 500">{t("select_run")}</div>'
                                )
                                ui.html(
                                    '<div style="font-size: 0.8rem; color: var(--text-muted); max-width: 30rem; text-align: center">'
                                    'Create a new research run or select an existing one from the sidebar to view '
                                    f'{t("select_run_desc")}</div>'
                                )
                        return

                    # Run header card
                    with ui.card().classes("mdr-card mdr-card-active w-full p-5"):
                        ui.label(run.query).style(
                            "font-family: 'Playfair Display', serif; font-size: 1.15rem; font-weight: 700; "
                            "color: var(--text-primary); line-height: 1.4"
                        )
                        with ui.row().classes("items-center gap-2 mt-2"):
                            ui.html(f'<span class="mdr-badge {_status_badge_class(run.status)}">{run.status}</span>')
                            ui.html(f'<span class="mdr-badge mdr-badge-neutral">{run.runtime_name}</span>')
                            if run_diag:
                                exec_mode = run_diag.get("execution_mode")
                                ui.html(f'<span class="mdr-badge {_exec_badge_class(exec_mode)}">{_exec_label(exec_mode)}</span>')
                            ui.html(f'<span class="mdr-badge mdr-badge-neutral">{run.progress}%</span>')
                        ui.linear_progress(value=run.progress / 100).classes("mdr-progress w-full mt-3")
                        if run_diag and run_diag.get("fallback_reason"):
                            ui.label(run_diag["fallback_reason"]).style(
                                "font-size: 0.75rem; color: var(--warn); margin-top: 0.5rem"
                            )
                        with ui.row().classes("gap-2 mt-3"):
                            ui.button(t("interrupt"), on_click=interrupt_selected).props(
                                "outline size=sm"
                            ).style("color: var(--text-secondary); border-color: var(--border-dim)")
                            ui.button(t("cancel"), on_click=cancel_selected).props(
                                "outline size=sm"
                            ).style("color: var(--error); border-color: var(--error)")

                    # Tabs
                    artifacts = service.list_artifacts(run.id)
                    events = service.list_events(run.id)

                    def on_tab_change(e: Any) -> None:
                        selected["active_tab"] = e.value

                    _active_tab_name: str = selected.get("active_tab") or "trace"  # type: ignore[assignment]

                    with ui.tabs(
                        value=_active_tab_name,  # type: ignore[arg-type]
                        on_change=on_tab_change,
                    ).classes("mdr-tabs w-full") as tabs:
                        trace_tab = ui.tab("trace")
                        artifacts_tab = ui.tab("artifacts")
                        report_tab = ui.tab("report")
                        diag_tab = ui.tab("diagnostics")

                    _tab_map = {"trace": trace_tab, "artifacts": artifacts_tab, "report": report_tab, "diagnostics": diag_tab}
                    _active = _tab_map.get(_active_tab_name, trace_tab)

                    with ui.tab_panels(tabs, value=_active).classes("w-full").style("background: transparent !important"):

                        with ui.tab_panel(trace_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html(f'<div class="mdr-section-title">{t("execution_trace")}</div>')
                                ui.html(f'<div class="mdr-section-desc">{len(events)} events</div>')
                                if not events:
                                    ui.label(t("waiting_events")).style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                                with ui.column().classes("w-full gap-0 mt-3"):
                                    for event in events[-50:]:
                                        with ui.row().classes("mdr-trace-item w-full items-start gap-3"):
                                            ui.html(f'<span class="mdr-trace-seq">{event.sequence:02d}</span>')
                                            with ui.column().classes("gap-0 min-w-0 flex-1"):
                                                ui.html(f'<span class="mdr-trace-msg">{event.message}</span>')
                                                meta_parts = [event.phase, event.event_type, f"{event.progress}%"]
                                                if event.tool_name:
                                                    meta_parts.append(event.tool_name)
                                                if event.agent_name:
                                                    meta_parts.append(event.agent_name)
                                                ui.html(f'<span class="mdr-trace-meta">{" · ".join(meta_parts)}</span>')

                        with ui.tab_panel(artifacts_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html('<div class="mdr-section-title">Artifacts</div>')
                                ui.html(f'<div class="mdr-section-desc">{len(artifacts)} artifacts</div>')
                                if not artifacts:
                                    ui.label(t("no_artifacts")).style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                                for artifact in artifacts:
                                    with ui.expansion(
                                        f"{artifact.artifact_type}: {artifact.name}",
                                        icon="description",
                                    ).classes("w-full"):
                                        if artifact.content_text:
                                            ui.markdown(f"```\n{artifact.content_text}\n```")
                                        if artifact.content_json:
                                            ui.code(artifact.content_json, language="json").classes("w-full")

                        with ui.tab_panel(report_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-5"):
                                ui.html('<div class="mdr-section-title" style="margin-bottom:1rem">Report</div>')
                                ui.markdown(
                                    run.result_markdown or t("report_not_started")
                                ).classes("mdr-report w-full")

                        with ui.tab_panel(diag_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html(f'<div class="mdr-section-title">{t("run_diagnostics")}</div>')
                                if not run_diag:
                                    ui.label(t("no_diagnostics")).style("color: var(--text-muted)")
                                else:
                                    with ui.row().classes("flex-wrap gap-1 mt-2"):
                                        exec_mode = run_diag.get("execution_mode")
                                        ui.html(f'<span class="mdr-badge {_exec_badge_class(exec_mode)}">{_exec_label(exec_mode)}</span>')
                                        _bool_badge("SDK", run_diag.get("sdk_available"))
                                        _bool_badge("Key", run_diag.get("provider_credentials_present"))
                                        _bool_badge("Online", not run_diag.get("offline_mode", False))
                                    ui.label(
                                        f"{run_diag.get('runtime_name', '')} · {run_diag.get('model', '')}"
                                    ).style("font-size: 0.75rem; color: var(--text-muted); font-family: 'IBM Plex Mono', monospace; margin-top: 0.5rem")
                                    if run_diag.get("ranked_results") is not None:
                                        ui.label(f"Ranked results: {run_diag['ranked_results']}").style(
                                            "font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem"
                                        )
                                    if run_diag.get("fallback_reason"):
                                        ui.label(run_diag["fallback_reason"]).style(
                                            "font-size: 0.75rem; color: var(--warn); margin-top: 0.25rem"
                                        )
                                    ui.code(
                                        json.dumps(run_diag, indent=2), language="json"
                                    ).classes("w-full mt-3")

                detail_panel()

        def _on_service_change(run_id: str, change_type: str) -> None:
            """Push-based UI update triggered by service state changes."""
            run_list.refresh()
            if selected["run_id"] == run_id:
                detail_panel.refresh()

        service.add_ui_listener(_on_service_change)

    index()
