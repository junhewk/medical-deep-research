"""
Medical Research Tools

LangChain tool wrappers for medical research operations including:
- PICO query building
- MeSH term mapping
- PubMed search
- Evidence level classification
- Citation formatting
"""

from typing import Any, Dict, List, Optional, Type

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field


# MeSH term mappings (extended from medical_question.py)
MESH_TERM_MAPPINGS = {
    # Cardiovascular
    "high blood pressure": "Hypertension",
    "hypertension": "Hypertension",
    "heart attack": "Myocardial Infarction",
    "myocardial infarction": "Myocardial Infarction",
    "heart failure": "Heart Failure",
    "irregular heartbeat": "Arrhythmias, Cardiac",
    "arrhythmia": "Arrhythmias, Cardiac",
    "chest pain": "Chest Pain",
    "stroke": "Stroke",
    "atrial fibrillation": "Atrial Fibrillation",
    "coronary artery disease": "Coronary Artery Disease",

    # Diabetes
    "diabetes": "Diabetes Mellitus",
    "type 2 diabetes": "Diabetes Mellitus, Type 2",
    "type 1 diabetes": "Diabetes Mellitus, Type 1",
    "high blood sugar": "Hyperglycemia",
    "low blood sugar": "Hypoglycemia",
    "insulin resistance": "Insulin Resistance",
    "hba1c": "Glycated Hemoglobin A",
    "metformin": "Metformin",
    "sglt2": "Sodium-Glucose Transporter 2 Inhibitors",
    "sglt2 inhibitors": "Sodium-Glucose Transporter 2 Inhibitors",

    # Oncology
    "cancer": "Neoplasms",
    "tumor": "Neoplasms",
    "breast cancer": "Breast Neoplasms",
    "lung cancer": "Lung Neoplasms",
    "colon cancer": "Colonic Neoplasms",
    "prostate cancer": "Prostatic Neoplasms",
    "chemotherapy": "Antineoplastic Agents",
    "immunotherapy": "Immunotherapy",

    # Respiratory
    "asthma": "Asthma",
    "copd": "Pulmonary Disease, Chronic Obstructive",
    "pneumonia": "Pneumonia",
    "bronchitis": "Bronchitis",

    # Infectious Disease
    "infection": "Infection",
    "covid": "COVID-19",
    "coronavirus": "COVID-19",
    "flu": "Influenza, Human",
    "influenza": "Influenza, Human",
    "antibiotic": "Anti-Bacterial Agents",
    "antiviral": "Antiviral Agents",

    # Mental Health
    "depression": "Depressive Disorder",
    "anxiety": "Anxiety Disorders",
    "schizophrenia": "Schizophrenia",
    "bipolar": "Bipolar Disorder",
    "ptsd": "Stress Disorders, Post-Traumatic",

    # Pain
    "pain": "Pain",
    "headache": "Headache",
    "migraine": "Migraine Disorders",
    "back pain": "Back Pain",
    "chronic pain": "Chronic Pain",

    # Dental
    "tooth decay": "Dental Caries",
    "gum disease": "Periodontal Diseases",
    "periodontitis": "Periodontitis",
    "gingivitis": "Gingivitis",
    "toothache": "Toothache",
    "oral health": "Oral Health",
    "dental implant": "Dental Implants",

    # Study Types
    "randomized controlled trial": "Randomized Controlled Trial",
    "rct": "Randomized Controlled Trial",
    "systematic review": "Systematic Review",
    "meta-analysis": "Meta-Analysis",
    "cohort study": "Cohort Studies",
    "case-control": "Case-Control Studies",

    # Outcomes
    "mortality": "Mortality",
    "survival": "Survival Rate",
    "quality of life": "Quality of Life",
    "adverse effects": "Drug-Related Side Effects and Adverse Reactions",
    "side effects": "Drug-Related Side Effects and Adverse Reactions",
}


# Evidence level classification markers
EVIDENCE_LEVEL_MARKERS = {
    "Level I": [
        "systematic review",
        "meta-analysis",
        "cochrane review",
        "pooled analysis",
        "umbrella review",
    ],
    "Level II": [
        "randomized controlled trial",
        "rct",
        "randomised controlled trial",
        "double-blind",
        "placebo-controlled",
        "multicenter trial",
    ],
    "Level III": [
        "cohort study",
        "prospective study",
        "longitudinal study",
        "follow-up study",
        "observational study",
    ],
    "Level IV": [
        "case-control",
        "case control",
        "retrospective study",
        "cross-sectional",
        "survey",
    ],
    "Level V": [
        "case report",
        "case series",
        "expert opinion",
        "narrative review",
        "editorial",
        "letter",
        "commentary",
    ],
}


# Tool Input Schemas
class PICOQueryInput(BaseModel):
    """Input for PICO query builder."""
    query: str = Field(description="The medical research question to analyze")


class MeSHMappingInput(BaseModel):
    """Input for MeSH term mapping."""
    terms: str = Field(description="Medical terms to map to MeSH vocabulary")


class PubMedSearchInput(BaseModel):
    """Input for PubMed search."""
    query: str = Field(description="Search query for PubMed")
    max_results: int = Field(default=10, description="Maximum number of results")


class EvidenceClassifierInput(BaseModel):
    """Input for evidence classification."""
    text: str = Field(description="Text describing a study to classify")


class CitationFormatterInput(BaseModel):
    """Input for citation formatting."""
    title: str = Field(description="Article title")
    authors: str = Field(default="", description="Article authors")
    journal: str = Field(default="", description="Journal name")
    year: str = Field(default="", description="Publication year")
    pmid: str = Field(default="", description="PubMed ID")


class PICOQueryBuilderTool(BaseTool):
    """Tool for building PICO-structured queries from natural language."""

    name: str = "pico_query_builder"
    description: str = """Build a PICO (Population, Intervention, Comparison, Outcome)
    structured query from a medical research question. Use this to properly structure
    clinical questions for evidence-based research."""
    args_schema: Type[BaseModel] = PICOQueryInput

    llm: Optional[Any] = None

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Build PICO query from the input."""
        logger.info(f"Building PICO query for: {query}")

        if self.llm:
            prompt = f"""Analyze this medical research question and extract PICO components:

Question: {query}

Extract and format as:
P (Population): [patient/population characteristics]
I (Intervention): [treatment, test, or exposure]
C (Comparison): [alternative or control, if applicable]
O (Outcome): [outcomes of interest]

Also provide:
- Optimized PubMed search query using MeSH terms
- Key search terms to include

Be specific and use medical terminology."""

            try:
                response = self.llm.invoke([HumanMessage(content=prompt)])
                return response.content if hasattr(response, 'content') else str(response)
            except Exception as e:
                logger.exception(f"LLM call failed: {e}")

        # Fallback: Simple extraction
        return self._simple_pico_extraction(query)

    def _simple_pico_extraction(self, query: str) -> str:
        """Simple rule-based PICO extraction as fallback."""
        query_lower = query.lower()

        # Try to identify components
        population = "Not specified"
        intervention = "Not specified"
        comparison = "Standard care/placebo"
        outcome = "Not specified"

        # Common patterns
        if "patient" in query_lower or "people with" in query_lower:
            population = "See query for population details"
        if "treatment" in query_lower or "therapy" in query_lower:
            intervention = "See query for intervention details"
        if "compared to" in query_lower or "versus" in query_lower:
            comparison = "See query for comparison details"
        if "effect" in query_lower or "outcome" in query_lower:
            outcome = "See query for outcome details"

        return f"""PICO Analysis:
P (Population): {population}
I (Intervention): {intervention}
C (Comparison): {comparison}
O (Outcome): {outcome}

Original query: {query}

Note: For better PICO extraction, please configure an LLM."""


class MeSHTermMappingTool(BaseTool):
    """Tool for mapping common medical terms to MeSH vocabulary."""

    name: str = "mesh_term_mapping"
    description: str = """Map common medical terms to their official MeSH
    (Medical Subject Headings) vocabulary equivalents for precise PubMed searches."""
    args_schema: Type[BaseModel] = MeSHMappingInput

    def _run(
        self,
        terms: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Map terms to MeSH vocabulary."""
        logger.info(f"Mapping terms to MeSH: {terms}")

        terms_lower = terms.lower()
        mapped_terms = []
        unmapped_terms = []

        # Split into individual terms
        term_list = [t.strip() for t in terms.replace(",", " ").split() if t.strip()]

        # Also try multi-word combinations
        for mesh_term, mesh_value in MESH_TERM_MAPPINGS.items():
            if mesh_term in terms_lower:
                mapped_terms.append(f"{mesh_term} -> {mesh_value}[MeSH]")

        # Find unmapped significant terms
        for term in term_list:
            if len(term) > 3 and term not in ["with", "from", "that", "this", "have"]:
                if not any(term in mt.lower() for mt in mapped_terms):
                    unmapped_terms.append(term)

        result = "MeSH Term Mappings:\n"
        if mapped_terms:
            result += "\n".join(f"  - {m}" for m in mapped_terms)
        else:
            result += "  No direct mappings found."

        if unmapped_terms:
            result += f"\n\nTerms without direct mapping (search in Title/Abstract):\n"
            result += ", ".join(unmapped_terms)

        return result


class PubMedSearchTool(BaseTool):
    """Tool for searching PubMed."""

    name: str = "pubmed_search"
    description: str = """Search PubMed for medical literature. Returns article
    titles, abstracts, and metadata. Use MeSH terms for better precision."""
    args_schema: Type[BaseModel] = PubMedSearchInput

    search_engine: Optional[Any] = None
    llm: Optional[Any] = None

    def _run(
        self,
        query: str,
        max_results: int = 10,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Search PubMed with the query."""
        logger.info(f"Searching PubMed for: {query}")

        if self.search_engine:
            try:
                results = self.search_engine.run(query)
                return self._format_results(results, max_results)
            except Exception as e:
                logger.exception(f"PubMed search failed: {e}")
                return f"Search failed: {str(e)}"

        return "PubMed search engine not configured. Please configure a search engine."

    def _format_results(self, results: List[Any], max_results: int) -> str:
        """Format search results."""
        if not results:
            return "No results found."

        formatted = []
        for i, r in enumerate(results[:max_results], 1):
            if isinstance(r, dict):
                title = r.get("title", "Unknown Title")
                snippet = r.get("snippet", r.get("abstract", ""))[:300]
                link = r.get("link", "")
                authors = r.get("authors", [])
                year = r.get("pubdate", "")[:4] if r.get("pubdate") else ""

                entry = f"{i}. **{title}**"
                if authors:
                    author_str = ", ".join(authors[:3])
                    if len(authors) > 3:
                        author_str += " et al."
                    entry += f"\n   Authors: {author_str}"
                if year:
                    entry += f" ({year})"
                if snippet:
                    entry += f"\n   {snippet}..."
                if link:
                    entry += f"\n   Link: {link}"

                formatted.append(entry)

        return f"Found {len(results)} results:\n\n" + "\n\n".join(formatted)


class EvidenceClassifierTool(BaseTool):
    """Tool for classifying evidence levels."""

    name: str = "evidence_classifier"
    description: str = """Classify the evidence level of medical studies based on
    study design (Level I: systematic reviews/meta-analyses, Level II: RCTs,
    Level III: cohort studies, Level IV: case-control, Level V: case reports/expert opinion)."""
    args_schema: Type[BaseModel] = EvidenceClassifierInput

    def _run(
        self,
        text: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Classify evidence level from text."""
        logger.info("Classifying evidence level")

        text_lower = text.lower()
        classifications = []

        for level, markers in EVIDENCE_LEVEL_MARKERS.items():
            for marker in markers:
                if marker in text_lower:
                    classifications.append((level, marker))

        if classifications:
            # Return highest level found (Level I is highest)
            level_order = ["Level I", "Level II", "Level III", "Level IV", "Level V"]
            best_level = min(classifications, key=lambda x: level_order.index(x[0]))

            result = f"Evidence Classification: {best_level[0]}\n"
            result += f"Detected marker: '{best_level[1]}'\n\n"
            result += "Evidence Hierarchy:\n"
            result += "  Level I: Systematic reviews, meta-analyses\n"
            result += "  Level II: Randomized controlled trials\n"
            result += "  Level III: Cohort studies\n"
            result += "  Level IV: Case-control studies\n"
            result += "  Level V: Case reports, expert opinion\n"

            if len(classifications) > 1:
                result += f"\nOther markers found: {', '.join(c[1] for c in classifications[1:])}"

            return result

        return "Unable to determine evidence level from the text. Manual review recommended."


class CitationFormatterTool(BaseTool):
    """Tool for formatting medical citations."""

    name: str = "citation_formatter"
    description: str = """Format medical literature citations in standard format
    (Vancouver/ICMJE style) for medical publications."""
    args_schema: Type[BaseModel] = CitationFormatterInput

    def _run(
        self,
        title: str,
        authors: str = "",
        journal: str = "",
        year: str = "",
        pmid: str = "",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Format a citation in Vancouver style."""
        logger.info(f"Formatting citation for: {title}")

        citation_parts = []

        # Authors
        if authors:
            citation_parts.append(authors)

        # Title
        citation_parts.append(title)

        # Journal and year
        if journal:
            journal_part = journal
            if year:
                journal_part += f". {year}"
            citation_parts.append(journal_part)
        elif year:
            citation_parts.append(year)

        # PMID
        if pmid:
            citation_parts.append(f"PMID: {pmid}")

        formatted = ". ".join(citation_parts)
        if not formatted.endswith("."):
            formatted += "."

        return formatted


# Factory functions for creating tools
def create_pico_query_builder_tool(llm: Optional[BaseChatModel] = None) -> PICOQueryBuilderTool:
    """Create a PICO query builder tool."""
    return PICOQueryBuilderTool(llm=llm)


def create_mesh_term_mapping_tool() -> MeSHTermMappingTool:
    """Create a MeSH term mapping tool."""
    return MeSHTermMappingTool()


def create_pubmed_search_tool(
    search_engine: Any = None,
    llm: Optional[BaseChatModel] = None
) -> PubMedSearchTool:
    """Create a PubMed search tool."""
    return PubMedSearchTool(search_engine=search_engine, llm=llm)


def create_evidence_classifier_tool() -> EvidenceClassifierTool:
    """Create an evidence classifier tool."""
    return EvidenceClassifierTool()


def create_citation_formatter_tool() -> CitationFormatterTool:
    """Create a citation formatter tool."""
    return CitationFormatterTool()


def get_all_medical_tools(
    llm: Optional[BaseChatModel] = None,
    search_engine: Any = None
) -> List[BaseTool]:
    """Get all medical research tools."""
    return [
        create_pico_query_builder_tool(llm),
        create_mesh_term_mapping_tool(),
        create_pubmed_search_tool(search_engine, llm),
        create_evidence_classifier_tool(),
        create_citation_formatter_tool(),
    ]
