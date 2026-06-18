# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest Release](https://img.shields.io/github/v/release/junhewk/medical-deep-research)](https://github.com/junhewk/medical-deep-research/releases/latest)

<p align="center">
  <img src="public/medical-deep-research.png" alt="Medical Deep Research" width="400">
</p>

## Overview

Medical Deep Research is a **desktop research assistant** for healthcare professionals and medical researchers. It uses **autonomous AI agents** to search medical literature across multiple databases, classify evidence levels, retrieve open-access full-text PDFs, and synthesize findings into comprehensive reports.

Built with Python and PySide6 (Qt), packaged as a native desktop app for macOS and Windows.

### Key Features

| Feature | Description |
|---------|-------------|
| **Architecture** | Agentic loop — LLM autonomously calls 25+ tools via shared-state bridge |
| **Providers** | Anthropic (Claude), OpenAI, DeepSeek, Google (Gemini), Local LLMs (Ollama, LM Studio, llama-server) |
| **Query Framework** | PICO (clinical) + PCC (scoping reviews) + Free-form (auto-classified) |
| **Search** | PubMed, PMC, Europe PMC, Crossref, Cochrane, OpenAlex, Semantic Scholar, Scopus, ClinicalTrials.gov, medRxiv/bioRxiv preprints — up to 25 results per source |
| **Ranking** | Deterministic evidence-level pre-ranking → tiered/paged triage → PICO screening → agent ranking, with citation snowballing |
| **Full-text** | Unpaywall + PubMed Central OA lookup, Java-free PDF parsing, user PDF upload checkpoint |
| **Evidence** | Level I–V classification, GRADE certainty per finding, PMID verification against PubMed |
| **Check Studies** | Side-by-side paper reader + AI chat, Vancouver [#] reference linking with bibliography popover |
| **i18n** | English / Korean UI, LLM-powered report translation |
| **Desktop** | Native PySide6 (Qt) window, PyInstaller packaging, push-based UI, splitter-based layout |
| **UI polish** | Bundled Pretendard sans font, PICO/PCC-first research form, report outline/search reader |

## Download

Pre-built desktop apps for macOS and Windows are available on the [Releases](https://github.com/junhewk/medical-deep-research/releases/latest) page.

| Platform | File |
|----------|------|
| macOS | `Medical-Deep-Research-*-macOS.dmg` |
| Windows | `Medical-Deep-Research-*-Windows.zip` |

API keys are configured in the app's **API Keys** panel (stored locally in SQLite).

### Anthropic Runtime

Current builds use a Python-only LangChain/Anthropic agent runtime for Claude. This path does **not** require Git, Git Bash, Claude Code, or `claude-agent-sdk`.

The older Claude SDK route remains available only as an opt-in legacy mode from source:

```bash
MDR_ANTHROPIC_RUNTIME=claude_sdk uv run medical-deep-research
```

Legacy Claude SDK mode may require Git on macOS/Linux and Git for Windows/Git Bash on Windows.

### macOS Gatekeeper

The macOS build is ad-hoc signed but not Apple-notarized. If macOS says the DMG or app is from an unidentified developer, open it with one of these methods:

1. Control-click the DMG or **Medical Deep Research.app**, choose **Open**, then choose **Open** again.
2. Or go to **System Settings → Privacy & Security** and choose **Open Anyway** for Medical Deep Research.

If macOS reports that the app is "damaged", copy **Medical Deep Research.app** to `/Applications`, then run:

```bash
xattr -dr com.apple.quarantine "/Applications/Medical Deep Research.app"
open "/Applications/Medical Deep Research.app"
```

### v2.9.5 — EBM Loop, Wider Search & Tiered Triage

- Searches now return up to **25 results per source** (previously the agent self-limited to ~10), so it casts a wider net before triage.
- `get_studies` returns a deterministically pre-ranked **top tier grouped by evidence level (I→V)** with facet counts; the new `browse_studies` tool pages or filters the full pool by evidence level or source without re-ranking.
- `screen_studies` is now a **whitelist** — only studies the agent explicitly includes survive; the rest are dropped and reported in the Methods section.
- New **EBM stages**: PICO screening and GRADE certainty appraisal run as both agentic tools and structured checkpoints, with a soft certainty quality gate and gap-aware rewind. Up to 20 ranked studies now reach the synthesized report.
- **Citation snowballing** (`get_references`/`get_citations` via Europe PMC + OpenAlex), ClinicalTrials.gov registry search for publication-bias awareness, and Europe PMC full-text-XML-first retrieval.
- **Monotonic progress** — a shared progress tracker keeps the progress bar from jumping backward when the agent revisits a phase.
- Fixed an evidence-level scoring bug that scored every level as the highest, so deterministic pre-ranking now reflects true Level I→V quality.

## Quick Start (from source)

```bash
# Install with the standard desktop/provider extras
uv sync --extra anthropic --extra openai --extra deepseek --extra google --extra langchain --extra pdf

# Or pick your provider
uv sync --extra anthropic   # Claude via LangChain/Anthropic
uv sync --extra claude-sdk   # Optional legacy Claude SDK mode
uv sync --extra openai      # OpenAI Agents SDK
uv sync --extra deepseek    # DeepSeek via OpenAI-compatible Chat API
uv sync --extra google      # Gemini via LangChain/Google GenAI
uv sync --extra langchain   # Local LLMs (Ollama, LM Studio, llama-server)
uv sync --extra pdf         # Full-text PDF parsing

# Run the app (opens a native Qt window — no browser, no local web port)
uv run medical-deep-research
```

### Build Desktop App

```bash
# macOS
./scripts/build-macos.sh          # builds dist/Medical Deep Research.app
./scripts/build-macos.sh --dmg    # also creates a .dmg installer

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1 -Zip

# Requires: Python 3.12+, uv
```

### Environment Variables

```bash
# LLM provider keys (or configure in-app)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
GOOGLE_API_KEY=...

# Local LLM endpoint (Ollama, LM Studio, and llama-server roots are normalized to /v1)
MDR_LOCAL_BASE_URL=http://127.0.0.1:11434/v1

# Optional search API keys
MDR_NCBI_API_KEY=...
MDR_SCOPUS_API_KEY=...
MDR_SEMANTIC_SCHOLAR_API_KEY=...
```

## How It Works

The agent autonomously executes a multi-step research workflow:

```
 1. plan_search        → Build search strategy (keywords, databases, queries)
 2. search_*           → Search 3–5 databases (up to 25 results per source)
 3. get_studies        → Deduplicate and pre-score into evidence-level tiers (I→V)
 4. browse_studies     → Page/filter the scored pool by evidence level or source
 5. screen_studies     → PICO include/exclude (whitelist — only kept studies survive)
 6. finalize_ranking   → Agent orders the included studies, best first
 7. get_references / get_citations → Optional citation snowballing for top studies
 8. fetch_fulltext / parse_pdf → Unpaywall + PMC lookup, parse PDFs to markdown
 9. appraise_evidence  → GRADE certainty (High/Moderate/Low/Very Low) per finding
10. verify_studies     → Validate PMIDs against PubMed
11. synthesize_report  → Collect structured evidence data
12. submit_report      → Agent writes and submits the final synthesis report
13. [translate]        → If language is Korean, translate via LLM (English preserved as artifact)
```

The LLM drives the workflow — it decides what to search, screens and ranks evidence by EBM quality, grades certainty, and writes the synthesis. Tools use a **shared-state bridge** so the agent never passes large JSON blobs as arguments.

### Domain-Specific Prompts

The system prompt adapts to the query domain:

- **Clinical questions** — PICO framework, evidence level classification (I–V), results organized by evidence level, population validation, landmark trial prioritization
- **Healthcare/academic topics** — keyword-based search, thematic organization, diverse methodologies (qualitative, mixed methods, policy analysis) treated equally

### Provider Support

| Provider | SDK | Default Model | Agentic |
|----------|-----|---------------|---------|
| Anthropic | `langchain-anthropic` | claude-haiku-4-5 | Yes |
| OpenAI | `openai-agents` | gpt-5-mini | Yes |
| DeepSeek | `langchain-openai` | deepseek-v4-pro | Yes |
| Google | `langchain-google-genai` | gemini-2.5-flash | Yes |
| Local | `langchain` + `langgraph` | qwen3.5-27b | Yes |

All providers fall back to a deterministic pipeline if SDK/credentials are unavailable. Anthropic also falls back if the SDK route starts but never reaches a search tool.

### Search Databases

| Database | Access | Notes |
|----------|--------|-------|
| PubMed | Free (NCBI key optional) | EBM publication type boost, relevance sort |
| Cochrane | Free (via PubMed) | Systematic reviews only |
| OpenAlex | Free | Broad academic coverage |
| Semantic Scholar | API key required | Medicine field filter; skipped without key |
| Scopus | API key required | Citation counts, broader coverage; STANDARD/COMPLETE view toggle |

The publication-year window is configurable per-app in **New Research** (default: last 5 years).

### Full-text Pipeline

After ranking, the agent retrieves open-access full-text for Level I & II studies:

1. **Unpaywall** — parallel lookup for ranked studies with DOIs
2. **PubMed Central** — batch PMID→PMCID conversion, OA service
3. **PDF parsing** — `pdfminer.six` text extraction, no Java runtime required

## Architecture

```
src/medical_deep_research/
├── main.py                 # PySide6 + qasync app entry point
├── qtui/                   # Native Qt UI package (sidebar, tabs, widgets)
├── assets/fonts/           # Bundled Pretendard font + license for consistent desktop rendering
├── reading_service.py      # Reading session management, fulltext chat, highlights
├── config.py               # Settings (pydantic-settings)
├── models.py               # SQLModel data models + RunRequest
├── persistence.py          # SQLite database layer
├── service.py              # Run orchestration + push-based UI updates
├── runtime.py              # Provider runtimes (Anthropic, OpenAI, Google, Local)
├── agentic_tools.py        # Shared tool logic + system prompts + translation
├── research/
│   ├── planning.py         # Query planning, keyword extraction, domain classification
│   ├── search.py           # PubMed, OpenAlex, Cochrane, Semantic Scholar, Scopus
│   ├── scoring.py          # Evidence level scoring, composite ranking
│   ├── verification.py     # PMID verification via NCBI
│   ├── reporting.py        # Fallback markdown report rendering
│   └── models.py           # Research data models
└── mcp/
    └── servers.py          # FastMCP servers (literature, evidence, workspace)

scripts/
├── desktop_entry.py        # PyInstaller entry point (PySide6)
├── build-macos.sh          # macOS build script
└── eval_anthropic_route.py # Opt-in Anthropic route smoke eval
```

## Evidence Level Classification

| Level | Study Type |
|-------|------------|
| Level I | Systematic reviews, Meta-analyses, Clinical guidelines |
| Level II | Randomized Controlled Trials (RCTs) |
| Level III | Cohort studies, Case-control studies |
| Level IV | Case series, Cross-sectional studies |
| Level V | Case reports, Expert opinion |

## Development

```bash
uv sync --extra anthropic --extra openai --extra deepseek --extra google --extra langchain --extra pdf --extra dev
uv run ruff check src/
uv run python -m unittest discover -s tests -v

# Optional live Anthropic route eval; requires ANTHROPIC_API_KEY
uv run python scripts/eval_anthropic_route.py
```

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgments

- Inspired by [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) by LearningCircuit
- PubMed/MeSH: [NCBI/NLM](https://www.ncbi.nlm.nih.gov/)
- Open access: [Unpaywall](https://unpaywall.org/), [PubMed Central](https://pmc.ncbi.nlm.nih.gov/)
- PDF parsing: [pdfminer.six](https://github.com/pdfminer/pdfminer.six)
- Agent SDKs: [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-code/sdk), [OpenAI Agents](https://openai.github.io/openai-agents-python/), [Google GenAI](https://googleapis.github.io/python-genai/), [LangChain](https://python.langchain.com/)
- UI framework: [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython-6/), [qasync](https://github.com/CabbageDevelopment/qasync)
- UI font: [Pretendard](https://github.com/orioncactus/pretendard), bundled under its included license

## Citation

```bibtex
@software{medical_deep_research,
  title = {Medical Deep Research: Evidence-Based Medical Research Assistant},
  author = {Kim, Junhewk},
  year = {2026},
  url = {https://github.com/junhewk/medical-deep-research}
}
```
