from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopBuildWorkflowTests(unittest.TestCase):
    def test_installs_codex_extra_for_pyinstaller_bundle(self) -> None:
        spec = (ROOT / "Medical Deep Research.spec").read_text()
        workflow = (ROOT / ".github/workflows/python-desktop-build.yml").read_text()

        if "openai_codex" not in spec and "codex_cli_bin" not in spec:
            return

        self.assertIn("--extra codex", workflow)
