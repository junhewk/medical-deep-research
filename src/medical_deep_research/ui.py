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
        selected: dict[str, str | None] = {"run_id": None}
        form_state: dict[str, Any] = {
            "query": "",
            "query_type": "free",
            "provider": "anthropic",
            "model": DEFAULT_MODELS["anthropic"],
        }

        def choose_run(run_id: str) -> None:
            selected["run_id"] = run_id
            detail_panel.refresh()

        def on_provider_change(provider: str) -> None:
            form_state["provider"] = provider
            form_state["model"] = DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"])
            provider_diagnostics.refresh()

        async def start_run() -> None:
            if not form_state["query"].strip():
                ui.notify("Query is required", type="negative")
                return
            run = service.create_run(
                query=form_state["query"],
                query_type=form_state["query_type"],
                provider=form_state["provider"],
                model=form_state["model"],
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
                ui.html('<span class="mdr-title">Medical Deep Research</span>')
            ui.html('<span class="mdr-subtitle">Agentic Evidence Synthesis Engine</span>')

        # -- Main layout --
        with ui.row().classes("w-full items-start gap-5 p-5"):

            # ===== LEFT PANEL =====
            with ui.column().classes("w-[28rem] max-w-full gap-4"):

                # New Research form
                with ui.card().classes("mdr-card w-full p-5"):
                    ui.html('<div class="mdr-section-title">New Research</div>')
                    ui.html('<div class="mdr-section-desc" style="margin-bottom:0.75rem">Enter a clinical or healthcare question</div>')
                    query_input = ui.textarea(
                        label="Research question",
                        placeholder="e.g. What is the evidence for SGLT2 inhibitors in heart failure with preserved ejection fraction?",
                        value=form_state["query"],
                    ).props("autogrow outlined dark").classes("w-full")
                    query_input.bind_value(form_state, "query")

                    with ui.row().classes("w-full gap-3"):
                        ui.select(
                            {"free": "Free-form", "pico": "PICO", "pcc": "PCC"},
                            label="Query type",
                            value=form_state["query_type"],
                        ).props("outlined dark dense").bind_value(form_state, "query_type").classes("flex-1")

                        provider_select = ui.select(
                            {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google"},
                            label="Provider",
                            value=form_state["provider"],
                            on_change=lambda e: on_provider_change(e.value),
                        ).props("outlined dark dense").classes("flex-1")
                        provider_select.bind_value(form_state, "provider")

                    model_input = ui.input(label="Model", value=form_state["model"]).props("outlined dark dense").classes("w-full")
                    model_input.bind_value(form_state, "model")

                    ui.button("Start Research Run", on_click=start_run).classes("mdr-btn-primary w-full")

                # Provider diagnostics
                @ui.refreshable
                def provider_diagnostics() -> None:
                    diagnostics = service.get_provider_diagnostics()
                    with ui.card().classes("mdr-card w-full p-4"):
                        ui.html('<div class="mdr-section-title">Provider Status</div>')
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

                # Recent runs
                @ui.refreshable
                def run_list() -> None:
                    with ui.card().classes("mdr-card w-full p-4"):
                        ui.html('<div class="mdr-section-title">Recent Runs</div>')
                        runs = service.list_runs()
                        if not runs:
                            ui.label("No runs yet.").style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                            return
                        with ui.column().classes("w-full gap-1 mt-2"):
                            for run in runs[:20]:
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
                                    'color: var(--text-muted); font-weight: 500">Select a run to inspect</div>'
                                )
                                ui.html(
                                    '<div style="font-size: 0.8rem; color: var(--text-muted); max-width: 30rem; text-align: center">'
                                    'Create a new research run or select an existing one from the sidebar to view '
                                    'its execution trace, artifacts, and final report.</div>'
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
                            ui.button("Interrupt", on_click=interrupt_selected).props(
                                "outline size=sm"
                            ).style("color: var(--text-secondary); border-color: var(--border-dim)")
                            ui.button("Cancel", on_click=cancel_selected).props(
                                "outline size=sm"
                            ).style("color: var(--error); border-color: var(--error)")

                    # Tabs
                    artifacts = service.list_artifacts(run.id)
                    events = service.list_events(run.id)

                    with ui.tabs().classes("mdr-tabs w-full") as tabs:
                        trace_tab = ui.tab("trace")
                        artifacts_tab = ui.tab("artifacts")
                        report_tab = ui.tab("report")
                        diag_tab = ui.tab("diagnostics")

                    with ui.tab_panels(tabs, value=trace_tab).classes("w-full").style("background: transparent !important"):

                        with ui.tab_panel(trace_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html('<div class="mdr-section-title">Execution Trace</div>')
                                ui.html(f'<div class="mdr-section-desc">{len(events)} events</div>')
                                if not events:
                                    ui.label("Waiting for events...").style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
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
                                    ui.label("No artifacts yet.").style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
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
                                    run.result_markdown or "_Report not started yet._"
                                ).classes("mdr-report w-full")

                        with ui.tab_panel(diag_tab).style("background: transparent !important; padding: 0 !important"):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html('<div class="mdr-section-title">Run Diagnostics</div>')
                                if not run_diag:
                                    ui.label("No diagnostics available.").style("color: var(--text-muted)")
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

        ui.timer(1.5, run_list.refresh)
        ui.timer(2.0, provider_diagnostics.refresh)
        ui.timer(1.5, detail_panel.refresh)

    index()
