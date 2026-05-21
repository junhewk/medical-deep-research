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


if __name__ == "__main__":
    unittest.main()
