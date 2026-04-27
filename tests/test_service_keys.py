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
            database.create_all()
            service = ResearchService(database)

            service.save_api_key("scopus", "stale-key")
            self.assertEqual(service.get_api_keys()["scopus"], "stale-key")

            service.save_api_key("scopus", "")
            self.assertNotIn("scopus", service.get_api_keys())


if __name__ == "__main__":
    unittest.main()
