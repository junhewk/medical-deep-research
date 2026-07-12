from __future__ import annotations

import hashlib
import io
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

import httpx
from packaging.version import Version

from medical_deep_research import __version__
from medical_deep_research.updates import (
    CHECKSUM_ASSET,
    GitHubUpdateService,
    InstallContext,
    UpdateStatus,
    _checksum_for_asset,
    _safe_extract_zip,
)


def _asset(name: str, *, size: int = 10) -> dict[str, object]:
    return {
        "name": name,
        "browser_download_url": f"https://downloads.test/{name}",
        "size": size,
    }


def _release(version: str, *, draft: bool = False, prerelease: bool = False) -> dict[str, object]:
    return {
        "tag_name": f"v{version}",
        "name": f"Version {version}",
        "body": "Changes",
        "html_url": f"https://github.test/releases/v{version}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            _asset(f"Medical-Deep-Research-{version}-Windows.zip"),
            _asset(f"Medical-Deep-Research-{version}-macOS-update.zip"),
            _asset(CHECKSUM_ASSET),
        ],
    }


class UpdateReleaseTests(unittest.TestCase):
    def test_runtime_and_project_versions_match(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, "2.9.12")
        self.assertEqual(project["project"]["version"], __version__)

    def test_selects_highest_stable_semantic_release(self) -> None:
        context = InstallContext("win32", True, Path("app.exe"), Path("install"))
        service = GitHubUpdateService(Path("data"), context=context, current_version="2.9.6")
        manual = _release("9.0.0")
        manual["tag_name"] = "manual-42"

        selected = service._select_release(
            [_release("2.9.9"), _release("3.0.0", prerelease=True), manual, _release("2.10.0")]
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.version, Version("2.10.0"))
        self.assertEqual(selected.asset.name, "Medical-Deep-Research-2.10.0-Windows.zip")

    def test_release_without_checksum_keeps_browser_fallback_metadata(self) -> None:
        context = InstallContext("darwin", True, Path("app"), Path("Medical Deep Research.app"))
        service = GitHubUpdateService(Path("data"), context=context)
        raw = _release("3.0.0")
        raw["assets"] = raw["assets"][:-1]

        release = service._select_release([raw])
        self.assertIsNotNone(release)
        self.assertIsNone(release.checksum_asset)

    def test_checksum_manifest_requires_exact_filename_and_sha256(self) -> None:
        digest = "a" * 64
        manifest = f"{digest}  app.zip\n{'b' * 64}  other.zip\n"
        self.assertEqual(_checksum_for_asset(manifest, "app.zip"), digest)
        self.assertIsNone(_checksum_for_asset(manifest, "missing.zip"))

    def test_zip_extraction_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", "bad")
            destination = Path(tmp) / "stage"
            destination.mkdir()

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                _safe_extract_zip(archive, destination)


class UpdateNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_packaged_writable_install_reports_update_available(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request, json=[_release("3.0.0")])

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Medical Deep Research"
            service = GitHubUpdateService(
                Path(tmp) / "data",
                context=InstallContext("win32", True, target / "Medical Deep Research.exe", target),
                current_version="2.9.6",
                client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )

            result = await service.check()

            self.assertEqual(result.status, UpdateStatus.UPDATE_AVAILABLE)

    async def test_source_build_reports_browser_assisted_update(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request, json=[_release("3.0.0")])

        service = GitHubUpdateService(
            Path("data"),
            context=InstallContext("linux", False, Path("python"), None),
            current_version="2.9.6",
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await service.check()

        self.assertEqual(result.status, UpdateStatus.UNSUPPORTED)
        self.assertEqual(result.release.version, Version("3.0.0"))

    async def test_download_verifies_and_stages_windows_archive(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as bundle:
            bundle.writestr("Medical Deep Research/Medical Deep Research.exe", b"binary")
            bundle.writestr("Medical Deep Research/runtime/library.dat", b"runtime")
        archive = archive_buffer.getvalue()
        digest = hashlib.sha256(archive).hexdigest()
        raw = _release("3.0.0")
        raw["assets"][0]["size"] = len(archive)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(CHECKSUM_ASSET):
                return httpx.Response(
                    200,
                    request=request,
                    text=f"{digest}  Medical-Deep-Research-3.0.0-Windows.zip\n",
                )
            return httpx.Response(200, request=request, content=archive)

        with tempfile.TemporaryDirectory() as tmp:
            context = InstallContext("win32", True, Path("app.exe"), Path(tmp) / "installed")
            service = GitHubUpdateService(
                Path(tmp),
                context=context,
                current_version="2.9.6",
                client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
            release = service._select_release([raw])

            staged = await service.download_and_stage(release)

            self.assertEqual(staged.name, "Medical Deep Research")
            self.assertTrue((staged / "Medical Deep Research.exe").is_file())

    async def test_download_removes_partial_file_on_checksum_failure(self) -> None:
        archive = b"not the expected bytes"
        raw = _release("3.0.0")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(CHECKSUM_ASSET):
                return httpx.Response(
                    200,
                    request=request,
                    text=f"{'0' * 64}  Medical-Deep-Research-3.0.0-Windows.zip\n",
                )
            return httpx.Response(200, request=request, content=archive)

        with tempfile.TemporaryDirectory() as tmp:
            service = GitHubUpdateService(
                Path(tmp),
                context=InstallContext("win32", True, Path("app.exe"), Path(tmp) / "installed"),
                current_version="2.9.6",
                client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
            release = service._select_release([raw])

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                await service.download_and_stage(release)

            partial = Path(tmp) / "updates/3.0.0/Medical-Deep-Research-3.0.0-Windows.zip.part"
            self.assertFalse(partial.exists())


if __name__ == "__main__":
    unittest.main()
