from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from medical_deep_research.config import Settings
from medical_deep_research.persistence import AppDatabase
from medical_deep_research.service import ResearchService


class ServiceKeyTests(unittest.TestCase):
    def test_blank_scopus_key_clears_stored_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                service = ResearchService(database)

                service.save_api_key("scopus", "stale-key")
                self.assertEqual(service.get_api_keys()["scopus"], "stale-key")

                service.save_api_key("scopus", "")
                self.assertNotIn("scopus", service.get_api_keys())
            finally:
                # On Windows, the SQLite engine must be disposed before the
                # TemporaryDirectory cleanup or the file handle blocks deletion.
                database.close()

    def test_deepseek_key_enables_deepseek_provider_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            database = AppDatabase(settings)
            try:
                database.create_all()
                service = ResearchService(database)

                service.save_api_key("deepseek", "test-deepseek-key")
                deepseek = next(
                    diag for diag in service.get_provider_diagnostics()
                    if diag["provider"] == "deepseek"
                )

                self.assertEqual(deepseek["default_model"], "deepseek-v4-pro")
                self.assertEqual(deepseek["runtime_engine"], "langchain_deepseek")
                self.assertTrue(deepseek["provider_credentials_present"])
            finally:
                database.close()

    def test_codex_auth_cache_enables_codex_provider_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir), db_filename="test.sqlite")
            settings.codex_home_path.mkdir(parents=True, exist_ok=True)
            settings.codex_home_path.joinpath("auth.json").write_text("{}", encoding="utf-8")
            database = AppDatabase(settings)
            try:
                database.create_all()
                service = ResearchService(database)

                codex = next(
                    diag for diag in service.get_provider_diagnostics()
                    if diag["provider"] == "codex"
                )

                self.assertEqual(codex["default_model"], "gpt-5.4-mini")
                self.assertEqual(codex["runtime_engine"], "openai_codex")
                self.assertTrue(codex["provider_credentials_present"])
                self.assertNotEqual(codex["fallback_reason"], "Codex ChatGPT OAuth is not configured.")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
