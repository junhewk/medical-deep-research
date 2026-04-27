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


if __name__ == "__main__":
    unittest.main()
