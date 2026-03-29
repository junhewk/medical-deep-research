# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest Release](https://img.shields.io/github/v/release/junhewk/medical-deep-research)](https://github.com/junhewk/medical-deep-research/releases/latest)

## Overview

Medical Deep Research is an **evidence-based medicine (EBM)** research assistant for healthcare professionals and medical researchers. It uses **autonomous AI agents** to search medical literature across multiple databases, classify evidence levels, retrieve and parse open-access full-text PDFs, and synthesize findings into comprehensive reports.

The Python rewrite (`feature/python-nicegui-rewrite`) replaces the original TypeScript/LangGraph stack with a **multi-provider agentic architecture** where the LLM autonomously drives the entire research workflow by calling MCP tools.

### Key Features

| Feature | Description |
|---------|-------------|
| **Architecture** | Agentic loop — LLM calls 15 tools autonomously via shared-state bridge |
| **Providers** | Anthropic (Claude), OpenAI, Google (Gemini), **Local LLMs** (Ollama, LM Studio, llama-server) |
| **Query Framework** | PICO (clinical) + PCC (scoping reviews) + Free-form (auto-classified) |
| **Search** | PubMed (EBM-boosted), Cochrane, OpenAlex, Semantic Scholar, Scopus (BYOK) |
| **Ranking** | Agent-driven: LLM reviews abstracts and ranks by relevance, evidence quality, recency |
| **Full-text** | Unpaywall + PubMed Central OA lookup, PDF download and parsing via opendataloader-pdf |
| **Evidence** | Level I-V classification, PMID verification against PubMed |
| **Stack** | Python, NiceGUI, SQLModel, claude-agent-sdk / openai-agents / google-adk / LangChain |
| **UI** | Dark "Clinical Observatory" theme with real-time event trace |

## Quick Start

```bash
# Install with all provider extras
uv sync --all-extras

# Or pick your provider
uv sync --extra anthropic   # Claude Agent SDK
uv sync --extra openai      # OpenAI Agents SDK
uv sync --extra google      # Google ADK
uv sync --extra langchain   # Local LLMs (Ollama, LM Studio, llama-server)
uv sync --extra pdf         # Full-text PDF parsing

# Run the app
uv run medical-deep-research
```

Open http://127.0.0.1:8080

### Environment Variables

```bash
# LLM provider keys (at least one required for cloud providers)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Local LLM endpoint (for Ollama, LM Studio, llama-server, vLLM)
MDR_LOCAL_BASE_URL=http://127.0.0.1:8090/v1

# Optional search API keys
MDR_NCBI_API_KEY=...        # Higher PubMed rate limits
MDR_SCOPUS_API_KEY=...      # Scopus/Elsevier access
MDR_SEMANTIC_SCHOLAR_API_KEY=...
```

## How It Works

The agent autonomously executes an 8-step research workflow:

```
1. plan_search        → Build search strategy (keywords, databases, queries)
2. search_*           → Search 3-5 databases (PubMed, Cochrane, OpenAlex, etc.)
3. get_studies        → Deduplicate and pre-score all collected studies
4. finalize_ranking   → Agent reviews abstracts and ranks by EBM quality
5. fetch_fulltext     → Unpaywall + PMC lookup for open-access PDFs
6. parse_pdf          → Download and parse full-text PDFs to markdown
7. verify_studies     → Validate PMIDs against PubMed
8. synthesize_report  → Generate final evidence report
```

The LLM drives the workflow — it decides what to search, reviews evidence quality, ranks studies using medical knowledge, and writes the synthesis. Tools use a **shared-state bridge** so the agent never passes large JSON blobs as arguments.

### Provider Support

| Provider | SDK | Model (tested) | Agentic | Full-text |
|----------|-----|----------------|---------|-----------|
| Anthropic | `claude-agent-sdk` | claude-haiku-4-5 | Yes | Yes |
| OpenAI | `openai-agents` | gpt-5-mini | Yes | Yes |
| Google | `google-adk` | gemini-2.5-flash | Yes | Yes |
| Local | `langchain` + `langgraph` | Qwen3.5-122B (llama-server) | Yes | Yes |

All providers fall back to a deterministic pipeline if SDK/credentials are unavailable.

### Search Hardening

Searches are optimized for the small result window (~10-50 articles per database):

- **PubMed**: EBM publication type boost (systematic reviews, meta-analyses, RCTs, guidelines), relevance sort, 2019+ date filter
- **OpenAlex**: 2015+ filter, relevance sort
- **Semantic Scholar**: Medicine field filter, 2015+ year, retry on 429
- **Cochrane**: Filtered to Cochrane Database of Systematic Reviews
- **Scopus**: Relevance sort, 2015-2026 date range

### Full-text Pipeline

After ranking, the agent retrieves open-access full-text for Level I & II studies:

1. **Unpaywall** — parallel lookup (10 concurrent) for all ranked Level I/II studies with DOIs
2. **PubMed Central** — batch PMID→PMCID conversion, then OA service for tgz package URLs
3. **PDF parsing** — download via direct URL (not unpywall handle, which corrupts binary data), parse to markdown via opendataloader-pdf

## Architecture

```
src/medical_deep_research/
├── main.py                 # NiceGUI app entry point
├── ui.py                   # Dark-theme web UI
├── config.py               # Settings (pydantic-settings)
├── models.py               # SQLModel data models + RunRequest
├── persistence.py          # SQLite database layer
├── service.py              # Run orchestration + event persistence
├── runtime.py              # Provider runtimes (Anthropic, OpenAI, Google, Local)
├── agentic_tools.py        # Shared tool logic + AgenticEventBridge + system prompt
├── tools.py                # Legacy tool helpers
├── research/
│   ├── planning.py         # Query planning, keyword extraction, EBM classification
│   ├── search.py           # PubMed, OpenAlex, Cochrane, Semantic Scholar, Scopus
│   ├── scoring.py          # Evidence level scoring, composite ranking
│   ├── verification.py     # PMID verification via NCBI
│   ├── reporting.py        # Markdown report rendering
│   └── models.py           # Research data models (EvidenceStudy, ScoredStudy, etc.)
└── mcp/
    └── servers.py          # FastMCP servers (literature, evidence, workspace)
```

### Runtime Class Hierarchy

```
ResearchRuntime (ABC)
  └─ DeterministicRuntime          ← pure Python fallback
       └─ NativeSDKRuntime         ← legacy 3-checkpoint base
            ├─ OpenAIRuntime       ← agentic (FunctionTool + Runner)
            ├─ AnthropicRuntime    ← agentic (MCP servers + hooks)
            ├─ GoogleRuntime       ← agentic (ADK Agent + callbacks)
            └─ LangChainLocalRuntime ← agentic (StructuredTool + langgraph)
```

### Shared Infrastructure

All 4 agentic runtimes share:

- **`AgenticEventBridge`** — shared state (search results, ranked studies, verification, PDFs) + async event queue for UI streaming
- **15 tool functions** — `tool_plan_search`, `tool_search`, `tool_get_studies`, `tool_finalize_ranking`, `tool_fetch_fulltext`, `tool_parse_pdf`, etc.
- **`agentic_system_prompt()`** — common workflow instructions
- **`recover_report_from_bridge()`** — partial recovery if agent times out

Each provider wraps the shared tools in its SDK format:
- Anthropic: `claude_agent_sdk.tool` + `create_sdk_mcp_server`
- OpenAI: `agents.FunctionTool`
- Google: plain async callables (ADK inspects signatures)
- LangChain: `@tool` decorator

## MCP Servers

Run standalone MCP servers for external tool access:

```bash
uv run medical-deep-research-mcp literature   # Search tools
uv run medical-deep-research-mcp evidence     # Ranking, verification, reporting
uv run medical-deep-research-mcp workspace    # Run/artifact management
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
# Install dev dependencies
uv sync --all-extras

# Lint
uv run ruff check src/
uv run mypy src/ --ignore-missing-imports

# Test a specific provider
ANTHROPIC_API_KEY=... uv run python -c "
import asyncio
from medical_deep_research.runtime import AnthropicRuntime, RunRequest
# ... see test examples in the codebase
"
```

## License

MIT License - see [LICENSE](LICENSE)

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
