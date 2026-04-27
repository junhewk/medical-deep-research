from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.desktop_entry import _safe_download_target


class DesktopEntryTests(unittest.TestCase):
    def test_safe_download_target_uses_downloads_and_avoids_overwrite(self) -> None:
        old_home = os.environ.get("HOME")
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.environ["HOME"] = tmp_dir
                downloads = Path(tmp_dir) / "Downloads"
                downloads.mkdir()
                existing = downloads / "report_1.txt"
                existing.write_text("existing", encoding="utf-8")

                target = _safe_download_target("../report:1.txt")

                self.assertEqual(target.parent, downloads)
                self.assertEqual(target.name, "report_1 (1).txt")
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
