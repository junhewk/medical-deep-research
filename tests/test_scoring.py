from __future__ import annotations

import unittest

from medical_deep_research.research.models import EvidenceStudy
from medical_deep_research.research.scoring import get_evidence_level_score, score_and_rank_results


class EvidenceLevelScoreTests(unittest.TestCase):
    def test_each_level_scores_distinctly(self) -> None:
        # Regression: "level i" is a substring of "level ii"/"iii"/"iv", so the
        # checks must run most-specific first or every level collapses to 1.0.
        self.assertEqual(get_evidence_level_score("Level I"), 1.0)
        self.assertEqual(get_evidence_level_score("Level II"), 0.8)
        self.assertEqual(get_evidence_level_score("Level III"), 0.6)
        self.assertEqual(get_evidence_level_score("Level IV"), 0.4)
        self.assertEqual(get_evidence_level_score("Level V"), 0.2)
        self.assertEqual(get_evidence_level_score(None), 0.3)
        self.assertEqual(get_evidence_level_score("unknown"), 0.3)


class ScoringTests(unittest.TestCase):
    def test_structured_query_relevance_demotes_wrong_intervention(self) -> None:
        query_payload = {
            "population": "type 2 diabetes",
            "intervention": "large language models or chatbots",
            "comparison": "usual care",
            "outcome": "self-management education",
        }
        studies = [
            EvidenceStudy(
                source="pubmed",
                source_id="wrong",
                title="Psycho-spiritual intervention in women with type 2 diabetes",
                abstract="A randomized clinical trial of reflective counseling and usual care.",
                publication_year="2025",
                doi="10.1000/wrong",
                evidence_level="Level I",
                citation_count=30,
            ),
            EvidenceStudy(
                source="pubmed",
                source_id="right",
                title="Conversational agent for diabetes self-management education",
                abstract="A chatbot powered by generative artificial intelligence supported adults with type 2 diabetes.",
                publication_year="2025",
                doi="10.1000/right",
                evidence_level="Level II",
                citation_count=2,
            ),
        ]

        ranked = score_and_rank_results(
            studies,
            context="clinical",
            query="Do large language models improve diabetes self-management education?",
            query_payload=query_payload,
        )

        self.assertEqual(ranked[0].source_id, "right")
        self.assertGreaterEqual(ranked[0].relevance_score, 0.7)
        self.assertLess(ranked[1].relevance_score, 0.35)

    def test_pcc_context_promotes_direct_ai_communication_training(self) -> None:
        query_payload = {
            "population": "health professions learners and clinicians",
            "concept": "AI-supported education training simulation feedback",
            "context": "communication training shared decision making patient-centered conversations",
        }
        studies = [
            EvidenceStudy(
                source="openalex",
                source_id="broad",
                title="Artificial intelligence in undergraduate health professions education",
                abstract="A systematic review of AI tools for assessment and clinical reasoning in medical education.",
                publication_year="2026",
                doi="10.1000/broad",
                evidence_level="Level I",
                citation_count=30,
            ),
            EvidenceStudy(
                source="pubmed",
                source_id="direct",
                title="Large language model virtual patient for communication skills training",
                abstract=(
                    "Medical students practiced medical interview, empathy, and shared decision making "
                    "with an AI simulated patient and received feedback."
                ),
                publication_year="2026",
                doi="10.1000/direct",
                evidence_level="Level III",
                citation_count=2,
            ),
        ]

        ranked = score_and_rank_results(
            studies,
            context="clinical",
            query=(
                "AI-supported education for health professions learners in communication training "
                "and shared decision making"
            ),
            query_payload=query_payload,
        )

        self.assertEqual(ranked[0].source_id, "direct")
        self.assertGreater(ranked[0].relevance_score, ranked[1].relevance_score)


if __name__ == "__main__":
    unittest.main()
