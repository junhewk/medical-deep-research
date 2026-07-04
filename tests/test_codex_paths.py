from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from medical_deep_research.codex_auth import CodexAuthManager, CodexRuntimeStatus, check_codex_runtime
from medical_deep_research.config import Settings, load_settings
from medical_deep_research.models import RunRequest
from medical_deep_research.runtime import _codex_home_for_request


class _FakeCodexCliBin:
    def __init__(self, path: Path | None = None, exc: Exception | None = None) -> None:
        self._path = path
        self._exc = exc

    def bundled_codex_path(self) -> Path:
        if self._exc is not None:
            raise self._exc
        if self._path is None:
            raise FileNotFoundError("missing codex binary")
        return self._path


def _module_loader(modules: dict[str, object]):
    def load(name: str) -> object:
        module = modules.get(name)
        if isinstance(module, Exception):
            raise module
        if module is None:
            raise ImportError(name)
        return module

    return load


class CodexPathTests(unittest.TestCase):
    def test_codex_runtime_check_succeeds_when_sdk_and_binary_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            codex_bin = Path(tmp_dir) / "codex.exe"
            codex_bin.write_text("binary", encoding="utf-8")

            status = check_codex_runtime(
                import_module=_module_loader(
                    {
                        "openai_codex": object(),
                        "codex_cli_bin": _FakeCodexCliBin(codex_bin),
                    }
                )
            )

        self.assertTrue(status.available)
        self.assertEqual(status.codex_bin_path, str(codex_bin))
        self.assertIsNone(status.error)

    def test_codex_runtime_check_reports_missing_sdk(self) -> None:
        status = check_codex_runtime(import_module=_module_loader({}))

        self.assertFalse(status.available)
        self.assertIn("Python SDK", status.error or "")
        self.assertTrue(status.download_url)

    def test_codex_runtime_check_reports_missing_runtime_package(self) -> None:
        status = check_codex_runtime(import_module=_module_loader({"openai_codex": object()}))

        self.assertFalse(status.available)
        self.assertIn("runtime package", status.error or "")

    def test_codex_runtime_check_reports_missing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "codex.exe"
            status = check_codex_runtime(
                import_module=_module_loader(
                    {
                        "openai_codex": object(),
                        "codex_cli_bin": _FakeCodexCliBin(missing),
                    }
                )
            )

        self.assertFalse(status.available)
        self.assertIn("executable", status.error or "")

    def test_load_settings_resolves_data_dir_and_creates_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                with patch.dict(os.environ, {"MDR_DATA_DIR": "relative-data"}, clear=False):
                    settings = load_settings()
            finally:
                os.chdir(previous_cwd)

            expected = (Path(tmp_dir) / "relative-data").resolve()
            self.assertEqual(settings.data_dir, expected)
            self.assertTrue(settings.data_dir.is_absolute())
            self.assertTrue(settings.codex_home_path.is_dir())

    def test_auth_manager_exposes_absolute_codex_home_for_direct_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                settings = Settings(data_dir=Path("relative-data"))
                manager = CodexAuthManager(settings)
                codex_home = manager.codex_home_path
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(codex_home, (Path(tmp_dir) / "relative-data" / "codex-home").resolve())
            self.assertTrue(codex_home.is_absolute())

    def test_auth_status_uses_existing_cache_without_sdk_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir))
            settings.codex_home_path.mkdir(parents=True, exist_ok=True)
            settings.codex_home_path.joinpath("auth.json").write_text("{}", encoding="utf-8")
            manager = CodexAuthManager(settings)

            with (
                patch(
                    "medical_deep_research.codex_auth.check_codex_runtime",
                    return_value=CodexRuntimeStatus(available=True, codex_bin_path="/tmp/codex"),
                ),
                patch("medical_deep_research.codex_auth._codex_sdk", side_effect=AssertionError("SDK checked")),
            ):
                status = asyncio.run(manager.status(refresh=False))

            self.assertTrue(status.configured)
            self.assertIsNone(status.error)
            self.assertTrue(status.runtime_available)

    def test_auth_status_reports_runtime_error_without_refreshing_cached_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(data_dir=Path(tmp_dir))
            settings.codex_home_path.mkdir(parents=True, exist_ok=True)
            settings.codex_home_path.joinpath("auth.json").write_text("{}", encoding="utf-8")
            manager = CodexAuthManager(settings)

            with (
                patch(
                    "medical_deep_research.codex_auth.check_codex_runtime",
                    return_value=CodexRuntimeStatus(available=False, error="missing codex.exe"),
                ),
                patch("medical_deep_research.codex_auth._codex_sdk", side_effect=AssertionError("SDK checked")),
            ):
                status = asyncio.run(manager.status(refresh=False))

            self.assertTrue(status.configured)
            self.assertFalse(status.runtime_available)
            self.assertEqual(status.runtime_error, "missing codex.exe")
            self.assertEqual(status.error, "missing codex.exe")

    def test_runtime_codex_home_for_request_is_absolute_and_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                request = RunRequest(
                    run_id="test",
                    query="query",
                    query_type="free",
                    mode="quick",
                    provider="codex",
                    model="gpt-5.4-mini",
                    codex_home_path="relative-codex-home",
                )
                codex_home = _codex_home_for_request(request)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(codex_home, (Path(tmp_dir) / "relative-codex-home").resolve())
            self.assertTrue(codex_home.is_absolute())
            self.assertTrue(codex_home.is_dir())


if __name__ == "__main__":
    unittest.main()
