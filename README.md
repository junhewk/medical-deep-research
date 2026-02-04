# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

Medical Deep Research is an **evidence-based medicine (EBM)** research assistant for healthcare professionals and medical researchers. It uses autonomous AI agents to search medical literature, classify evidence levels, and synthesize findings into comprehensive reports.

### What's New in v2.0 (TypeScript Migration)

- **Full TypeScript Stack**: Unified Next.js application (no Python backend)
- **Single-User Mode**: No authentication required - just install and use
- **BYOK Model**: Bring Your Own Keys for LLM and search APIs
- **LangGraph Agent**: Autonomous research with StateGraph-based planning
- **PICO-First UI**: PICO framework as default, with PCC for scoping reviews

### Key Features

| Feature | Description |
|---------|-------------|
| **Architecture** | **LangGraph StateGraph** with autonomous planning |
| **Query Framework** | **PICO** (clinical) + **PCC** (scoping reviews) |
| **Terminology** | **MeSH term mapping** (60+ medical terms) |
| **Evidence** | **Evidence level tagging** (Level I-V) |
| **Search** | PubMed, Scopus (BYOK), Cochrane |
| **Stack** | Next.js 14 + Drizzle ORM + SQLite |
| **API Keys** | BYOK - OpenAI, Anthropic, Scopus, NCBI |

## Quick Start

### Prerequisites

- Node.js 18+
- npm or pnpm

### One-Click Start

**macOS / Linux:**
```bash
./start-web.sh
```

**Windows:**
```cmd
start-web.bat
```

The startup script will automatically:
- Install dependencies
- Set up the SQLite database
- Start the development server

### Manual Installation

```bash
cd medical-deep-research/web

# Install dependencies
npm install

# Generate and run database migrations
npm run db:generate
npm run db:migrate

# Start development server
npm run dev
```

Open http://localhost:3000

### Configure API Keys

1. Go to **Settings > API Keys**
2. Add your API keys:
   - **OpenAI** or **Anthropic** (required for LLM)
   - **NCBI** (optional - higher PubMed rate limits)
   - **Scopus** (optional - for Scopus searches)

### Start Your First Research

1. Click **New Research**
2. Choose framework:
   - **PICO** - For clinical intervention questions
   - **PCC** - For scoping reviews / qualitative research
   - **Free-form** - Natural language query
3. Fill in the components and click **Start Research**

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
medical-deep-research/web/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── api/
│   │   │   ├── research/       # Research CRUD + agent trigger
│   │   │   └── settings/       # API key management
│   │   ├── research/           # Research pages
│   │   │   ├── new/            # PICO/PCC query builder
│   │   │   └── [id]/           # Research progress/results
│   │   └── settings/
│   │       └── api-keys/       # BYOK configuration
│   ├── components/
│   │   ├── research/           # Progress, planning, tool log
│   │   └── ui/                 # shadcn/ui components
│   ├── db/
│   │   ├── schema.ts           # Drizzle schema
│   │   └── index.ts            # SQLite connection
│   ├── lib/
│   │   ├── agent/
│   │   │   ├── deep-agent.ts   # LangGraph StateGraph agent
│   │   │   └── tools/
│   │   │       ├── pubmed.ts       # NCBI E-utilities
│   │   │       ├── scopus.ts       # Elsevier API
│   │   │       ├── cochrane.ts     # Cochrane + PubMed fallback
│   │   │       ├── mesh-mapping.ts # Term mapping + evidence levels
│   │   │       ├── pico-query.ts   # PICO → PubMed query
│   │   │       └── pcc-query.ts    # PCC → PubMed query
│   │   ├── research.ts         # React Query hooks
│   │   ├── state-export.ts     # Markdown file export
│   │   └── utils.ts
│   └── types/
└── data/
    ├── medical-deep-research.db  # SQLite database
    └── research/                  # Markdown exports per research
```

## Database Schema

```typescript
// Research sessions
research: { id, query, queryType, mode, status, progress, ... }

// Query components
picoQueries: { id, researchId, population, intervention, comparison, outcome, ... }
pccQueries: { id, researchId, population, concept, context, ... }

// Results
reports: { id, researchId, title, content, wordCount, referenceCount, ... }
searchResults: { id, researchId, title, source, evidenceLevel, pmid, doi, ... }

// Agent state
agentStates: { id, researchId, phase, planningSteps, toolExecutions, ... }

// Configuration
apiKeys: { id, service, apiKey, ... }
settings: { key, value, category, ... }
```

## Medical Research Tools

| Tool | Description |
|------|-------------|
| `pico_query_builder` | Builds PubMed query from PICO components |
| `pcc_query_builder` | Builds query from PCC components |
| `mesh_mapping` | Maps terms to MeSH vocabulary |
| `evidence_level` | Classifies study evidence (I-V) |
| `pubmed_search` | Searches PubMed via NCBI E-utilities |
| `scopus_search` | Searches Scopus (requires API key) |
| `cochrane_search` | Searches Cochrane Library |

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
│  │  Planning → Tool Execution → Synthesis → Report       │  │
│  └─────────────────────────────────────────────────────┘    │
│                          ↓                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  MeSH    │  │  PubMed  │  │  Scopus  │  │ Cochrane │    │
│  │ Mapping  │  │  Search  │  │  Search  │  │  Search  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                          ↓                                   │
├─────────────────────────────────────────────────────────────┤
│                 EVIDENCE PROCESSING                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  • Evidence Level Classification (I-V)              │    │
│  │  • MeSH Term Extraction                             │    │
│  │  • Abstract Analysis                                │    │
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
| OpenAI | Yes* | GPT-4o, GPT-4 for research |
| Anthropic | Yes* | Claude 3.5 Sonnet alternative |
| NCBI | No | Higher PubMed rate limits (free) |
| Scopus | No | Scopus/Elsevier database access |
| Cochrane | No | Direct Cochrane API (falls back to PubMed) |

*One LLM provider required

## Development

```bash
# Development
npm run dev

# Build
npm run build

# Database commands
npm run db:generate  # Generate migrations
npm run db:migrate   # Run migrations
npm run db:push      # Push schema changes

# Lint
npm run lint
```

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Additional MeSH term mappings
- [ ] OpenAlex / Semantic Scholar integration
- [ ] GRADE evidence assessment
- [ ] Citation export (RIS, BibTeX)
- [ ] Multilingual support
- [ ] Streaming progress updates

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

- Original concept: [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) by LearningCircuit
- PubMed/MeSH: [NCBI/NLM](https://www.ncbi.nlm.nih.gov/)
- UI components: [shadcn/ui](https://ui.shadcn.com/)
- Agent framework: [LangGraph](https://langchain-ai.github.io/langgraph/)

## Citation

```bibtex
@software{medical_deep_research,
  title = {Medical Deep Research: Evidence-Based Medical Research Assistant},
  author = {Kim, Junhewk},
  year = {2026},
  url = {https://github.com/junhewk/medical-deep-research}
}
```
