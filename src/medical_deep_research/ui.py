from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from .reading_service import ReadingService
from .service import DEFAULT_MODELS, ResearchService


_CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700;900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, .q-page { overflow: hidden !important; }

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

/* Query type segmented control */
.mdr-query-toggle .q-btn {
    background: var(--bg-surface) !important;
    color: var(--text-secondary) !important;
    border: 1px solid var(--border-dim) !important;
    min-height: 2.5rem !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}
.mdr-query-toggle .q-btn.q-btn--active {
    background: var(--accent-dim) !important;
    color: var(--accent) !important;
    border-color: var(--border-active) !important;
    box-shadow: inset 0 0 0 1px rgba(45, 212, 168, 0.16) !important;
}
.mdr-query-toggle .q-btn:before,
.mdr-query-toggle .q-btn:after {
    box-shadow: none !important;
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

/* Study cards */
.mdr-study-card {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-dim) !important;
    border-radius: 6px !important;
    padding: 0.7rem 0.9rem !important;
    min-width: 13rem;
    max-width: 15rem;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    box-shadow: none !important;
    flex-shrink: 0;
}
.mdr-study-card:hover {
    border-color: var(--text-muted) !important;
    background: var(--bg-card) !important;
}
.mdr-study-card-selected {
    border-color: var(--accent) !important;
    background: var(--accent-dim) !important;
}
.mdr-study-title {
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 600;
    font-size: 0.78rem;
    color: var(--text-primary);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.mdr-evidence-badge {
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    font-weight: 500;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    color: var(--text-primary);
}
.mdr-evidence-I   { background: #1a3d2a; color: #4ade80; }
.mdr-evidence-II  { background: #1a2d3d; color: #60a5fa; }
.mdr-evidence-III { background: #3d3a1a; color: #facc15; }
.mdr-evidence-IV  { background: #3d2a1a; color: #fb923c; }
.mdr-evidence-V   { background: #2a2a2a; color: #9ca3af; }
.mdr-evidence-NA  { background: #1e1e1e; color: #6b7280; }

/* Chat */
.mdr-chat-panel-wrapper {
    overflow: hidden !important;
}
.mdr-chat-card {
    display: flex !important;
    flex-direction: column !important;
    flex: 1 1 0 !important;
    min-height: 200px;
    overflow: hidden;
}
.mdr-chat-scroll {
    overflow-y: auto;
    flex: 1 1 0;
    min-height: 0;
    scroll-behavior: smooth;
    padding-bottom: 0.5rem;
}
.mdr-chat-msg {
    padding: 0.65rem 0.85rem;
    border-radius: 6px;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.82rem;
    line-height: 1.55;
    color: var(--text-secondary);
    max-width: 92%;
}
.mdr-chat-msg-assistant {
    background: var(--bg-surface);
    border: 1px solid var(--border-dim);
    border-left: 2px solid var(--accent);
}
.mdr-chat-msg-user {
    background: var(--accent-dim);
    border: 1px solid var(--accent);
    margin-left: auto;
}
.mdr-chat-msg p { margin: 0.25rem 0; }
.mdr-chat-msg strong { color: var(--text-primary); }
.mdr-ref-link {
    color: var(--accent);
    cursor: pointer;
    font-weight: 600;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 2px;
    transition: color 0.15s;
}
.mdr-ref-link:hover { color: var(--text-primary); }
.mdr-ref-popover {
    position: fixed;
    z-index: 9999;
    background: var(--bg-card);
    border: 1px solid var(--border-dim);
    border-left: 2px solid var(--accent);
    border-radius: 6px;
    padding: 0.75rem 0.9rem;
    max-width: 370px;
    min-width: 220px;
    box-shadow: 0 8px 28px rgba(0,0,0,0.55);
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.76rem;
    color: var(--text-secondary);
    line-height: 1.5;
    display: none;
}
.mdr-ref-popover-title {
    color: var(--text-primary);
    font-weight: 600;
    font-size: 0.8rem;
    margin-bottom: 0.3rem;
    line-height: 1.4;
}
.mdr-ref-popover-meta {
    color: var(--text-muted);
    font-size: 0.7rem;
    margin-top: 0.1rem;
}
.mdr-scope-indicator {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    color: var(--accent);
    padding: 0.15rem 0.5rem;
    background: var(--accent-dim);
    border-radius: 3px;
}

/* Side-by-side reading layout — fills available viewport */
.mdr-reading-panel {
    overflow-y: auto;
    height: var(--reading-panel-h, 65vh);
    padding-right: 0.5rem;
}

/* Compact run status bar */
.mdr-status-bar {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-dim) !important;
    border-radius: 5px !important;
    padding: 0.55rem 0.9rem !important;
    position: relative;
    overflow: visible;
}
.mdr-status-bar .q-btn {
    min-height: 0 !important;
    padding: 0.15rem 0.5rem !important;
}
.mdr-status-bar::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    height: 2px;
    width: var(--mdr-progress, 0%);
    background: linear-gradient(90deg, var(--accent), rgba(45, 212, 168, 0.3));
    transition: width 0.5s ease;
}
.mdr-status-query {
    font-family: 'Playfair Display', serif;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
}
.mdr-tool-btn {
    font-size: 0.7rem !important;
    padding: 0.25rem 0.6rem !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}

/* Highlights */
.mdr-highlight-item {
    background: var(--bg-surface);
    border: 1px solid var(--border-dim);
    border-left: 2px solid var(--warn);
    border-radius: 4px;
    padding: 0.4rem 0.6rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    line-height: 1.4;
    cursor: pointer;
    transition: border-color 0.15s;
}
.mdr-highlight-item:hover {
    border-color: var(--accent);
}
.mdr-highlight-text {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-style: italic;
}

/* Floating selection toolbar */
#mdr-sel-toolbar {
    display: none;
    position: fixed;
    z-index: 10001;
    background: var(--bg-card);
    border: 1px solid var(--accent);
    border-radius: 6px;
    padding: 0.25rem 0.3rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    gap: 0.2rem;
}
#mdr-sel-toolbar.visible { display: flex; }
#mdr-sel-toolbar button {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.7rem;
    font-weight: 500;
    padding: 0.25rem 0.55rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.1s;
}
#mdr-sel-toolbar .sel-ask {
    background: var(--accent);
    color: var(--bg-deep);
}
#mdr-sel-toolbar .sel-save {
    background: transparent;
    color: var(--warn);
    border: 1px solid var(--warn);
}
#mdr-sel-toolbar button:hover { opacity: 0.85; }
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
    if mode in {"native_sdk", "native_sdk_agentic"}:
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
        "studies": "Studies",
        "studies_not_available": "Complete a research run to discuss studies.",
        "no_study_selected": "Select a study card above to start a discussion.",
        "compare_selected": "Compare Selected",
        "fetch_fulltext": "Fetch Full Text",
        "fetching_fulltext": "Fetching...",
        "fulltext_fetched": "Full text fetched",
        "fulltext_failed": "Could not fetch full text",
        "send": "Send",
        "discussing_study": "Discussing Study",
        "comparing_studies": "Comparing Studies",
        "all_studies": "All Studies",
        "tool_structure": "Structure",
        "tool_findings": "Key Findings",
        "tool_citations": "Citations",
        "tool_critical": "Critical Reading",
        "ask_selected": "Ask Selected",
        "save_selected": "Save Highlight",
        "export_notes": "Export Notes",
        "saved_highlights": "Saved Highlights",
        "notes_copied": "Notes copied to clipboard",
        "no_notes": "No discussion yet to export.",
        "highlight_saved": "Highlight saved",
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
        "studies": "논문 토론",
        "studies_not_available": "연구 실행을 완료하면 논문을 토론할 수 있습니다.",
        "no_study_selected": "위에서 논문 카드를 선택하여 토론을 시작하세요.",
        "compare_selected": "선택 논문 비교",
        "fetch_fulltext": "전문 가져오기",
        "fetching_fulltext": "가져오는 중...",
        "fulltext_fetched": "전문을 가져왔습니다",
        "fulltext_failed": "전문을 가져올 수 없습니다",
        "send": "보내기",
        "discussing_study": "논문 토론 중",
        "comparing_studies": "논문 비교 중",
        "all_studies": "전체 논문",
        "tool_structure": "구조 분석",
        "tool_findings": "주요 결과",
        "tool_citations": "인용 분석",
        "tool_critical": "비판적 읽기",
        "ask_selected": "선택 텍스트 질문",
        "save_selected": "하이라이트 저장",
        "export_notes": "노트 내보내기",
        "saved_highlights": "저장된 하이라이트",
        "notes_copied": "노트가 클립보드에 복사되었습니다",
        "no_notes": "아직 토론 내용이 없습니다.",
        "highlight_saved": "하이라이트가 저장되었습니다",
    },
}


_TAB_PANEL_STYLE = "background: transparent !important; padding: 0 !important"
_RECALC_PANEL_JS = "window._mdrRecalcPanelHeight && window._mdrRecalcPanelHeight()"


def _t(lang: str, key: str) -> str:
    return _I18N.get(lang, _I18N["en"]).get(key, _I18N["en"].get(key, key))


def _bool_badge(label: str, value: Any) -> None:
    if value is True:
        ui.html(f'<span class="mdr-badge mdr-badge-success">{label}: yes</span>')
    elif value is False:
        ui.html(f'<span class="mdr-badge mdr-badge-error">{label}: no</span>')
    else:
        ui.html(f'<span class="mdr-badge mdr-badge-neutral">{label}: ?</span>')


def _evidence_badge_class(level: str | None) -> str:
    if not level:
        return "mdr-evidence-NA"
    for roman in ("I", "II", "III", "IV", "V"):
        if roman in level:
            return f"mdr-evidence-{roman}"
    return "mdr-evidence-NA"


def _build_studies_panel(
    tab: Any,
    *,
    run: Any,
    reading_service: ReadingService,
    service: ResearchService,
    t: Any,
) -> None:
    """Build the Studies / Reading tab panel — side-by-side paper + chat."""
    import asyncio as _asyncio

    with ui.tab_panel(tab).style(_TAB_PANEL_STYLE):

        rs = reading_service.get_or_create_session(run.id)
        if not rs:
            ui.label(t("studies_not_available")).style("color: var(--text-muted)")
            return

        studies = reading_service.get_ranked_studies(run.id)
        if not studies:
            ui.label(t("studies_not_available")).style("color: var(--text-muted)")
            return

        reading_state: dict[str, Any] = {
            "selected_refs": [],
            "scope": None,
            "streaming": False,
        }

        # -- Study cards row --
        with ui.row().classes("w-full gap-2 pb-3").style("overflow-x: auto; flex-wrap: nowrap"):
            for study in studies:
                ref = study.reference_number
                ev_level = study.evidence_level or "N/A"
                ev_class = _evidence_badge_class(ev_level)
                score_pct = int(study.composite_score * 100)
                has_ft = reading_service.get_fulltext(run.id, ref) is not None if ref else False
                with ui.card().classes("mdr-study-card").props(f'data-ref="{ref}"') as card:
                    ui.html(f'<div class="mdr-study-title">#{ref} {study.title}</div>')
                    with ui.row().classes("items-center gap-1 mt-1"):
                        ui.html(f'<span class="mdr-evidence-badge {ev_class}">{ev_level}</span>')
                        ui.html(f'<span style="font-family: IBM Plex Mono, monospace; font-size: 0.65rem; color: var(--text-muted)">{score_pct}%</span>')
                        if has_ft:
                            ui.html('<span style="font-size: 0.6rem; color: var(--accent)">PDF</span>')

                    def _on_card_click(e: Any, r: int = ref) -> None:  # type: ignore[assignment]
                        reading_state["selected_refs"] = [r]
                        reading_state["scope"] = f"study:{r}"
                        main_area.refresh()

                    card.on("click", _on_card_click)

        # -- Main area (side-by-side) --
        @ui.refreshable
        def main_area() -> None:
            scope = reading_state["scope"]
            if not scope:
                with ui.card().classes("mdr-card w-full p-5"):
                    ui.label(t("no_study_selected")).style("color: var(--text-muted); font-size: 0.85rem")
                return

            if not scope.startswith("study:"):
                # Cross-study or session scope — chat only (no paper panel)
                with ui.column().classes("mdr-reading-panel mdr-chat-panel-wrapper gap-3 w-full"):
                    _build_chat_panel(scope)
                ui.timer(0.3, lambda: ui.run_javascript(_RECALC_PANEL_JS), once=True)
                return

            ref_n = int(scope.split(":")[1])
            study = next((x for x in studies if x.reference_number == ref_n), None)
            if not study:
                return
            fulltext = reading_service.get_fulltext(run.id, ref_n)

            # ===== SIDE-BY-SIDE LAYOUT =====
            with ui.row().classes("w-full items-start").style("flex-wrap: nowrap; gap: 0.75rem"):

                # ---- LEFT: Paper panel ----
                with ui.column().classes("mdr-reading-panel gap-3").style("flex: 1 1 50%; min-width: 0"):
                    with ui.card().classes("mdr-card w-full p-4"):
                        # Title
                        ui.label(study.title).style(
                            "font-family: 'Playfair Display', serif; font-size: 1.05rem; "
                            "font-weight: 700; color: var(--text-primary); line-height: 1.35"
                        )
                        authors_str = ", ".join(study.authors[:5])
                        if len(study.authors) > 5:
                            authors_str += " et al."
                        ui.label(authors_str).style("font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem")
                        ui.label(f"{study.journal or 'N/A'}, {study.publication_year or 'N/A'}").style(
                            "font-size: 0.72rem; color: var(--text-muted); font-style: italic"
                        )
                        # Badges
                        ev_class = _evidence_badge_class(study.evidence_level)
                        with ui.row().classes("items-center gap-1 mt-2 flex-wrap"):
                            ui.html(f'<span class="mdr-evidence-badge {ev_class}">{study.evidence_level or "N/A"}</span>')
                            ui.html(f'<span class="mdr-badge mdr-badge-neutral">Score {study.composite_score:.2f}</span>')
                            ui.html(f'<span class="mdr-badge mdr-badge-neutral">{study.citation_count} cit.</span>')
                            if study.doi:
                                doi_url = f"https://doi.org/{study.doi}"
                                ui.link("DOI", doi_url, new_tab=True).style(
                                    "font-size: 0.65rem; color: var(--accent)"
                                )
                            if study.pmid:
                                ui.html(f'<span class="mdr-badge mdr-badge-neutral">PMID {study.pmid}</span>')

                    # Floating selection toolbar — appears on text drag
                    _CLEAR_SEL_JS = (
                        "window._mdrSelectedText = '';"
                        "document.getElementById('mdr-sel-toolbar').classList.remove('visible')"
                    )

                    async def _get_and_clear_selection() -> str | None:
                        """Get selected text from JS and dismiss the toolbar. Returns None if too short."""
                        sel = await ui.run_javascript("window._mdrSelectedText || ''")
                        if not sel or len(sel) <= 3:
                            return None
                        await ui.run_javascript(_CLEAR_SEL_JS)
                        return sel

                    async def _sel_action(prompt_template: str) -> None:
                        sel = await _get_and_clear_selection()
                        if sel:
                            reading_state["_pending_msg"] = prompt_template.format(text=sel[:500])
                            main_area.refresh()

                    async def _save_selected() -> None:
                        sel = await _get_and_clear_selection()
                        if sel:
                            reading_service.save_highlight(rs.id, scope, sel)
                            ui.notify(t("highlight_saved"), type="positive")
                            main_area.refresh()

                    # Toolbar div — Ask, Citations, Critical Reading, Save
                    ui.html(f'''
                        <div id="mdr-sel-toolbar">
                            <button class="sel-ask" id="mdr-sel-ask">{t("ask_selected")}</button>
                            <button class="sel-ask" id="mdr-sel-cite">{t("tool_citations")}</button>
                            <button class="sel-ask" id="mdr-sel-crit">{t("tool_critical")}</button>
                            <button class="sel-save" id="mdr-sel-save">{t("save_selected")}</button>
                        </div>
                    ''')

                    # Hidden proxy buttons (JS → Python bridge)
                    _sel_prompts = {
                        "ask": 'Explain this passage: "{text}"',
                        "cite": 'Evaluate the citations and evidence supporting this passage: "{text}"',
                        "crit": 'Analyze the rhetoric in this passage. Distinguish evidence-backed claims from interpretive leaps, hedged language, and unsupported assertions: "{text}"',
                    }
                    for action_key, tmpl in _sel_prompts.items():
                        def _make_handler(prompt: str = tmpl) -> Any:
                            async def _h() -> None:
                                await _sel_action(prompt)
                            return _h
                        btn = ui.button("", on_click=_make_handler()).style("display:none")
                        btn.props(f'id="mdr-sel-{action_key}-proxy-{ref_n}"')

                    save_btn = ui.button("", on_click=_save_selected).style("display:none")
                    save_btn.props(f'id="mdr-sel-save-proxy-{ref_n}"')

                    # Wire JS events (runs after DOM renders)
                    _toolbar_js = f"""
                        window._mdrSelectedText = '';
                        var toolbar = document.getElementById('mdr-sel-toolbar');
                        if (toolbar && !toolbar._mdrBound) {{
                            toolbar._mdrBound = true;
                            document.addEventListener('mouseup', function(e) {{
                                var sel = window.getSelection().toString().trim();
                                if (sel.length > 3) {{
                                    window._mdrSelectedText = sel;
                                    toolbar.style.left = e.clientX + 'px';
                                    toolbar.style.top = (e.clientY - 40) + 'px';
                                    toolbar.classList.add('visible');
                                }} else {{
                                    toolbar.classList.remove('visible');
                                    window._mdrSelectedText = '';
                                }}
                            }});
                            document.addEventListener('mousedown', function(e) {{
                                if (!toolbar.contains(e.target)) {{
                                    toolbar.classList.remove('visible');
                                }}
                            }});
                            ['ask','cite','crit','save'].forEach(function(k) {{
                                var btn = document.getElementById('mdr-sel-' + k);
                                var proxy = document.getElementById('mdr-sel-' + k + '-proxy-{ref_n}');
                                if (btn && proxy) btn.addEventListener('click', function() {{ proxy.click(); }});
                            }});
                        }}
                    """
                    ui.timer(0.1, lambda: ui.run_javascript(_toolbar_js), once=True)

                    # Abstract
                    if study.abstract:
                        with ui.card().classes("mdr-card w-full p-4"):
                            ui.html('<div class="mdr-section-title" style="font-size: 0.82rem">Abstract</div>')
                            ui.label(study.abstract).style(
                                "font-size: 0.78rem; color: var(--text-secondary); line-height: 1.55; margin-top: 0.3rem"
                            )

                    # Full text
                    if fulltext:
                        with ui.card().classes("mdr-card w-full p-4"):
                            ui.html('<div class="mdr-section-title" style="font-size: 0.82rem">Full Text</div>')
                            ui.markdown(fulltext).classes("mdr-report mdr-reflink-target w-full")

                        # Link Vancouver [#] references in fulltext to paper's own bibliography
                        _link_refs_js = """
                            window._mdrLinkRefsRetry = 0;
                            window._mdrLinkRefs = function() {
                                var block = document.querySelector('.mdr-reflink-target');
                                if (block && !block.querySelector('h1,h2,h3,h4,h5,h6') && window._mdrLinkRefsRetry < 15) {
                                    window._mdrLinkRefsRetry++;
                                    setTimeout(window._mdrLinkRefs, 400);
                                    return;
                                }
                                if (!window._mdrRefPop) {
                                    var pop = document.createElement('div');
                                    pop.className = 'mdr-ref-popover';
                                    document.body.appendChild(pop);
                                    window._mdrRefPop = pop;
                                    document.addEventListener('click', function(e) {
                                        if (!e.target.closest('.mdr-ref-link') && !e.target.closest('.mdr-ref-popover'))
                                            pop.style.display = 'none';
                                    });
                                }

                                // Parse the References section from the fulltext itself
                                var refMap = {};
                                var block = document.querySelector('.mdr-reflink-target');
                                if (!block) return;

                                // Find the References heading
                                var refHeading = null;
                                block.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(function(h) {
                                    if (/^\\s*(References|Bibliography|Works Cited|REFERENCES)\\s*$/i.test(h.textContent))
                                        refHeading = h;
                                });

                                if (refHeading) {
                                    // Walk siblings after the heading to collect reference entries
                                    var el = refHeading.nextElementSibling;
                                    var counter = 1;
                                    while (el) {
                                        if (/^H[1-6]$/i.test(el.tagName)) break;
                                        // MDPI style: <ol start="N"><li>text</li></ol> (possibly nested in <ul><li>)
                                        el.querySelectorAll('ol').forEach(function(ol) {
                                            var n = ol.hasAttribute('start') ? parseInt(ol.getAttribute('start')) : counter;
                                            var li = ol.querySelector('li');
                                            if (li) {
                                                var txt = li.textContent.trim();
                                                if (txt.length > 10) { refMap[n] = txt; counter = n + 1; }
                                            }
                                        });
                                        // Plain <li> items (normal numbered list)
                                        if (!el.querySelector('ol')) {
                                            var lis = el.tagName === 'OL' ? el.querySelectorAll(':scope > li') : el.querySelectorAll('li');
                                            lis.forEach(function(li) {
                                                var txt = li.textContent.trim();
                                                if (txt.length > 10 && !refMap[counter]) { refMap[counter] = txt; counter++; }
                                            });
                                        }
                                        // Plain <p> paragraphs with numbered refs
                                        if (el.tagName === 'P' && el.textContent.trim().length > 10) {
                                            var lm = el.textContent.trim().match(/^\\[?(\\d{1,3})\\.?\\]?[.\\s)]+(.+)/);
                                            if (lm) refMap[parseInt(lm[1])] = lm[2].trim();
                                        }
                                        el = el.nextElementSibling;
                                    }
                                }

                                // Fallback: scan plain text lines after "References"
                                if (Object.keys(refMap).length < 3) {
                                    var lines = block.innerText.split('\\n');
                                    var inRef = false, counter = 1;
                                    for (var i = 0; i < lines.length; i++) {
                                        var line = lines[i].trim();
                                        if (/^(References|Bibliography|REFERENCES)\\s*$/i.test(line)) { inRef = true; continue; }
                                        if (!inRef) continue;
                                        if (line.length < 15) continue;
                                        var lm = line.match(/^\\[?(\\d{1,3})\\.?\\]?[.\\s)]+(.+)/);
                                        if (lm) { refMap[parseInt(lm[1])] = lm[2].trim(); }
                                        else if (!refMap[counter]) { refMap[counter] = line; counter++; }
                                    }
                                }

                                window._mdrRefMap = refMap;
                                var hasRefs = Object.keys(refMap).length > 0;

                                // Link [#] citations in the body (exclude the References section itself)
                                if (block.dataset.refsLinked) return;
                                block.dataset.refsLinked = '1';
                                var els = block.querySelectorAll('p, li, td, h1, h2, h3, h4, h5, h6, em, strong, span');
                                if (!els.length) els = [block];

                                function _wrapRef(n) {
                                    var ref = parseInt(n);
                                    return '<span class="mdr-ref-link" data-ref="' + ref + '">[' + ref + ']</span>';
                                }
                                function _wrapOne(p) {
                                    p = p.trim();
                                    if (/^\\d+$/.test(p)) return '<span class="mdr-ref-link" data-ref="' + parseInt(p) + '">' + p + '</span>';
                                    return p;
                                }
                                els.forEach(function(el) {
                                    if (/\\[\\d+/.test(el.innerHTML) && !el.querySelector('.mdr-ref-link')) {
                                        el.innerHTML = el.innerHTML.replace(/\\[(\\d[\\d,\\s\\-\\u2013]*)\\]/g, function(m, inner) {
                                            if (/^\\d+$/.test(inner.trim())) return _wrapRef(inner.trim());
                                            if (/[,]/.test(inner)) {
                                                return '[' + inner.split(/\\s*,\\s*/).map(_wrapOne).join(',') + ']';
                                            }
                                            var rm = inner.match(/^(\\d+)\\s*[\\-\\u2013]\\s*(\\d+)$/);
                                            if (rm) {
                                                var lo = parseInt(rm[1]), hi = parseInt(rm[2]), out = [];
                                                for (var i = lo; i <= hi && i - lo < 30; i++) out.push('<span class="mdr-ref-link" data-ref="'+i+'">'+i+'</span>');
                                                return '[' + out.join(',') + ']';
                                            }
                                            return m;
                                        });
                                    }
                                });

                                // Click handler: show reference text from the paper's bibliography
                                document.querySelectorAll('.mdr-ref-link:not([data-bound])').forEach(function(lnk) {
                                    lnk.dataset.bound = '1';
                                    lnk.addEventListener('click', function(e) {
                                        e.stopPropagation();
                                        var ref = parseInt(lnk.dataset.ref);
                                        var pop = window._mdrRefPop;
                                        var txt = window._mdrRefMap[ref];
                                        var h = '<div class="mdr-ref-popover-title">[' + ref + ']</div>';
                                        if (txt) {
                                            // Try to parse author/title from the reference text
                                            h += '<div style="margin-top:0.2rem;line-height:1.5">' + txt.substring(0, 400) + (txt.length > 400 ? '...' : '') + '</div>';
                                        } else {
                                            h += '<div style="color:var(--text-muted);font-style:italic">Reference not found in bibliography</div>';
                                        }
                                        pop.innerHTML = h;
                                        pop.style.display = 'block';
                                        // Position: prefer right side of viewport to avoid action pane overlap
                                        var r = lnk.getBoundingClientRect();
                                        var popW = Math.min(370, window.innerWidth - 32);
                                        var panel = lnk.closest('.mdr-reading-panel');
                                        var l, t = r.bottom + 6;
                                        if (panel) {
                                            var pr = panel.getBoundingClientRect();
                                            l = pr.right - popW - 8;
                                            if (l < pr.left) l = pr.left + 8;
                                        } else {
                                            l = window.innerWidth - popW - 16;
                                        }
                                        if (t + pop.offsetHeight > window.innerHeight - 16) t = r.top - pop.offsetHeight - 6;
                                        if (t < 8) t = 8;
                                        pop.style.left = l + 'px';
                                        pop.style.top = t + 'px';
                                    });
                                });
                            };
                            window._mdrLinkRefs();
                        """
                        ui.timer(0.4, lambda: ui.run_javascript(_link_refs_js), once=True)
                    else:
                        with ui.card().classes("mdr-card w-full p-4"):
                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                async def _fetch_ft(r: int = ref_n) -> None:
                                    ft_btn.set_text(t("fetching_fulltext"))
                                    ft_btn.disable()
                                    result = await reading_service.fetch_fulltext_on_demand(
                                        run.id, r, service.get_api_keys()
                                    )
                                    if result:
                                        ui.notify(t("fulltext_fetched"), type="positive")
                                        main_area.refresh()
                                    else:
                                        ui.notify(t("fulltext_failed"), type="warning")
                                        ft_btn.set_text(t("fetch_fulltext"))
                                        ft_btn.enable()

                                ft_btn = ui.button(t("fetch_fulltext"), on_click=_fetch_ft).props(
                                    "outline size=sm"
                                ).style("color: var(--text-muted); border-color: var(--border-dim); font-size: 0.75rem")
                                if study.doi:
                                    ui.link("Open DOI", f"https://doi.org/{study.doi}", new_tab=True).style(
                                        "font-size: 0.75rem; color: var(--accent)"
                                    )

                            ui.html('<div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 0.4rem">Or drop a PDF:</div>')

                            async def _handle_pdf_upload(e: Any, r: int = ref_n) -> None:
                                content = e.content.read()
                                if not content or content[:5] != b"%PDF-":
                                    ui.notify("Not a valid PDF", type="warning")
                                    return
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                                    tmp.write(content)
                                    pdf_path = tmp.name
                                text = ""
                                try:
                                    import opendataloader_pdf
                                    import glob as _glob
                                    output_dir = tempfile.mkdtemp()
                                    await _asyncio.to_thread(
                                        opendataloader_pdf.convert, input_path=[pdf_path],
                                        output_dir=output_dir, format="markdown",
                                    )
                                    md_files = _glob.glob(f"{output_dir}/**/*.md", recursive=True)
                                    if md_files:
                                        with open(md_files[0]) as mf:
                                            text = mf.read()
                                except ImportError:
                                    text = "[opendataloader-pdf not installed]"
                                except Exception as exc:
                                    text = f"[PDF parse error: {exc}]"
                                finally:
                                    import os as _os
                                    try:
                                        _os.unlink(pdf_path)
                                    except OSError:
                                        pass
                                if text:
                                    reading_service.store_fulltext(run.id, r, text)
                                    ui.notify(t("fulltext_fetched"), type="positive")
                                    main_area.refresh()
                                else:
                                    ui.notify(t("fulltext_failed"), type="warning")

                            ui.upload(on_upload=_handle_pdf_upload, auto_upload=True, max_file_size=50_000_000).props(
                                'accept=".pdf" flat bordered'
                            ).classes("w-full").style(
                                "max-width: 18rem; border-color: var(--border-dim) !important; "
                                "background: var(--bg-surface) !important; border-style: dashed !important"
                            )

                # ---- RIGHT: Tools + Chat + Highlights ----
                with ui.column().classes("mdr-reading-panel mdr-chat-panel-wrapper gap-3").style("flex: 1 1 50%; min-width: 0"):
                    _build_chat_panel(scope)

            # Recalculate panel height now that reading panels exist in the DOM
            ui.timer(0.3, lambda: ui.run_javascript(_RECALC_PANEL_JS), once=True)
            ui.timer(0.8, lambda: ui.run_javascript(_RECALC_PANEL_JS), once=True)

        def _build_chat_panel(scope: str) -> None:
            """Chat + tool buttons + highlights — used for all scopes."""

            # Scope label
            if scope.startswith("study:"):
                scope_label = f'{t("discussing_study")} #{scope.split(":")[1]}'
            elif scope.startswith("cross:"):
                scope_label = f'{t("comparing_studies")} #{scope.split(":")[1]}'
            else:
                scope_label = t("all_studies")

            # Tool buttons (whole-paper tools; selection-scoped tools are in the floating toolbar)
            _TOOL_PROMPTS = {
                "tool_structure": "Summarize the structure of this paper: what are the main sections, what claim does each section make, and how do they connect?",
                "tool_findings": "What are the key findings and results? List each with its statistical evidence (p-values, confidence intervals, effect sizes).",
            }

            with ui.card().classes("mdr-card w-full p-3"):
                with ui.row().classes("items-center gap-1 flex-wrap"):
                    for key, prompt in _TOOL_PROMPTS.items():
                        def _make_tool_click(p: str = prompt) -> Any:
                            async def _click() -> None:
                                reading_state["_pending_msg"] = p
                                main_area.refresh()
                            return _click

                        ui.button(t(key), on_click=_make_tool_click()).props(
                            "outline size=xs"
                        ).classes("mdr-tool-btn").style("color: var(--text-secondary); border-color: var(--border-dim)")

                    # Export notes
                    async def _export_notes() -> None:
                        notes_md = reading_service.export_notes(rs.id, scope, run.id)
                        if not notes_md.strip():
                            ui.notify(t("no_notes"), type="info")
                            return
                        await ui.run_javascript(
                            f"navigator.clipboard.writeText({json.dumps(notes_md)})"
                        )
                        ui.notify(t("notes_copied"), type="positive")

                    ui.button(t("export_notes"), on_click=_export_notes).props(
                        "outline size=xs"
                    ).classes("mdr-tool-btn").style("color: var(--accent); border-color: var(--accent)")

            # Chat card (flex layout: scroll area fills space, input pinned at bottom)
            with ui.card().classes("mdr-card mdr-chat-card w-full p-3"):
                ui.html(f'<span class="mdr-scope-indicator">{scope_label}</span>')

                history = reading_service.get_chat_history(rs.id, scope)

                chat_column = ui.column().classes("mdr-chat-scroll w-full gap-2 mt-2")
                chat_column.props('id="mdr-chat-messages"')
                with chat_column:
                    if not history:
                        ui.html(
                            '<div style="color: var(--text-muted); font-size: 0.78rem; font-style: italic">'
                            'Starting discussion...</div>'
                        )
                    for msg in history:
                        cls = "mdr-chat-msg-assistant" if msg.role == "assistant" else "mdr-chat-msg-user"
                        with ui.column().classes(f"mdr-chat-msg {cls}"):
                            ui.markdown(msg.content)

                streaming_md = ui.markdown("").classes("mdr-chat-msg mdr-chat-msg-assistant")
                streaming_md.set_visibility(False)

                # Auto-scroll to bottom on render
                _scroll_js = """
                    var el = document.getElementById('mdr-chat-messages');
                    if (el) el.scrollTop = el.scrollHeight;
                """
                ui.timer(0.2, lambda: ui.run_javascript(_scroll_js), once=True)

                with ui.row().classes("w-full items-end gap-2 pt-2").style("flex-shrink: 0"):
                    msg_input = ui.input(placeholder="...").classes("flex-1").props("dense outlined")
                    msg_input.style("font-family: 'IBM Plex Sans', sans-serif; font-size: 0.8rem; color: var(--text-primary)")

                    async def _stream_response(chunks: Any) -> None:
                        """Stream chunks into the chat, handling scroll and cleanup."""
                        reading_state["streaming"] = True
                        streaming_md.set_visibility(True)
                        msg_input.disable()
                        send_btn.disable()
                        accumulated = ""
                        counter = 0
                        try:
                            async for chunk in chunks:
                                accumulated += chunk
                                streaming_md.set_content(accumulated)
                                counter += 1
                                if counter % 10 == 0:
                                    ui.run_javascript(_scroll_js)
                        except Exception as exc:
                            accumulated = f"*Error: {exc}*"
                            streaming_md.set_content(accumulated)
                        ui.run_javascript(_scroll_js)
                        reading_state["streaming"] = False
                        msg_input.enable()
                        send_btn.enable()
                        streaming_md.set_visibility(False)
                        main_area.refresh()

                    async def _send_message(override_text: str | None = None) -> None:
                        user_text = override_text or (msg_input.value.strip() if msg_input.value else "")
                        current_scope = reading_state["scope"]
                        if not user_text or not current_scope or reading_state["streaming"]:
                            return

                        msg_input.value = ""

                        with chat_column:
                            with ui.column().classes("mdr-chat-msg mdr-chat-msg-user"):
                                ui.markdown(user_text)

                        await _stream_response(reading_service.ask(
                            session_id=rs.id, scope=current_scope,
                            user_message=user_text, run_id=run.id,
                            provider=run.provider, model=run.model,
                            api_keys=service.get_api_keys(),
                        ))

                    send_btn = ui.button(t("send"), on_click=_send_message).props("size=sm").style(
                        "background: var(--accent) !important; color: var(--bg-deep) !important; font-weight: 600"
                    )
                    msg_input.on("keydown.enter", _send_message)

                # Handle pending message from tool buttons or text selection
                pending = reading_state.pop("_pending_msg", None)
                if pending and not reading_state["streaming"]:
                    async def _run_pending(text: str = pending) -> None:
                        await _send_message(override_text=text)
                    ui.timer(0.15, lambda: _asyncio.ensure_future(_run_pending()), once=True)

                # Auto-open discussion if no history
                elif not history and not reading_state["streaming"]:
                    async def _auto_open() -> None:
                        if reading_state["streaming"]:
                            return
                        current_scope = reading_state["scope"]
                        if not current_scope:
                            return
                        await _stream_response(reading_service.open_discussion(
                            session_id=rs.id, scope=current_scope,
                            run_id=run.id, provider=run.provider,
                            model=run.model, api_keys=service.get_api_keys(),
                        ))

                    ui.timer(0.15, lambda: _asyncio.ensure_future(_auto_open()), once=True)

            # Saved highlights
            highlights = reading_service.get_highlights(rs.id, scope)
            if highlights:
                with ui.card().classes("mdr-card w-full p-3"):
                    ui.html(f'<div class="mdr-section-title" style="font-size: 0.8rem">{t("saved_highlights")}</div>')
                    for hl in highlights:
                        with ui.row().classes("mdr-highlight-item w-full items-center justify-between mt-1"):
                            with ui.column().classes("flex-1 min-w-0"):
                                ui.html(f'<div class="mdr-highlight-text">"{hl.text[:150]}"</div>')

                            async def _ask_hl(text: str = hl.text) -> None:
                                reading_state["_pending_msg"] = f'Explain this: "{text[:300]}"'
                                main_area.refresh()

                            async def _del_hl(hid: str = hl.id) -> None:
                                reading_service.delete_highlight(hid)
                                main_area.refresh()

                            ui.button(icon="chat", on_click=_ask_hl).props("flat size=xs").style("color: var(--accent)")
                            ui.button(icon="delete", on_click=_del_hl).props("flat size=xs").style("color: var(--error)")

        main_area()


def build_ui(service: ResearchService, reading_service: ReadingService | None = None) -> None:
    ui.add_css(_CUSTOM_CSS)

    def index() -> None:
        selected: dict[str, str | None] = {"run_id": None, "active_tab": "trace"}
        page_state: dict[str, int] = {"page": 0, "per_page": 8}

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
        drawer: Any = None
        with ui.header().classes("mdr-header items-center justify-between"):
            with ui.row().classes("items-center gap-3"):
                ui.button(
                    icon="menu", on_click=lambda: drawer.toggle(),
                ).props("flat dense round").style("color: var(--text-secondary)")
                ui.html(f'<span class="mdr-title">{t("app_title")}</span>')
            with ui.row().classes("items-center gap-1"):
                _font_size = {"val": 100}

                def _adjust_font(delta: int) -> None:
                    _font_size["val"] = max(70, min(150, _font_size["val"] + delta))
                    ui.run_javascript(
                        f"document.documentElement.style.fontSize='{_font_size['val']}%'"
                    )

                _font_btn_style = "color: var(--text-muted); font-size: 0.75rem; min-width: 1.8rem; font-family: 'IBM Plex Sans', sans-serif"
                ui.button("A-", on_click=lambda: _adjust_font(-10)).props("flat dense size=sm").style(_font_btn_style)
                ui.button("A+", on_click=lambda: _adjust_font(10)).props("flat dense size=sm").style(_font_btn_style)
                ui.html(f'<span class="mdr-subtitle">{t("app_subtitle")}</span>')

        # -- Sidebar drawer --
        with ui.left_drawer(value=True).props("bordered overlay width=420").style(
            "background: var(--bg-deep) !important; border-right: 1px solid var(--border-dim) !important; "
            "padding: 0.75rem"
        ) as drawer:  # noqa: F811

                # New Research form (collapsible)
                with ui.expansion(t("new_research"), icon="add_circle_outline").classes("mdr-card w-full").props("dense default-opened"):
                    ui.html(f'<div class="mdr-section-desc" style="margin-bottom:0.75rem">{t("new_research_desc")}</div>')

                    ui.html(
                        f'<div class="mdr-section-desc" style="margin-bottom:0.35rem">{t("query_type")}</div>'
                    )
                    ui.toggle(
                        {"free": t("free_form"), "pico": "PICO", "pcc": "PCC"},
                        value=form_state["query_type"],
                        on_change=lambda _: structured_input.refresh(),
                    ).props(
                        "spread no-caps unelevated toggle-color=transparent color=transparent"
                    ).bind_value(form_state, "query_type").classes("mdr-query-toggle w-full")

                    with ui.row().classes("w-full gap-3"):

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

                        def _field(label_key: str, placeholder: str, state_key: str) -> None:
                            ui.input(label=t(label_key), placeholder=placeholder).props(
                                "outlined dark dense"
                            ).classes("w-full").bind_value(form_state, state_key)

                        if qt == "pico":
                            _field("population", "e.g. Adults with HFpEF", "pico_p")
                            _field("intervention", "e.g. SGLT2 inhibitors", "pico_i")
                            _field("comparison", "e.g. Placebo or standard care", "pico_c")
                            _field("outcome", "e.g. Hospitalisation, mortality", "pico_o")
                        elif qt == "pcc":
                            _field("population", "e.g. Elderly patients with diabetes", "pcc_p")
                            _field("concept", "e.g. Self-management strategies", "pcc_concept")
                            _field("context", "e.g. Primary care settings", "pcc_context")
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
                        if total > 0:
                            total_pages = max(1, (total + pp - 1) // pp)
                            current_page = page_state["page"] + 1
                            with ui.row().classes("w-full justify-center items-center gap-1 mt-2"):
                                ui.button(icon="chevron_left", on_click=prev_page).props(
                                    "flat dense round" + (" disable" if page_state["page"] == 0 else "")
                                ).style("color: var(--text-secondary)")
                                ui.html(
                                    f'<span style="font-family: IBM Plex Mono, monospace; font-size: 0.7rem; '
                                    f'color: var(--text-muted)">{current_page}/{total_pages}</span>'
                                )
                                ui.button(icon="chevron_right", on_click=next_page).props(
                                    "flat dense round" + (" disable" if offset + pp >= total else "")
                                ).style("color: var(--text-secondary)")

                                def _set_per_page(e: Any) -> None:
                                    page_state["per_page"] = int(e.value)
                                    page_state["page"] = 0
                                    run_list.refresh()

                                ui.select(
                                    {5: "5", 8: "8", 15: "15", 30: "30"},
                                    value=pp, on_change=_set_per_page,
                                ).props("dense borderless").style(
                                    "width: 3.5rem; font-size: 0.65rem; color: var(--text-muted)"
                                )

                run_list()

        # ===== MAIN CONTENT (full width) =====
        with ui.column().classes("w-full gap-3").style(
            "padding: 0.75rem 1.25rem; height: calc(100vh - 3.5rem); overflow-y: auto"
        ).on("click", lambda: drawer.hide()):

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
                                    f'{t("select_run_desc")}</div>'
                                )
                        return

                    # Pre-compute these before the header (needed for auto-collapse logic)
                    artifacts = service.list_artifacts(run.id)
                    _has_studies = (
                        reading_service is not None
                        and run.status == "completed"
                        and any(a.artifact_type == "ranked_results" for a in artifacts)
                    )
                    _active_tab_name: str = selected.get("active_tab") or "trace"  # type: ignore[assignment]

                    # Compact run status bar
                    with ui.row().classes("mdr-status-bar w-full items-center gap-3").props(
                        'id="mdr-run-header"'
                    ).style(f"--mdr-progress: {run.progress}%"):
                        ui.html(f'<span class="mdr-status-query">{run.query}</span>')
                        ui.html(f'<span class="mdr-badge {_status_badge_class(run.status)}" style="flex-shrink:0">{run.status}</span>')
                        ui.html(f'<span class="mdr-badge mdr-badge-neutral" style="flex-shrink:0">{run.runtime_name}</span>')
                        ui.html(
                            f'<span style="font-family: IBM Plex Mono, monospace; font-size: 0.68rem; '
                            f'color: var(--text-muted); flex-shrink: 0">{run.progress}%</span>'
                        )
                        ui.button(t("interrupt"), on_click=interrupt_selected).props(
                            "outline size=xs dense"
                        ).style("color: var(--text-secondary); border-color: var(--border-dim); font-size: 0.68rem")
                        ui.button(t("cancel"), on_click=cancel_selected).props(
                            "outline size=xs dense"
                        ).style("color: var(--error); border-color: var(--error); font-size: 0.68rem")

                    # JS: dynamically calc reading panel height based on available space
                    ui.timer(0.2, lambda: ui.run_javascript("""
                        window._mdrRecalcPanelHeight = function(retries) {
                            retries = (typeof retries === 'number') ? retries : 0;
                            var panel = document.querySelector('.mdr-reading-panel');
                            if (panel) {
                                var r = panel.getBoundingClientRect();
                                var targetBottom = window.innerHeight - 16;
                                var delta = r.bottom - targetBottom;
                                if (Math.abs(delta) > 2) {
                                    var h = Math.max(r.height - delta, 200);
                                    document.documentElement.style.setProperty('--reading-panel-h', h + 'px');
                                    if (retries < 5) {
                                        requestAnimationFrame(function() {
                                            requestAnimationFrame(function() {
                                                window._mdrRecalcPanelHeight(retries + 1);
                                            });
                                        });
                                    }
                                }
                                return;
                            }
                            var header = document.getElementById('mdr-run-header');
                            if (!header) return;
                            var rect = header.getBoundingClientRect();
                            var tabsEl = header.nextElementSibling;
                            var tabsH = tabsEl ? tabsEl.offsetHeight : 40;
                            var usedTop = rect.bottom + tabsH + 16;
                            var available = window.innerHeight - usedTop - 16;
                            var h = Math.max(available, 200);
                            document.documentElement.style.setProperty('--reading-panel-h', h + 'px');
                        };
                        window._mdrRecalcPanelHeight();
                        window.addEventListener('resize', window._mdrRecalcPanelHeight);
                    """), once=True)

                    # Tabs
                    events = service.list_events(run.id)

                    def on_tab_change(e: Any) -> None:
                        selected["active_tab"] = e.value

                    with ui.tabs(
                        value=_active_tab_name,  # type: ignore[arg-type]
                        on_change=on_tab_change,
                    ).classes("mdr-tabs w-full") as tabs:
                        trace_tab = ui.tab("trace")
                        artifacts_tab = ui.tab("artifacts")
                        report_tab = ui.tab("report")
                        if _has_studies:
                            studies_tab = ui.tab(t("studies"))
                        diag_tab = ui.tab("diagnostics")

                    _tab_map: dict[str, Any] = {"trace": trace_tab, "artifacts": artifacts_tab, "report": report_tab, "diagnostics": diag_tab}
                    if _has_studies:
                        _tab_map[t("studies")] = studies_tab  # type: ignore[possibly-undefined]
                    _active = _tab_map.get(_active_tab_name, trace_tab)

                    with ui.tab_panels(tabs, value=_active).classes("w-full").style("background: transparent !important"):

                        with ui.tab_panel(trace_tab).style(_TAB_PANEL_STYLE):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html(f'<div class="mdr-section-title">{t("execution_trace")}</div>')
                                ui.html(f'<div class="mdr-section-desc">{len(events)} events</div>')
                                if not events:
                                    ui.label(t("waiting_events")).style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                                with ui.column().classes("w-full gap-0 mt-3").style(
                                    "max-height: calc(100vh - 16rem); overflow-y: auto"
                                ):
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

                        with ui.tab_panel(artifacts_tab).style(_TAB_PANEL_STYLE):
                            with ui.card().classes("mdr-card w-full p-4"):
                                ui.html('<div class="mdr-section-title">Artifacts</div>')
                                ui.html(f'<div class="mdr-section-desc">{len(artifacts)} artifacts</div>')
                                if not artifacts:
                                    ui.label(t("no_artifacts")).style("color: var(--text-muted); font-size: 0.82rem; margin-top: 0.5rem")
                                with ui.column().classes("w-full gap-1 mt-2").style(
                                    "max-height: calc(100vh - 16rem); overflow-y: auto"
                                ):
                                    for artifact in artifacts:
                                        with ui.expansion(
                                            f"{artifact.artifact_type}: {artifact.name}",
                                            icon="description",
                                        ).classes("w-full"):
                                            if artifact.content_text:
                                                ui.markdown(f"```\n{artifact.content_text}\n```")
                                            if artifact.content_json:
                                                ui.code(artifact.content_json, language="json").classes("w-full")

                        with ui.tab_panel(report_tab).style(_TAB_PANEL_STYLE):
                            with ui.card().classes("mdr-card w-full p-5"):
                                ui.html('<div class="mdr-section-title" style="margin-bottom:1rem">Report</div>')
                                ui.markdown(
                                    run.result_markdown or t("report_not_started")
                                ).classes("mdr-report w-full")

                        with ui.tab_panel(diag_tab).style(_TAB_PANEL_STYLE):
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
                                    if run_diag.get("tool_calls") is not None:
                                        ui.label(f"Tool calls: {run_diag['tool_calls']}").style(
                                            "font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem"
                                        )
                                    if run_diag.get("report_source"):
                                        ui.label(f"Report source: {run_diag['report_source']}").style(
                                            "font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem"
                                        )
                                    if run_diag.get("search_sources_executed"):
                                        sources = ", ".join(run_diag["search_sources_executed"])
                                        ui.label(f"Search sources: {sources}").style(
                                            "font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem"
                                        )
                                    if run_diag.get("error_message"):
                                        ui.label(run_diag["error_message"]).style(
                                            "font-size: 0.75rem; color: var(--error); margin-top: 0.25rem"
                                        )
                                    if run_diag.get("fallback_reason"):
                                        ui.label(run_diag["fallback_reason"]).style(
                                            "font-size: 0.75rem; color: var(--warn); margin-top: 0.25rem"
                                        )
                                    ui.code(
                                        json.dumps(run_diag, indent=2), language="json"
                                    ).classes("w-full mt-3")

                        # -- Studies / Reading tab --
                        if _has_studies:
                            _build_studies_panel(
                                studies_tab,  # type: ignore[possibly-undefined]
                                run=run,
                                reading_service=reading_service,  # type: ignore[arg-type]
                                service=service,
                                t=t,
                            )

                detail_panel()

        def _on_service_change(run_id: str, change_type: str) -> None:
            """Push-based UI update triggered by service state changes."""
            run_list.refresh()
            if selected["run_id"] == run_id:
                detail_panel.refresh()

        service.add_ui_listener(_on_service_change)

    index()
