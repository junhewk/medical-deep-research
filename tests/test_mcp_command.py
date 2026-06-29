from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from medical_deep_research.models import RunRequest
from medical_deep_research.runtime import _build_mcp_server_env, _mcp_stdio_command


class McpCommandTests(unittest.TestCase):
    def test_mcp_stdio_command_uses_python_module_in_source_checkout(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            _command, args = _mcp_stdio_command("literature")

        self.assertEqual(
            args,
            ["-m", "medical_deep_research.mcp.servers", "literature", "--transport", "stdio"],
        )

    def test_mcp_stdio_command_uses_private_entry_in_frozen_app(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/Applications/Medical Deep Research.app/Contents/MacOS/Medical Deep Research"),
        ):
            command, args = _mcp_stdio_command("evidence")

        self.assertEqual(command, "/Applications/Medical Deep Research.app/Contents/MacOS/Medical Deep Research")
        self.assertEqual(args, ["--mdr-mcp-server", "evidence", "--transport", "stdio"])

    def test_codex_mcp_env_includes_search_credentials(self) -> None:
        request = RunRequest(
            run_id="test",
            query="query",
            query_type="free",
            mode="quick",
            provider="codex",
            model="gpt-5.4-mini",
            api_keys={
                "ncbi": "ncbi-key",
                "scopus": "scopus-key",
                "semantic_scholar": "semantic-key",
            },
        )

        env = _build_mcp_server_env(request)

        self.assertEqual(env["MDR_NCBI_API_KEY"], "ncbi-key")
        self.assertEqual(env["MDR_SCOPUS_API_KEY"], "scopus-key")
        self.assertEqual(env["MDR_SEMANTIC_SCHOLAR_API_KEY"], "semantic-key")
        self.assertEqual(env["MDR_OFFLINE_MODE"], "0")


if __name__ == "__main__":
    unittest.main()
