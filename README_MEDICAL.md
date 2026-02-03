# Medical Deep Research

Evidence-Based Medical Research Assistant powered by Local Deep Research

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

Medical Deep Research is a specialized fork of [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) optimized for **evidence-based medicine (EBM)** research. It provides medical researchers with:

- **PICO Query Builder**: Structured clinical question search
- **MeSH Term Integration**: Automatic term mapping for precise searches
- **Evidence Level Tagging**: Automatic classification (Level I-V)
- **Medical-Focused Prompts**: EBM-optimized system prompts
- **PubMed Priority**: Medical literature-first search strategy

## Features

### 🔬 PICO Framework Support

Build structured clinical queries using the PICO format:
- **P**opulation/Patient: Who are the patients?
- **I**ntervention: What treatment/exposure?
- **C**omparison: What is the alternative?
- **O**utcome: What results matter?

Example:
```python
from local_deep_research.advanced_search_system.questions.medical_question import MedicalQuestionGenerator

generator = MedicalQuestionGenerator(model)

# Build PubMed query from PICO components
query = generator.build_pubmed_query(
    population="Type 2 Diabetes",
    intervention="Metformin",
    comparison="Sulfonylurea",
    outcome="Cardiovascular outcomes",
    study_types=["RCT", "Meta-Analysis"]
)
# Output: ("Diabetes Mellitus, Type 2"[Mesh] OR Type 2 Diabetes[Title/Abstract]) AND ...
```

### 📚 MeSH Term Mapping

Automatic mapping of common medical terms to MeSH vocabulary:

| Common Term | MeSH Term |
|-------------|-----------|
| high blood pressure | Hypertension |
| heart attack | Myocardial Infarction |
| diabetes | Diabetes Mellitus |
| cancer | Neoplasms |
| gum disease | Periodontal Diseases |
| ... | ... |

### 📊 Evidence Level Classification

Automatic tagging of studies based on evidence hierarchy:

| Level | Study Type |
|-------|------------|
| Level I | Systematic reviews, Meta-analyses |
| Level II | Randomized Controlled Trials (RCTs) |
| Level III | Cohort studies, Prospective studies |
| Level IV | Case-control studies, Cross-sectional |
| Level V | Case reports, Expert opinion |

### 🔒 Privacy-First Design

- **Fully Local Execution**: Sensitive patient data never leaves your machine
- **AES-256 Encryption**: Signal-level security for stored data
- **No Cloud Dependencies**: Works offline with local LLMs

## Installation

### Option 1: Easy Install (Recommended for Beginners)

The easiest way to install Medical Deep Research is using the one-click installer:

**macOS/Linux:**
```bash
# Download and run installer
curl -O https://raw.githubusercontent.com/junhewk/medical-deep-research/main/install.py
python3 install.py

# Start the application
./start.sh
```

**Windows (PowerShell):**
```powershell
# Download and run installer
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/junhewk/medical-deep-research/main/install.py" -OutFile install.py
python install.py

# Start the application (double-click start.bat or run:)
.\start.bat
```

Access the web interface at: **http://localhost:5000**

### Option 2: Docker

```bash
curl -O https://raw.githubusercontent.com/junhewk/medical-deep-research/main/docker-compose.yml
docker compose up -d
```

Access at: http://localhost:5000

### Option 3: Manual pip Install

```bash
# Clone the repository
git clone https://github.com/junhewk/medical-deep-research.git
cd medical-deep-research

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install
pip install -e .

# Run
ldr-web
```

## Quick Start

### 1. Configure AI Provider (New!)

In the web UI, configure your AI provider and API keys:

1. Open http://localhost:5000 and create an account
2. Go to **AI Settings** in the sidebar (robot icon)
3. Add your API key for OpenAI, Claude, or Gemini
4. Click "Test" to verify your connection
5. Select your preferred model in the "Model Selection" tab

**Supported Providers:**
- **OpenAI**: GPT-4o, GPT-4, o1 (requires API key)
- **Claude**: Claude 3.5 Sonnet, Claude 3 Opus (requires API key)
- **Gemini**: Gemini Pro, Gemini Ultra (requires API key)
- **Ollama**: Run models locally, no API key needed

### 2. Configure Search Engine

In the web UI (http://localhost:5000), set PubMed Medical as your primary search engine:

1. Go to Settings → Search Engines
2. Select "PubMed (Medical Research)"
3. Optionally add your NCBI API key for higher rate limits

### 3. PICO-Based Search

Enter your clinical question in PICO format:

```
Population: Type 2 diabetes patients with periodontal disease
Intervention: Integrated oral health management
Outcome: HbA1c levels
```

### 4. Evidence-Focused Research

The system will:
1. Map terms to MeSH vocabulary
2. Search PubMed, Semantic Scholar, and Cochrane
3. Tag results by evidence level
4. Prioritize systematic reviews and RCTs

### 5. Export Your Results

After completing research, export your results in multiple formats:

- **Markdown** (.md) - Perfect for Obsidian and other note-taking apps
- **PDF** - Professional reports for sharing
- **LaTeX** (.tex) - For academic papers
- **Quarto** (.qmd + .bib) - For reproducible research documents
- **RIS** - Import citations into reference managers (Zotero, Mendeley, etc.)

## Configuration

### Environment Variables

```bash
# LLM Configuration (choose one)
OLLAMA_BASE_URL=http://localhost:11434  # For local Ollama
OPENAI_API_KEY=your-key                  # For OpenAI
ANTHROPIC_API_KEY=your-key               # For Claude

# Search Configuration
NCBI_API_KEY=your-ncbi-key              # Optional: Higher PubMed rate limits
DEFAULT_SEARCH_ENGINE=pubmed_medical     # Use medical-optimized PubMed
```

### Recommended LLM Models

For medical research, we recommend:

| Provider | Model | Notes |
|----------|-------|-------|
| Ollama (Local) | `llama3.1:8b` | Good balance of speed/quality |
| Ollama (Local) | `gemma2:9b` | Strong medical knowledge |
| OpenAI | `gpt-4o` | Best quality, requires API |
| Anthropic | `claude-3-5-sonnet` | Excellent reasoning |

## Usage Examples

### Example 1: Systematic Review Search

```
Query: "What is the effectiveness of cognitive behavioral therapy for chronic pain management in adults?"

PICO:
- P: Adults with chronic pain
- I: Cognitive behavioral therapy
- C: Standard care or placebo
- O: Pain reduction, quality of life
```

### Example 2: Clinical Guideline Search

```
Query: "Current guidelines for antibiotic prophylaxis in dental procedures for patients with prosthetic heart valves"

Evidence Focus: Clinical practice guidelines, systematic reviews
```

### Example 3: Drug Comparison

```
Query: "Metformin vs SGLT2 inhibitors for type 2 diabetes: cardiovascular outcomes"

PICO:
- P: Type 2 diabetes patients
- I: SGLT2 inhibitors
- C: Metformin
- O: Cardiovascular events, mortality
```

## Medical Research Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                   PICO QUERY BUILDER                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ Population  │  │Intervention │  │  Outcome    │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         └────────────────┼────────────────┘                  │
│                          ↓                                   │
│              ┌───────────────────────┐                       │
│              │   MeSH Term Mapping   │                       │
│              └───────────┬───────────┘                       │
│                          ↓                                   │
├─────────────────────────────────────────────────────────────┤
│                   SEARCH EXECUTION                           │
│  ┌─────────┐  ┌───────────────┐  ┌────────────────┐        │
│  │ PubMed  │  │Semantic Scholar│  │   Cochrane    │        │
│  └────┬────┘  └───────┬───────┘  └───────┬────────┘        │
│       └───────────────┼──────────────────┘                  │
│                       ↓                                      │
├─────────────────────────────────────────────────────────────┤
│                 EVIDENCE PROCESSING                          │
│  ┌─────────────────────────────────────────────────┐        │
│  │  • Evidence Level Classification (I-V)          │        │
│  │  • Publication Type Tagging                     │        │
│  │  • Abstract/Full-text Extraction                │        │
│  │  • Quality Assessment                           │        │
│  └─────────────────────────────────────────────────┘        │
│                          ↓                                   │
│              ┌───────────────────────┐                       │
│              │   Research Report     │                       │
│              │   with Citations      │                       │
│              └───────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Areas for Contribution

- [ ] Additional MeSH term mappings
- [ ] Cochrane Library integration
- [ ] Clinical trial registry search (ClinicalTrials.gov)
- [ ] GRADE evidence assessment
- [ ] Multilingual medical term support

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

- Based on [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) by LearningCircuit
- PubMed and MeSH terms provided by [NCBI/NLM](https://www.ncbi.nlm.nih.gov/)

## Citation

If you use Medical Deep Research in your research, please cite:

```bibtex
@software{medical_deep_research,
  title = {Medical Deep Research: Evidence-Based Medical Research Assistant},
  author = {Kim, Junhewk},
  year = {2025},
  url = {https://github.com/junhewk/medical-deep-research}
}
```

## Contact

- GitHub Issues: [Report a bug](https://github.com/junhewk/medical-deep-research/issues)
- Email: junhewk.kim@gmail.com
