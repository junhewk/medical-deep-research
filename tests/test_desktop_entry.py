from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import desktop_entry
from scripts.desktop_entry import _safe_download_target


_HOME_VARS = ("HOME", "USERPROFILE")


class DesktopEntryTests(unittest.TestCase):
    def test_mcp_server_invocation_routes_without_desktop_main(self) -> None:
        argv = ["Medical Deep Research", "--mdr-mcp-server", "literature", "--transport", "stdio"]
        with (
            patch.object(sys, "argv", argv),
            patch("medical_deep_research.mcp.servers.main") as mcp_main,
            patch("medical_deep_research.main.main") as desktop_main,
        ):
            exit_code = desktop_entry.main()
            routed_argv = list(sys.argv)

        self.assertEqual(exit_code, 0)
        self.assertEqual(routed_argv, ["Medical Deep Research", "literature", "--transport", "stdio"])
        mcp_main.assert_called_once_with()
        desktop_main.assert_not_called()

    def test_safe_download_target_uses_downloads_and_avoids_overwrite(self) -> None:
        # Path.home() reads HOME on POSIX and USERPROFILE on Windows, so the
        # fixture must override both for the test to be cross-platform.
        original = {name: os.environ.get(name) for name in _HOME_VARS}
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                for name in _HOME_VARS:
                    os.environ[name] = tmp_dir
                downloads = Path(tmp_dir) / "Downloads"
                downloads.mkdir()
                existing = downloads / "report_1.txt"
                existing.write_text("existing", encoding="utf-8")

                target = _safe_download_target("../report:1.txt")

                self.assertEqual(target.parent, downloads)
                self.assertEqual(target.name, "report_1 (1).txt")
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
