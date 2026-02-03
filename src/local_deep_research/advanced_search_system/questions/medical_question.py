"""
Medical research question generation with PICO framework support.
Specialized for evidence-based medicine research.
"""

from datetime import datetime, UTC
from typing import List, Dict, Optional

from loguru import logger

from .base_question import BaseQuestionGenerator


# Common MeSH term mappings for medical research
MESH_TERM_MAPPINGS = {
    # Cardiovascular
    "high blood pressure": "Hypertension",
    "heart attack": "Myocardial Infarction",
    "heart failure": "Heart Failure",
    "irregular heartbeat": "Arrhythmias, Cardiac",
    "chest pain": "Chest Pain",
    "stroke": "Stroke",

    # Diabetes
    "diabetes": "Diabetes Mellitus",
    "type 2 diabetes": "Diabetes Mellitus, Type 2",
    "type 1 diabetes": "Diabetes Mellitus, Type 1",
    "high blood sugar": "Hyperglycemia",
    "low blood sugar": "Hypoglycemia",

    # Oncology
    "cancer": "Neoplasms",
    "tumor": "Neoplasms",
    "breast cancer": "Breast Neoplasms",
    "lung cancer": "Lung Neoplasms",
    "colon cancer": "Colonic Neoplasms",
    "prostate cancer": "Prostatic Neoplasms",

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

    # Mental Health
    "depression": "Depressive Disorder",
    "anxiety": "Anxiety Disorders",
    "schizophrenia": "Schizophrenia",
    "bipolar": "Bipolar Disorder",

    # Pain
    "pain": "Pain",
    "headache": "Headache",
    "migraine": "Migraine Disorders",
    "back pain": "Back Pain",

    # Dental
    "tooth decay": "Dental Caries",
    "gum disease": "Periodontal Diseases",
    "periodontitis": "Periodontitis",
    "gingivitis": "Gingivitis",
    "toothache": "Toothache",
    "oral health": "Oral Health",
}


# Evidence level classification keywords
EVIDENCE_LEVEL_MARKERS = {
    "Level I": [
        "systematic review",
        "meta-analysis",
        "cochrane review",
        "pooled analysis",
    ],
    "Level II": [
        "randomized controlled trial",
        "rct",
        "randomised controlled trial",
        "double-blind",
        "placebo-controlled",
    ],
    "Level III": [
        "cohort study",
        "prospective study",
        "longitudinal study",
        "follow-up study",
    ],
    "Level IV": [
        "case-control",
        "case control",
        "retrospective study",
        "cross-sectional",
    ],
    "Level V": [
        "case report",
        "case series",
        "expert opinion",
        "narrative review",
        "editorial",
    ],
}


class MedicalQuestionGenerator(BaseQuestionGenerator):
    """
    Medical research question generator with PICO framework support.
    Optimized for evidence-based medicine and clinical research.
    """

    def __init__(self, model, prioritize_recent: bool = True):
        """
        Initialize the medical question generator.

        Args:
            model: The language model to use
            prioritize_recent: Whether to prioritize recent evidence (default True)
        """
        super().__init__(model)
        self.prioritize_recent = prioritize_recent

    def generate_questions(
        self,
        current_knowledge: str,
        query: str,
        questions_per_iteration: int = 2,
        questions_by_iteration: dict = None,
    ) -> List[str]:
        """
        Generate follow-up questions optimized for medical research.

        Uses PICO-aware prompting and emphasizes evidence quality.
        """
        now = datetime.now(UTC)
        current_time = now.strftime("%Y-%m-%d")
        questions_by_iteration = questions_by_iteration or {}

        logger.info("Generating medical research questions...")

        # Medical-specific system context
        medical_context = """You are a medical research assistant specializing in evidence-based medicine.

Research priorities:
1. Prioritize peer-reviewed sources from PubMed and Cochrane Library
2. Focus on high-quality evidence (systematic reviews, RCTs, meta-analyses)
3. Use MeSH terminology for precision when relevant
4. Consider PICO framework for clinical questions
5. Be cautious about claims without strong evidence

Evidence hierarchy (prioritize higher levels):
- Level I: Systematic reviews, meta-analyses
- Level II: Randomized controlled trials (RCTs)
- Level III: Cohort studies
- Level IV: Case-control studies
- Level V: Case reports, expert opinion
"""

        if questions_by_iteration:
            prompt = f"""{medical_context}

Critically evaluate the current knowledge for:
- Evidence quality and level
- Recency of studies
- Potential biases or limitations
- Gaps in the evidence

Query: {query}
Today: {current_time}
Past questions: {questions_by_iteration!s}
Current Knowledge: {current_knowledge}

Generate {questions_per_iteration} high-quality medical research questions that:
1. Target evidence gaps in current knowledge
2. Seek higher-level evidence if current evidence is weak
3. Address clinical relevance and applicability
4. Consider patient populations, interventions, comparisons, and outcomes

Format: One question per line, e.g.
Q: question1
Q: question2
"""
        else:
            prompt = f"""{medical_context}

Generate {questions_per_iteration} high-quality medical research questions to answer: {query}

Today: {current_time}

Consider:
- What systematic reviews or meta-analyses exist?
- What RCTs have been conducted?
- What are the key clinical outcomes?
- What patient populations have been studied?

Format: One question per line, e.g.
Q: question1
Q: question2
"""

        response = self.model.invoke(prompt)

        response_text = ""
        if hasattr(response, "content"):
            response_text = response.content
        else:
            response_text = str(response)

        questions = [
            q.replace("Q:", "").strip()
            for q in response_text.split("\n")
            if q.strip().startswith("Q:")
        ][:questions_per_iteration]

        # Apply MeSH term enrichment to questions
        questions = [self._enrich_with_mesh(q) for q in questions]

        logger.info(f"Generated {len(questions)} medical research questions")

        return questions

    def generate_pico_questions(
        self,
        population: str,
        intervention: str,
        comparison: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> List[str]:
        """
        Generate research questions based on PICO framework.

        Args:
            population: Patient/Population description
            intervention: Intervention/Exposure
            comparison: Comparison intervention (optional)
            outcome: Outcome of interest (optional)

        Returns:
            List of structured research questions
        """
        # Map terms to MeSH
        population_mesh = self._get_mesh_term(population)
        intervention_mesh = self._get_mesh_term(intervention)
        comparison_mesh = self._get_mesh_term(comparison) if comparison else None
        outcome_mesh = self._get_mesh_term(outcome) if outcome else None

        prompt = f"""Generate 3 structured medical research questions using the PICO framework:

PICO Components:
- Population: {population} (MeSH: {population_mesh or 'N/A'})
- Intervention: {intervention} (MeSH: {intervention_mesh or 'N/A'})
- Comparison: {comparison or 'standard care/placebo'} (MeSH: {comparison_mesh or 'N/A'})
- Outcome: {outcome or 'clinical outcomes'} (MeSH: {outcome_mesh or 'N/A'})

Generate questions that:
1. One focused on efficacy/effectiveness
2. One focused on safety/adverse effects
3. One focused on implementation/practical considerations

Format: One question per line, e.g.
Q: question1
Q: question2
Q: question3
"""

        response = self.model.invoke(prompt)

        response_text = ""
        if hasattr(response, "content"):
            response_text = response.content
        else:
            response_text = str(response)

        questions = [
            q.replace("Q:", "").strip()
            for q in response_text.split("\n")
            if q.strip().startswith("Q:")
        ][:3]

        return questions

    def build_pubmed_query(
        self,
        population: str,
        intervention: str,
        comparison: Optional[str] = None,
        outcome: Optional[str] = None,
        study_types: Optional[List[str]] = None,
    ) -> str:
        """
        Build an optimized PubMed query from PICO components.

        Args:
            population: Patient/Population description
            intervention: Intervention/Exposure
            comparison: Comparison intervention (optional)
            outcome: Outcome of interest (optional)
            study_types: List of study types to filter (e.g., ["RCT", "Meta-Analysis"])

        Returns:
            Formatted PubMed query string
        """
        query_parts = []

        # Population
        pop_mesh = self._get_mesh_term(population)
        if pop_mesh:
            query_parts.append(f'("{pop_mesh}"[Mesh] OR {population}[Title/Abstract])')
        else:
            query_parts.append(f'{population}[Title/Abstract]')

        # Intervention
        int_mesh = self._get_mesh_term(intervention)
        if int_mesh:
            query_parts.append(f'("{int_mesh}"[Mesh] OR {intervention}[Title/Abstract])')
        else:
            query_parts.append(f'{intervention}[Title/Abstract]')

        # Comparison (if provided)
        if comparison:
            comp_mesh = self._get_mesh_term(comparison)
            if comp_mesh:
                query_parts.append(f'("{comp_mesh}"[Mesh] OR {comparison}[Title/Abstract])')
            else:
                query_parts.append(f'{comparison}[Title/Abstract]')

        # Outcome (if provided)
        if outcome:
            out_mesh = self._get_mesh_term(outcome)
            if out_mesh:
                query_parts.append(f'("{out_mesh}"[Mesh] OR {outcome}[Title/Abstract])')
            else:
                query_parts.append(f'{outcome}[Title/Abstract]')

        # Build main query
        main_query = " AND ".join(query_parts)

        # Add study type filter if specified
        if study_types:
            type_filters = []
            for st in study_types:
                st_lower = st.lower()
                if "meta" in st_lower:
                    type_filters.append('"Meta-Analysis"[Publication Type]')
                elif "systematic" in st_lower:
                    type_filters.append('"Systematic Review"[Publication Type]')
                elif "rct" in st_lower or "randomized" in st_lower:
                    type_filters.append('"Randomized Controlled Trial"[Publication Type]')
                elif "cohort" in st_lower:
                    type_filters.append('"Cohort Studies"[Mesh]')
                elif "case-control" in st_lower:
                    type_filters.append('"Case-Control Studies"[Mesh]')

            if type_filters:
                type_query = " OR ".join(type_filters)
                main_query = f"({main_query}) AND ({type_query})"

        return main_query

    def _get_mesh_term(self, term: str) -> Optional[str]:
        """
        Get MeSH term mapping for a common medical term.

        Args:
            term: Common medical term

        Returns:
            MeSH term if mapping exists, None otherwise
        """
        if not term:
            return None

        term_lower = term.lower().strip()
        return MESH_TERM_MAPPINGS.get(term_lower)

    def _enrich_with_mesh(self, question: str) -> str:
        """
        Enrich a question with MeSH terms where applicable.

        Args:
            question: Original question

        Returns:
            Question with MeSH term suggestions
        """
        # Simple enrichment - don't modify the question text
        # Just log any potential MeSH mappings for transparency
        question_lower = question.lower()

        for term, mesh in MESH_TERM_MAPPINGS.items():
            if term in question_lower:
                logger.debug(f"MeSH mapping available: '{term}' -> '{mesh}'")

        return question

    def classify_evidence_level(self, text: str) -> Optional[str]:
        """
        Classify the evidence level of a study based on text description.

        Args:
            text: Text describing the study (title, abstract, etc.)

        Returns:
            Evidence level (I-V) or None if unable to classify
        """
        text_lower = text.lower()

        for level, markers in EVIDENCE_LEVEL_MARKERS.items():
            for marker in markers:
                if marker in text_lower:
                    return level

        return None

    def generate_sub_questions(
        self, query: str, context: str = ""
    ) -> List[str]:
        """
        Generate sub-questions for complex medical queries.

        Args:
            query: The main query to break down
            context: Additional context

        Returns:
            List of sub-questions
        """
        prompt = f"""You are an expert medical researcher. Break down this complex medical question into simpler sub-questions.

Original Question: {query}

{context}

Consider the PICO framework when breaking down:
- Population: Who are the patients?
- Intervention: What treatment/exposure?
- Comparison: What is the alternative?
- Outcome: What results matter?

Generate 2-5 sub-questions that would help comprehensively answer the original question.
Focus on evidence-based aspects.

Format as a numbered list:
1. First sub-question
2. Second sub-question
...
"""

        try:
            response = self.model.invoke(prompt)

            content = ""
            if hasattr(response, "content"):
                content = response.content
            else:
                content = str(response)

            sub_questions = []
            for line in content.strip().split("\n"):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith("-")):
                    parts = (
                        line.split(".", 1)
                        if "." in line
                        else line.split(" ", 1)
                    )
                    if len(parts) > 1:
                        sub_question = parts[1].strip()
                        sub_questions.append(sub_question)

            return sub_questions[:5]
        except Exception as e:
            logger.exception(f"Error generating medical sub-questions: {e!s}")
            return []
