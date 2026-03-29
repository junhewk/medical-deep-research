# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest Release](https://img.shields.io/github/v/release/junhewk/medical-deep-research)](https://github.com/junhewk/medical-deep-research/releases/latest)

<p align="center">
  <img src="public/medical-deep-research.png" alt="Medical Deep Research" width="400">
</p>

## Overview

Medical Deep Research is a **desktop research assistant** for healthcare professionals and medical researchers. It uses **autonomous AI agents** to search medical literature across multiple databases, classify evidence levels, retrieve open-access full-text PDFs, and synthesize findings into comprehensive reports.

Built with Python and NiceGUI, packaged as a native desktop app for macOS and Windows.

### Key Features

| Feature | Description |
|---------|-------------|
| **Architecture** | Agentic loop — LLM calls 16 tools autonomously via shared-state bridge |
| **Providers** | Anthropic (Claude), OpenAI, Google (Gemini), Local LLMs (Ollama) |
| **Query Framework** | PICO (clinical) + PCC (scoping reviews) + Free-form (auto-classified) |
| **Search** | PubMed, Cochrane, OpenAlex, Semantic Scholar, Scopus |
| **Ranking** | Agent-driven: LLM reviews abstracts and ranks by relevance and evidence quality |
| **Full-text** | Unpaywall + PubMed Central OA lookup, PDF parsing |
| **Evidence** | Level I–V classification, PMID verification against PubMed |
| **i18n** | English / Korean UI, LLM-powered report translation |
| **Desktop** | Native window (pywebview), PyInstaller packaging, push-based UI |

## Download

Pre-built desktop apps for macOS and Windows are available on the [Releases](https://github.com/junhewk/medical-deep-research/releases/latest) page.

| Platform | File |
|----------|------|
| macOS | `Medical-Deep-Research-*-macOS.dmg` |
| Windows | `Medical-Deep-Research-*-Windows.zip` |

API keys are configured in the app's **API Keys** panel (stored locally in SQLite).

## Quick Start (from source)

```bash
# Install with all provider extras
uv sync --all-extras

# Or pick your provider
uv sync --extra anthropic   # Claude Agent SDK
uv sync --extra openai      # OpenAI Agents SDK
uv sync --extra google      # Google ADK
uv sync --extra langchain   # Local LLMs (Ollama, LM Studio)
uv sync --extra pdf         # Full-text PDF parsing

# Run the app
uv run medical-deep-research
```

Open http://127.0.0.1:18515

### Build Desktop App

```bash
# macOS
./scripts/build-macos.sh          # builds dist/Medical Deep Research.app
./scripts/build-macos.sh --dmg    # also creates a .dmg installer

# Requires: Python 3.12+, uv
```

### Environment Variables

```bash
# LLM provider keys (or configure in-app)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Local LLM endpoint
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
 2. search_*           → Search 3–5 databases (PubMed, Cochrane, OpenAlex, etc.)
 3. get_studies        → Deduplicate and pre-score all collected studies
 4. finalize_ranking   → Agent reviews abstracts and ranks by EBM quality
 5. fetch_fulltext     → Unpaywall + PMC lookup for open-access PDFs
 6. parse_pdf          → Download and parse full-text PDFs to markdown
 7. verify_studies     → Validate PMIDs against PubMed
 8. synthesize_report  → Collect structured evidence data
 9. submit_report      → Agent writes and submits the final synthesis report
10. [translate]        → If language is Korean, translate via LLM (English preserved as artifact)
```

The LLM drives the workflow — it decides what to search, reviews evidence quality, ranks studies using medical knowledge, and writes the synthesis. Tools use a **shared-state bridge** so the agent never passes large JSON blobs as arguments.

### Domain-Specific Prompts

The system prompt adapts to the query domain:

- **Clinical questions** — PICO framework, evidence level classification (I–V), results organized by evidence level, population validation, landmark trial prioritization
- **Healthcare/academic topics** — keyword-based search, thematic organization, diverse methodologies (qualitative, mixed methods, policy analysis) treated equally

### Provider Support

| Provider | SDK | Default Model | Agentic |
|----------|-----|---------------|---------|
| Anthropic | `claude-agent-sdk` | claude-haiku-4-5 | Yes |
| OpenAI | `openai-agents` | gpt-5-mini | Yes |
| Google | `google-adk` | gemini-2.5-flash | Yes |
| Local | `langchain` + `langgraph` | qwen3.5-27b | Yes |

All providers fall back to a deterministic pipeline if SDK/credentials are unavailable.

### Search Databases

| Database | Access | Notes |
|----------|--------|-------|
| PubMed | Free (NCBI key optional) | EBM publication type boost, relevance sort, 2019+ |
| Cochrane | Free (via PubMed) | Systematic reviews only |
| OpenAlex | Free | Broad academic coverage, 2015+ |
| Semantic Scholar | Free (API key optional) | Medicine field filter, 2015+ |
| Scopus | API key required | Citation counts, broader coverage |

### Full-text Pipeline

After ranking, the agent retrieves open-access full-text for Level I & II studies:

1. **Unpaywall** — parallel lookup for ranked studies with DOIs
2. **PubMed Central** — batch PMID→PMCID conversion, OA service
3. **PDF parsing** — download and parse to markdown via opendataloader-pdf

## Architecture

```
src/medical_deep_research/
├── main.py                 # NiceGUI app entry point
├── ui.py                   # Dark-theme web UI with i18n
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
├── desktop_entry.py        # PyInstaller entry point (pywebview + NiceGUI)
└── build-macos.sh          # macOS build script
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
uv sync --all-extras
uv run ruff check src/
uv run mypy src/ --ignore-missing-imports
```

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgments

- Inspired by [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) by LearningCircuit
- PubMed/MeSH: [NCBI/NLM](https://www.ncbi.nlm.nih.gov/)
- Open access: [Unpaywall](https://unpaywall.org/), [PubMed Central](https://pmc.ncbi.nlm.nih.gov/)
- PDF parsing: [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf)
- Agent SDKs: [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-code/sdk), [OpenAI Agents](https://openai.github.io/openai-agents-python/), [Google ADK](https://google.github.io/adk-docs/), [LangChain](https://python.langchain.com/)
- UI framework: [NiceGUI](https://nicegui.io/)

## Citation

```bibtex
@software{medical_deep_research,
  title = {Medical Deep Research: Evidence-Based Medical Research Assistant},
  author = {Kim, Junhewk},
  year = {2026},
  url = {https://github.com/junhewk/medical-deep-research}
}
```
