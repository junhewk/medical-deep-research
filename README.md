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
| **Architecture** | Agentic loop — LLM calls literature, evidence, full-text, and workspace tools via shared-state bridge |
| **Providers** | Anthropic (Claude), OpenAI, OpenAI Codex (ChatGPT OAuth), DeepSeek, Google (Gemini), Local LLMs (Ollama, LM Studio, llama-server) |
| **Query Framework** | PICO (clinical) + PCC (scoping reviews) + Free-form (auto-classified) |
| **Search** | PubMed, PMC, Europe PMC, Crossref, Cochrane, OpenAlex, Semantic Scholar, Scopus, citation snowballing — up to 25 literature records per source |
| **Ranking** | Agent-driven: evidence-level pre-ranking, tiered/paged triage, PICO/PCC screening, EBM ranking, and GRADE-style appraisal |
| **Full-text** | Europe PMC XML + Unpaywall + PubMed Central OA lookup, Java-free PDF parsing, user PDF upload checkpoint |
| **Evidence** | Literature-only ranked evidence, Level I–V classification, GRADE certainty notes, PMID verification against PubMed |
| **Auditability** | Source catalog, PRISMA flow summary, deterministic audit report, verified reference rendering |
| **Check Studies** | Side-by-side paper reader + AI chat, Vancouver [#] reference linking with bibliography popover |
| **i18n** | English / Korean UI, LLM-powered report translation for non-Codex providers, target-language Codex generation |
| **Desktop** | Native PySide6 (Qt) window, PyInstaller packaging, push-based UI, splitter-based layout |
| **UI polish** | Bundled Pretendard sans font, PICO/PCC-first research form, report outline/search reader |

## Download

Pre-built desktop apps for macOS and Windows are available on the [Releases](https://github.com/junhewk/medical-deep-research/releases/latest) page.

| Platform | File |
|----------|------|
| macOS | `Medical-Deep-Research-*-macOS.dmg` |
| Windows | `Medical-Deep-Research-*-Windows.zip` |

API keys are configured in the app's **API Keys** panel (stored locally in SQLite). OpenAI Codex uses the **Codex ChatGPT Auth** controls in that same panel and stores OAuth state under the app data directory, not the user's global Codex profile.

### Anthropic Runtime

Current builds use a Python-only LangChain/Anthropic agent runtime for Claude. This path does **not** require Git, Git Bash, Claude Code, or `claude-agent-sdk`.

The older Claude SDK route remains available only as an opt-in legacy mode from source:

```bash
MDR_ANTHROPIC_RUNTIME=claude_sdk uv run medical-deep-research
```

Legacy Claude SDK mode may require Git on macOS/Linux and Git for Windows/Git Bash on Windows.

### v2.9.10 — macOS Release Automation

- Added Developer ID signing and notarization support to the macOS build script, including recursive signing for bundled PyInstaller binaries.
- Updated the desktop build workflow to produce signed macOS DMG artifacts from GitHub Actions.
- Switched the release bundle identifier to the configurable `BUNDLE_ID` build setting.

### v2.9.9 — Literature-Only EBM Audit

- Removed non-literature sources from ranked evidence workflows; ClinicalTrials.gov is no longer exposed as ranked agent evidence and trial registry data is treated only as auxiliary context where used.
- Added source-catalog, PRISMA-flow, and deterministic audit artifacts across deterministic/native/agentic runs so reports can be checked for source coverage, screening counts, citation support, and unsupported numeric claims.
- Added a provider model catalog plus more resilient literature HTTP handling with retries, rate limits, and cache-aware requests; fixed Codex target-language runs so successful Korean reports no longer show a misleading skipped-translation diagnostic.

### v2.9.8 — Windows Codex Bundle Fix

- Fixed Windows desktop builds so the bundled OpenAI Codex SDK/runtime is treated as a required package and validated during packaging, preventing builds that omit `codex.exe`.
- Added an internal bundled-runtime health check used by build validation, Codex provider diagnostics, and ChatGPT auth status.
- Added a Codex auth recovery state in the UI: when the bundled runtime is missing, login controls are disabled and a **Download latest build** button opens the latest release page.

### v2.9.7 — Codex Runtime & PCC Evidence Quality

- Added **OpenAI Codex as a first-class provider** using ChatGPT OAuth, with app-managed auth state, provider-specific diagnostics, and runtime progress reporting.
- Improved Codex evidence synthesis for **PCC/scoping-review questions** with stricter numbered report sections, richer full-text use, broader study triage, and quality gates that prevent short status summaries from being accepted as reports.
- Hardened PubMed/PMC evidence retrieval paths, including NCBI-friendly user-agent/versioning, PMID/PMCID/OA lookup handling, and tests around citation metadata, report scope, Codex schema, and MCP search behavior.

### v2.9.6 — Verified Citations

- The References section is now **rendered deterministically from verified bibliographic metadata** instead of being written freehand by the model, so fabricated authors, journals, volumes, issues, pages, and years are no longer possible (a frequent failure with local LLM runtimes).
- Cited studies are re-fetched from their **authoritative record** — PubMed `esummary` (by PMID) and Crossref (by DOI) — and the canonical values win over search-time metadata, correcting wrong volumes/issues/pages, ISO journal abbreviations, publication years, and even mismatched DOIs.
- The PubMed parser now captures **volume, issue, pages, and ISO journal abbreviation** (`EvidenceStudy` gained the corresponding fields), with a `MedlineDate` fallback for publication year.

### v2.9.5 — Wider Search & Tiered Triage

- Searches now return up to **25 results per source** (the agent previously self-limited to ~10), casting a wider net before triage.
- `get_studies` returns a deterministically pre-ranked **top tier grouped by evidence level (I→V)** with facet counts; the new `browse_studies` tool pages or filters the full pool by evidence level or source without re-ranking or resetting screening.
- `screen_studies` is now a **whitelist** — only studies the agent explicitly includes survive; the rest are dropped and reported as "not selected" in Methods. Up to 30 ranked studies now reach the synthesized report.
- Fixed an evidence-level scoring bug where `"Level I"` matched II–V as a substring (scoring every level as the highest), so deterministic pre-ranking now reflects true Level I→V quality.

### v2.9.4 — Screened Evidence Workflow

- Run progress is now monotonic across repeated phases and rewinds, with pass labels in the trace and 100% reserved for completion.
- The agent workflow now includes explicit `screen_studies` and `appraise_evidence` checkpoints before report writing.
- Citation snowballing can expand ranked studies through Europe PMC references/citations and OpenAlex fallbacks, then merge and re-screen candidates.
- Added ClinicalTrials.gov registry support for registered, ongoing, and completed-but-unpublished trial context.
- Full-text retrieval tries Europe PMC JATS XML before PDF routes and keeps user PDF checkpoints connected to downstream parsing and appraisal.

## Quick Start (from source)

```bash
# Install with the standard desktop/provider extras
uv sync --extra anthropic --extra openai --extra codex --extra deepseek --extra google --extra langchain --extra pdf

# Or pick your provider
uv sync --extra anthropic   # Claude via LangChain/Anthropic
uv sync --extra claude-sdk   # Optional legacy Claude SDK mode
uv sync --extra openai      # OpenAI Agents SDK
uv sync --extra codex       # OpenAI Codex SDK with ChatGPT OAuth
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

# Codex subscription auth is configured in-app with ChatGPT OAuth.
# Tokens are stored under MDR data_dir/codex-home/auth.json.

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
 2. search_*           → Search literature databases (up to 25 records per source)
 3. get_studies        → Deduplicate and pre-score into evidence-level tiers (I→V)
 4. browse_studies     → Page/filter the scored pool by evidence level or source
 5. screen_studies     → PICO include/exclude — whitelist, only included studies survive
 6. finalize_ranking   → Agent orders the included studies by relevance and EBM quality
 7. [snowball]         → Optionally fetch references/citations and re-screen candidates
 8. fetch_fulltext / parse_pdf → Europe PMC XML + Unpaywall + PMC lookup, parse/upload PDFs
 9. appraise_evidence  → Record GRADE certainty and rationale per major finding
10. verify_studies     → Validate PMIDs against PubMed
11. synthesize_report  → Collect structured evidence data
12. submit_report      → Agent writes and submits the final synthesis report
13. audit/prisma       → Save PRISMA flow and deterministic audit artifacts
14. [translate]        → Non-Codex providers can translate after generation; Codex writes in the target language
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
| OpenAI Codex | `openai-codex` | gpt-5.4-mini | Yes |
| DeepSeek | `langchain-openai` | deepseek-v4-pro | Yes |
| Google | `langchain-google-genai` | gemini-2.5-flash | Yes |
| Local | `langchain` + `langgraph` | qwen3.5-27b | Yes |

All providers fall back to a deterministic pipeline if SDK/credentials are unavailable. Codex uses ChatGPT OAuth subscription auth through the embedded Codex SDK/runtime; no user-installed `codex` CLI is required. Anthropic also falls back if the SDK route starts but never reaches a search tool.

### Search Databases

| Database | Access | Notes |
|----------|--------|-------|
| PubMed | Free (NCBI key optional) | EBM publication type boost, relevance sort |
| PMC | Free | PubMed Central open-access article discovery |
| Europe PMC | Free | Broader biomedical coverage, full-text metadata, citation links |
| Crossref | Free | DOI metadata and publisher coverage |
| Cochrane | Free (via PubMed) | Systematic reviews only |
| OpenAlex | Free | Broad academic coverage and citation fallback |
| Semantic Scholar | API key required | Medicine field filter; skipped without key |
| Scopus | API key required | Citation counts, broader coverage; STANDARD/COMPLETE view toggle |
| Snowballing | Free | Europe PMC references/citations with OpenAlex DOI fallback |

ClinicalTrials.gov is intentionally not ranked as EBM literature evidence. Registry information may be used only as auxiliary context for publication-bias or ongoing-study signals.

The publication-year window is configurable per-app in **New Research** (default: last 5 years).

### Full-text Pipeline

After ranking, the agent retrieves open-access full text for ranked studies:

1. **Europe PMC XML** — JATS full text for open-access PMC articles when available
2. **Unpaywall** — parallel lookup for ranked studies with DOIs
3. **PubMed Central** — batch PMID→PMCID conversion, OA service, and OA archives
4. **User PDF checkpoint** — prompts for missing publisher PDFs and records uploaded ranks
5. **PDF parsing** — `pdfminer.six` text extraction, no Java runtime required

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
├── progress.py             # Monotonic progress and phase pass tracking
├── service.py              # Run orchestration + push-based UI updates
├── runtime.py              # Provider runtimes (Anthropic, OpenAI, Codex, Google, Local)
├── agentic_tools.py        # Shared tool logic + system prompts + translation
├── model_catalog.py        # Provider model catalog discovery and static fallbacks
├── research/
│   ├── audit.py            # Deterministic report/evidence audit artifacts
│   ├── connectors.py       # Source catalog and rankable literature-source policy
│   ├── fulltext.py         # Europe PMC JATS XML full-text retrieval
│   ├── http.py             # Retried/rate-limited/cache-aware HTTP helper
│   ├── planning.py         # Query planning, keyword extraction, domain classification
│   ├── prisma.py           # PRISMA flow summary artifacts
│   ├── search.py           # PubMed, PMC, Europe PMC, Crossref, OpenAlex, Semantic Scholar, Scopus
│   ├── scoring.py          # Evidence level scoring, composite ranking
│   ├── snowball.py         # Europe PMC/OpenAlex citation-graph traversal
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
uv sync --extra anthropic --extra openai --extra codex --extra deepseek --extra google --extra langchain --extra pdf --extra dev
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
- Agent SDKs: [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-code/sdk), [OpenAI Agents](https://openai.github.io/openai-agents-python/), [OpenAI Codex](https://github.com/openai/codex/tree/main/sdk/python), [Google GenAI](https://googleapis.github.io/python-genai/), [LangChain](https://python.langchain.com/)
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
