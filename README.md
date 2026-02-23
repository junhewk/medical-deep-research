# Medical Deep Research

Evidence-Based Medical Research Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

Medical Deep Research is an **evidence-based medicine (EBM)** research assistant for healthcare professionals and medical researchers. It uses autonomous AI agents to search medical literature, classify evidence levels, and synthesize findings into comprehensive reports. It also supports **broader healthcare research** topics such as ethics, policy, informatics, and social care with adapted thematic analysis pipelines.

### What's New in v2.7.0 (Healthcare Research Domain)

- **Research Domain Classification**: Free-form queries are automatically classified as "clinical" or "healthcare_research" using word-boundary-aware keyword heuristics (minimum 2-keyword threshold to prevent single-keyword flips)
- **Healthcare Research Pipeline**: Broader topics (ethics, policy, informatics, social care, etc.) get keyword-based search strategies, thematic report structure, and cross-disciplinary database coverage
- **Cross-Disciplinary Semantic Scholar**: Semantic Scholar searches omit the Medicine field filter for healthcare research queries; clinical agent calls auto-inject `fieldsOfStudy: "Medicine"`
- **Expanded Context Analysis**: New `policy_analysis` and `ethics_review` query intents in both LLM prompt and heuristic fallback
- **Cochrane/Scopus Skipped for Non-Clinical**: Healthcare research queries skip Cochrane and Scopus in mandatory search (OpenAlex + Semantic Scholar provide broad coverage)
- **Shared Keyword Constants**: Policy and ethics keywords centralized in `research-keywords.ts` to prevent drift between domain classifier and context analyzer

### What's New in v2.6 (Free Database Fallbacks)

- **OpenAlex Integration**: Free search with citation counts and broad coverage (no API key needed)
- **Semantic Scholar Integration**: Free Medicine-filtered search (no API key needed)
- **Smart Fallbacks**: Automatically uses OpenAlex + Semantic Scholar when Scopus unavailable
- **Deduplication**: Cross-database deduplication by PMID/DOI with source priority
- **Dynamic Thresholds**: Article minimums adjust based on available database coverage

### What's New in v2.3 (Dynamic MeSH & Context Analysis)

- **Dynamic MeSH Resolver**: Queries NLM's MeSH RDF API instead of hardcoded mappings
- **LLM-based Context Analysis**: AI understands query intent (clinical, economic, safety, etc.)
- **Korean Translation**: Full report translation with medical terminology preservation
- **Citation Fix**: Prevents out-of-range citation numbers in synthesized reports
- **Multi-provider Support**: OpenAI, Anthropic, Google LLMs with unified factory

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
| **Query Framework** | **PICO** (clinical) + **PCC** (scoping reviews) + **Free-form** (auto-classified) |
| **Terminology** | **Dynamic MeSH** via NLM API + SQLite caching |
| **Context Analysis** | **LLM-based** intent detection (clinical, economic, safety, policy, ethics) |
| **Evidence** | **Evidence level tagging** (Level I-V) |
| **Search** | PubMed, Scopus (BYOK), Cochrane, OpenAlex, Semantic Scholar |
| **Translation** | Korean report translation with terminology preservation |
| **Stack** | Next.js 14 + Drizzle ORM + SQLite |
| **API Keys** | BYOK - OpenAI, Anthropic, Google, Scopus, NCBI |

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
medical-deep-research/web/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── api/
│   │   │   ├── research/       # Research CRUD + agent trigger
│   │   │   └── settings/       # API key + language management
│   │   ├── research/           # Research pages
│   │   │   ├── new/            # PICO/PCC query builder
│   │   │   └── [id]/           # Research progress/results
│   │   └── settings/
│   │       └── api-keys/       # BYOK configuration
│   ├── components/
│   │   ├── research/           # Progress, planning, tool log
│   │   └── ui/                 # shadcn/ui components
│   ├── db/
│   │   ├── schema.ts           # Drizzle schema (+ MeSH cache)
│   │   └── index.ts            # SQLite connection
│   ├── i18n/                   # Internationalization
│   ├── lib/
│   │   ├── agent/
│   │   │   ├── deep-agent.ts           # LangGraph StateGraph agent
│   │   │   ├── research-keywords.ts    # Shared keyword constants
│   │   │   └── tools/
│   │   │       ├── pubmed.ts               # NCBI E-utilities
│   │   │       ├── scopus.ts               # Elsevier API
│   │   │       ├── cochrane.ts             # Cochrane + PubMed fallback
│   │   │       ├── mesh-mapping.ts         # Static MeSH mapping
│   │   │       ├── mesh-resolver.ts        # Dynamic MeSH via NLM API (new)
│   │   │       ├── query-context-analyzer.ts # LLM context analysis (new)
│   │   │       ├── llm-factory.ts          # Shared LLM creation (new)
│   │   │       ├── pico-query.ts           # PICO → PubMed query
│   │   │       ├── pcc-query.ts            # PCC → PubMed query
│   │   │       ├── population-validator.ts # Population matching
│   │   │       ├── claim-verifier.ts       # Citation verification
│   │   │       ├── report-translator.ts    # Korean translation
│   │   │       ├── openalex.ts            # OpenAlex search (free)
│   │   │       └── semantic-scholar.ts    # Semantic Scholar search (free)
│   │   ├── research.ts         # React Query hooks
│   │   ├── state-export.ts     # Markdown file export
│   │   └── utils.ts
│   └── types/
└── data/
    ├── medical-deep-research.db  # SQLite database (+ MeSH cache)
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
reports: { id, researchId, title, content, originalContent, language, wordCount, referenceCount, ... }
searchResults: { id, researchId, title, source, evidenceLevel, pmid, doi, compositeScore, ... }

// Agent state
agentStates: { id, researchId, phase, planningSteps, toolExecutions, ... }

// Configuration
apiKeys: { id, service, apiKey, ... }
settings: { key, value, category, ... }
llmConfig: { id, provider, model, isDefault, ... }

// MeSH cache (for dynamic NLM API lookups)
meshCache: { id, label, alternateLabels, treeNumbers, broaderTerms, narrowerTerms, scopeNote, fetchedAt }
meshLookupIndex: { id, searchTerm, meshId, matchType }
```

## Medical Research Tools

| Tool | Description |
|------|-------------|
| `pico_query_builder` | Builds PubMed query from PICO with context analysis |
| `pcc_query_builder` | Builds query from PCC with context analysis |
| `mesh_resolver` | Dynamic MeSH lookup via NLM RDF API (new) |
| `query_context_analyzer` | LLM-based query intent detection (new) |
| `mesh_mapping` | Static MeSH term lookup (legacy) |
| `evidence_level` | Classifies study evidence (I-V) |
| `pubmed_search` | Searches PubMed via NCBI E-utilities |
| `scopus_search` | Searches Scopus (requires API key) |
| `cochrane_search` | Searches Cochrane Library |
| `openalex_search` | Searches OpenAlex (free, no API key) |
| `semantic_scholar_search` | Searches Semantic Scholar (free, cross-disciplinary or Medicine-filtered) |
| `population_validator` | AI-based population matching |
| `claim_verifier` | Post-synthesis verification against PubMed |
| `report_translator` | Korean translation with terminology preservation (new) |

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
│  │ Mapping  │  │  Search  │  │  Search  │  │  Search  │    │
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
| OpenAI | Yes* | GPT-4o, GPT-4o-mini for research |
| Anthropic | Yes* | Claude 3.5 Sonnet, Claude 3.5 Haiku alternative |
| Google | Yes* | Gemini 1.5 Pro, Gemini 1.5 Flash alternative |
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

- [x] OpenAlex / Semantic Scholar integration
- [ ] GRADE evidence assessment
- [ ] Citation export (RIS, BibTeX)
- [ ] Additional language translations
- [ ] Streaming progress updates
- [ ] Mandatory claim verification node

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
