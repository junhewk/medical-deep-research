# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest Release](https://img.shields.io/github/v/release/junhewk/medical-deep-research)](https://github.com/junhewk/medical-deep-research/releases/latest)

## Overview

Medical Deep Research is an **evidence-based medicine (EBM)** research assistant for healthcare professionals and medical researchers. It uses autonomous AI agents to search medical literature, classify evidence levels, and synthesize findings into comprehensive reports. It also supports **broader healthcare research** topics such as ethics, policy, informatics, and social care with adapted thematic analysis pipelines.

Available as a **web application** and a **desktop application** (Windows, macOS) powered by [Tauri](https://v2.tauri.app/).

### Key Features

| Feature | Description |
|---------|-------------|
| **Architecture** | **LangGraph StateGraph** with autonomous planning |
| **Query Framework** | **PICO** (clinical) + **PCC** (scoping reviews) + **Free-form** (auto-classified) |
| **Terminology** | **Dynamic MeSH** via NLM API + SQLite caching |
| **Context Analysis** | **LLM-based** intent detection (clinical, economic, safety, policy, ethics) |
| **Evidence** | **Evidence level tagging** (Level I-V) |
| **Search** | PubMed, Scopus (BYOK), Cochrane, OpenAlex, Semantic Scholar |
| **Translation** | Korean report translation with terminology preservation |
| **Stack** | Next.js + Drizzle ORM + SQLite |
| **Desktop** | Tauri 2 (Windows NSIS installer, macOS DMG) |
| **API Keys** | BYOK - OpenAI, Anthropic, Google, Scopus, NCBI |

## Installation

### Desktop App (Recommended)

Download the latest installer from [GitHub Releases](https://github.com/junhewk/medical-deep-research/releases/latest):

| Platform | File | Notes |
|----------|------|-------|
| **Windows** (x64) | [`Medical.Deep.Research_2.0.0_x64-setup.exe`](https://github.com/junhewk/medical-deep-research/releases/latest) | NSIS installer |
| **macOS** (Apple Silicon) | [`Medical.Deep.Research_2.0.0_aarch64.dmg`](https://github.com/junhewk/medical-deep-research/releases/latest) | M1/M2/M3/M4 |
| **macOS** (Intel) | [`Medical.Deep.Research_2.0.0_x64.dmg`](https://github.com/junhewk/medical-deep-research/releases/latest) | Intel Macs |

The desktop app bundles everything — no Node.js or other dependencies required.

### Web App

#### Prerequisites

- Node.js 18+
- npm

#### One-Click Start

**macOS / Linux:**
```bash
./start-web.sh
```

**Windows:**
```cmd
start-web.bat
```

#### Manual Installation

```bash
cd web

# Install dependencies
npm install

# Initialize database
npm run db:init

# Start development server
npm run dev
```

Open http://localhost:3000

### Build Desktop from Source

**macOS / Linux:**
```bash
./scripts/build-desktop.sh
```

**Windows:**
```cmd
scripts\build-desktop.bat
```

Requires Rust toolchain and Node.js. The build script automatically downloads the Bun sidecar binary, builds the Next.js standalone server, and produces the Tauri installer.

## Getting Started

### Configure API Keys

1. Go to **Settings > API Keys**
2. Add your API keys:
   - **OpenAI**, **Anthropic**, or **Google** (one LLM provider required)
   - **NCBI** (optional - higher PubMed rate limits)
   - **Scopus** (optional - for Scopus searches)

### Start Your First Research

1. Click **New Research**
2. Choose framework:
   - **PICO** - For clinical intervention questions
   - **PCC** - For scoping reviews / qualitative research
   - **Free-form** - Natural language query
3. Fill in the components and click **Start Research**

> **Note:** Free-form queries are automatically classified as **clinical** or **healthcare research**. Clinical queries use PICO/PCC frameworks with evidence-level reporting. Healthcare research queries (ethics, policy, informatics, social care, etc.) use keyword-based search strategies with thematic report structure.

## Query Frameworks

### PICO (Clinical Questions)

Best for questions about interventions, therapies, or treatments.

| Component | Description | Example |
|-----------|-------------|---------|
| **P** - Population | Who are the patients? | Adults with type 2 diabetes |
| **I** - Intervention | What treatment/exposure? | SGLT2 inhibitors |
| **C** - Comparison | What is the alternative? | Metformin monotherapy |
| **O** - Outcome | What results matter? | Cardiovascular events |

### PCC (Scoping Reviews)

Best for exploratory questions and qualitative research.

| Component | Description | Example |
|-----------|-------------|---------|
| **P** - Population | Who is being studied? | Healthcare workers |
| **C** - Concept | What phenomenon? | Burnout experiences |
| **C** - Context | In what setting? | During COVID-19 pandemic |

## Architecture

```
medical-deep-research/
├── web/                          # Next.js web application
│   └── src/
│       ├── app/                  # App Router (pages + API routes)
│       ├── components/           # React components (shadcn/ui)
│       ├── db/                   # Drizzle ORM schema + SQLite
│       ├── i18n/                 # Internationalization
│       ├── lib/
│       │   ├── agent/            # LangGraph research agent
│       │   │   ├── deep-agent.ts
│       │   │   ├── research-keywords.ts
│       │   │   └── tools/        # PubMed, Scopus, Cochrane,
│       │   │                     # OpenAlex, Semantic Scholar,
│       │   │                     # MeSH, evidence, translation
│       │   ├── research.ts       # React Query hooks
│       │   └── state-export.ts   # Markdown export
│       └── types/
├── src-tauri/                    # Tauri desktop shell
│   ├── src/                      # Rust backend (server management)
│   ├── binaries/                 # Bun sidecar (per-platform)
│   ├── resources/                # Bundled Next.js standalone
│   ├── icons/                    # App icons
│   └── tauri.conf.json
└── scripts/
    ├── build-desktop.sh          # macOS/Linux build script
    └── build-desktop.bat         # Windows build script
```

### Desktop Architecture

The desktop app uses Tauri 2 to wrap the Next.js web application:

1. **Tauri shell** spawns a bundled **Bun** runtime as a sidecar process
2. Bun runs the **Next.js standalone server** on a random local port
3. A session auth token secures communication between the webview and server
4. SQLite database is stored in the platform's app data directory

## Medical Research Tools

| Tool | Description |
|------|-------------|
| `pico_query_builder` | Builds PubMed query from PICO with context analysis |
| `pcc_query_builder` | Builds query from PCC with context analysis |
| `mesh_resolver` | Dynamic MeSH lookup via NLM RDF API |
| `query_context_analyzer` | LLM-based query intent detection |
| `evidence_level` | Classifies study evidence (I-V) |
| `pubmed_search` | Searches PubMed via NCBI E-utilities |
| `scopus_search` | Searches Scopus (requires API key) |
| `cochrane_search` | Searches Cochrane Library |
| `openalex_search` | Searches OpenAlex (free, no API key) |
| `semantic_scholar_search` | Searches Semantic Scholar (free) |
| `population_validator` | AI-based population matching |
| `claim_verifier` | Post-synthesis citation verification |
| `report_translator` | Korean translation with terminology preservation |

## Evidence Level Classification

| Level | Study Type |
|-------|------------|
| Level I | Systematic reviews, Meta-analyses |
| Level II | Randomized Controlled Trials (RCTs) |
| Level III | Cohort studies, Case-control studies |
| Level IV | Case series, Cross-sectional studies |
| Level V | Case reports, Expert opinion |

## Research Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INPUT                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  PICO: Population + Intervention + Comparison + Outcome │
│  │  PCC:  Population + Concept + Context                   │
│  │  Free: Natural language query                           │
│  └─────────────────────────────────────────────────────┘    │
│                          ↓                                   │
├─────────────────────────────────────────────────────────────┤
│                  LANGGRAPH AGENT                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Domain Classification → Planning → Tools → Synthesis  │  │
│  └─────────────────────────────────────────────────────┘    │
│                          ↓                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  MeSH    │  │  PubMed  │  │  Scopus  │  │ Cochrane │    │
│  │ Resolver │  │  Search  │  │  Search  │  │  Search  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│  ┌──────────┐  ┌───────────────┐                            │
│  │ OpenAlex │  │   Semantic    │                            │
│  │  Search  │  │   Scholar     │                            │
│  └──────────┘  └───────────────┘                            │
│                          ↓                                   │
├─────────────────────────────────────────────────────────────┤
│                 EVIDENCE PROCESSING                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  • Evidence Level Classification (I-V)              │    │
│  │  • Cross-database Deduplication (PMID/DOI)          │    │
│  │  • Population Validation                            │    │
│  │  • Claim Verification                               │    │
│  └─────────────────────────────────────────────────────┘    │
│                          ↓                                   │
│              ┌───────────────────────┐                       │
│              │   Markdown Report     │                       │
│              │   with Citations      │                       │
│              └───────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

## API Key Configuration (BYOK)

All API keys are stored locally in SQLite. Configure in Settings > API Keys:

| Service | Required | Description |
|---------|----------|-------------|
| OpenAI | Yes* | GPT-4o for research |
| Anthropic | Yes* | Claude for research |
| Google | Yes* | Gemini for research |
| NCBI | No | Higher PubMed rate limits (free) |
| Scopus | No | Scopus/Elsevier database access |
| Cochrane | No | Direct Cochrane API (falls back to PubMed) |

*One LLM provider required

## Development

```bash
cd web

# Development
npm run dev

# Build
npm run build

# Database commands
npm run db:init   # Initialize database
npm run db:push   # Push schema changes

# Lint
npm run lint
```

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

- Inspired by [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) by LearningCircuit
- PubMed/MeSH: [NCBI/NLM](https://www.ncbi.nlm.nih.gov/)
- UI components: [shadcn/ui](https://ui.shadcn.com/)
- Agent framework: [LangGraph](https://langchain-ai.github.io/langgraph/)
- Desktop framework: [Tauri](https://v2.tauri.app/)

## Citation

```bibtex
@software{medical_deep_research,
  title = {Medical Deep Research: Evidence-Based Medical Research Assistant},
  author = {Kim, Junhewk},
  year = {2026},
  url = {https://github.com/junhewk/medical-deep-research}
}
```
