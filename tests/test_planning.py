from __future__ import annotations

import unittest

from medical_deep_research.research.planning import build_query_plan


class PlanningTests(unittest.TestCase):
    def test_pico_payload_removes_framework_labels_from_source_queries(self) -> None:
        query = (
            "Population: Video assisted thoracoscopic surgery; "
            "Intervention: SAPB; "
            "Comparison: Thoracic epidural analgesia; "
            "Outcome: pain"
        )
        plan = build_query_plan(
            query,
            "pico",
            "anthropic",
            {
                "population": "Video assisted thoracoscopic surgery",
                "intervention": "SAPB",
                "comparison": "Thoracic epidural analgesia",
                "outcome": "pain",
            },
        )

        forbidden = {"population", "intervention", "comparison", "outcome"}
        self.assertFalse(forbidden.intersection(plan.keywords))
        self.assertTrue(
            {
                "video",
                "assisted",
                "thoracoscopic",
                "surgery",
                "sapb",
                "thoracic",
                "epidural",
                "analgesia",
                "pain",
            }.issubset(set(plan.keywords))
        )
        self.assertNotIn("Population:", plan.normalized_query)
        self.assertNotIn("Intervention:", plan.source_queries["Scopus"])
        self.assertIn("sapb", plan.source_queries["Scopus"].lower())
        self.assertIn("epidural", plan.source_queries["Scopus"].lower())
        self.assertIn("pain", plan.source_queries["Scopus"].lower())

    def test_planning_adds_published_sources_without_preprints(self) -> None:
        plan = build_query_plan(
            "adult diabetes education randomized trial",
            "free",
            "openai",
        )

        self.assertIn("PMC", plan.databases)
        self.assertIn("Europe PMC", plan.databases)
        self.assertIn("Crossref", plan.databases)
        self.assertNotIn("ClinicalTrials.gov", plan.databases)
        self.assertNotIn("arXiv", plan.databases)
        self.assertNotIn("medRxiv", plan.databases)
        self.assertNotIn("bioRxiv", plan.databases)

    def test_pcc_ai_communication_query_requires_ai_and_communication_terms(self) -> None:
        plan = build_query_plan(
            (
                "Population: health professions learners, trainees, clinicians, educators; "
                "Concept: AI-supported education, training, simulation, coaching, assessment, feedback; "
                "Context: shared decision making education, communication training, patient-centered decision conversations"
            ),
            "pcc",
            "codex",
            {
                "population": "health professions learners, trainees, clinicians, educators",
                "concept": "AI-supported education, training, simulation, coaching, assessment, feedback",
                "context": "shared decision making education, communication training, patient-centered decision conversations",
            },
        )

        pubmed = plan.source_queries["PubMed"].lower()
        self.assertIn('"artificial intelligence"[tiab]', pubmed)
        self.assertIn('"large language model"[tiab]', pubmed)
        self.assertIn('"virtual patient"[tiab]', pubmed)
        self.assertIn('"communication skills"[tiab]', pubmed)
        self.assertIn('"shared decision making"[tiab]', pubmed)
        self.assertIn(") and (", pubmed)
        self.assertNotIn('"ai-supported education"[tiab] or training[tiab]', pubmed)

        openalex = plan.source_queries["OpenAlex"].lower()
        self.assertIn("chatgpt", openalex)
        self.assertIn("medical interview", openalex)
        self.assertIn("breaking bad news", openalex)


if __name__ == "__main__":
    unittest.main()
