from __future__ import annotations

import unittest
from unittest.mock import patch

from medical_deep_research.model_catalog import (
    default_model_for_provider,
    provider_model_options,
)


class ModelCatalogTests(unittest.TestCase):
    def test_builtin_catalog_returns_supported_provider_models(self) -> None:
        models = provider_model_options("openai", include_live=False)

        self.assertIn("gpt-5-mini", models)
        self.assertEqual(default_model_for_provider("openai"), "gpt-5-mini")

    def test_live_catalog_is_opt_in_and_merged(self) -> None:
        with patch(
            "medical_deep_research.model_catalog._live_provider_models",
            return_value={"openai": {"future-model": "Future Model"}},
        ):
            models = provider_model_options("openai", include_live=True)

        self.assertIn("gpt-5-mini", models)
        self.assertEqual(models["future-model"], "Future Model")


if __name__ == "__main__":
    unittest.main()
