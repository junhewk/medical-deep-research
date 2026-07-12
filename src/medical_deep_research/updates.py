from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from . import __version__


GITHUB_REPOSITORY = "junhewk/medical-deep-research"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
CHECKSUM_ASSET = "SHA256SUMS.txt"
_VERSION_TAG = re.compile(r"^v?(\d+\.\d+\.\d+(?:\.post\d+)?)$")


class UpdateStatus(StrEnum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    version: Version
    tag_name: str
    name: str
    notes: str
    html_url: str
    asset: ReleaseAsset | None
    checksum_asset: ReleaseAsset | None


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    release: ReleaseInfo | None = None
    message: str = ""


@dataclass(frozen=True)
class InstallContext:
    platform: str
    frozen: bool
    executable: Path
    target: Path | None

    @classmethod
    def detect(cls) -> InstallContext:
        executable = Path(sys.executable).resolve()
        frozen = bool(getattr(sys, "frozen", False))
        target: Path | None = None
        if frozen and sys.platform == "win32":
            target = executable.parent
        elif frozen and sys.platform == "darwin":
            for parent in executable.parents:
                if parent.suffix == ".app":
                    target = parent
                    break
        return cls(sys.platform, frozen, executable, target)

    @property
    def can_self_update(self) -> bool:
        return self.frozen and self.platform in {"win32", "darwin"} and self.target is not None


ProgressCallback = Callable[[int, int], None]


class GitHubUpdateService:
    def __init__(
        self,
        data_dir: Path,
        *,
        context: InstallContext | None = None,
        current_version: str = __version__,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.context = context or InstallContext.detect()
        self.current_version = Version(current_version)
        self._client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"medical-deep-research/{__version__}",
            },
        )

    async def check(self) -> UpdateCheckResult:
        try:
            async with self._client_factory() as client:
                response = await client.get(GITHUB_API_URL, params={"per_page": 20})
                response.raise_for_status()
                releases = response.json()
            release = self._select_release(releases)
            if release is None:
                return UpdateCheckResult(UpdateStatus.UP_TO_DATE)
            if release.version <= self.current_version:
                return UpdateCheckResult(UpdateStatus.UP_TO_DATE, release=release)
            if not self.context.can_self_update:
                return UpdateCheckResult(
                    UpdateStatus.UNSUPPORTED,
                    release=release,
                    message="Automatic installation is available only in packaged Windows and macOS builds.",
                )
            if self.context.target is None or not _directory_is_writable(self.context.target.parent):
                return UpdateCheckResult(
                    UpdateStatus.UNSUPPORTED,
                    release=release,
                    message="The application directory is read-only.",
                )
            if release.asset is None or release.checksum_asset is None:
                return UpdateCheckResult(
                    UpdateStatus.UNSUPPORTED,
                    release=release,
                    message="This release does not provide a verified in-app update asset.",
                )
            return UpdateCheckResult(UpdateStatus.UPDATE_AVAILABLE, release=release)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return UpdateCheckResult(UpdateStatus.ERROR, message=str(exc))

    def _select_release(self, payload: Any) -> ReleaseInfo | None:
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an invalid releases response")
        candidates: list[ReleaseInfo] = []
        for raw in payload:
            if not isinstance(raw, dict) or raw.get("draft") or raw.get("prerelease"):
                continue
            tag = str(raw.get("tag_name") or "")
            match = _VERSION_TAG.fullmatch(tag)
            if match is None:
                continue
            try:
                version = Version(match.group(1))
            except InvalidVersion:
                continue
            if version.is_prerelease or version.is_devrelease or version.local is not None:
                continue
            assets = {
                str(item.get("name") or ""): ReleaseAsset(
                    name=str(item.get("name") or ""),
                    download_url=str(item.get("browser_download_url") or ""),
                    size=int(item.get("size") or 0),
                )
                for item in raw.get("assets", [])
                if isinstance(item, dict) and item.get("browser_download_url")
            }
            asset_name = self._asset_name(version)
            asset = assets.get(asset_name)
            checksums = assets.get(CHECKSUM_ASSET)
            candidates.append(
                ReleaseInfo(
                    version=version,
                    tag_name=tag,
                    name=str(raw.get("name") or tag),
                    notes=str(raw.get("body") or ""),
                    html_url=str(raw.get("html_url") or RELEASES_URL),
                    asset=asset,
                    checksum_asset=checksums,
                )
            )
        return max(candidates, key=lambda item: item.version, default=None)

    def _asset_name(self, version: Version) -> str:
        if self.context.platform == "win32":
            return f"Medical-Deep-Research-{version}-Windows.zip"
        if self.context.platform == "darwin":
            return f"Medical-Deep-Research-{version}-macOS-update.zip"
        return ""

    async def download_and_stage(
        self,
        release: ReleaseInfo,
        *,
        progress: ProgressCallback | None = None,
    ) -> Path:
        if release.asset is None or release.checksum_asset is None:
            raise ValueError("This release has no verified update asset for this platform")
        update_root = self.data_dir / "updates" / str(release.version)
        update_root.mkdir(parents=True, exist_ok=True)
        archive = update_root / release.asset.name
        partial = archive.with_suffix(archive.suffix + ".part")
        try:
            async with self._client_factory() as client:
                checksum_response = await client.get(release.checksum_asset.download_url)
                checksum_response.raise_for_status()
                checksum = _checksum_for_asset(checksum_response.text, release.asset.name)
                if checksum is None:
                    raise ValueError(f"No checksum was published for {release.asset.name}")

                digest = hashlib.sha256()
                downloaded = 0
                async with client.stream("GET", release.asset.download_url) as response:
                    response.raise_for_status()
                    total = release.asset.size or int(response.headers.get("Content-Length", "0") or 0)
                    with partial.open("wb") as stream:
                        async for chunk in response.aiter_bytes():
                            stream.write(chunk)
                            digest.update(chunk)
                            downloaded += len(chunk)
                            if progress is not None:
                                progress(downloaded, total)
                if digest.hexdigest().lower() != checksum.lower():
                    raise ValueError("The downloaded update failed SHA-256 verification")
                partial.replace(archive)

            staging = update_root / "staging"
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir()
            if self.context.platform == "darwin":
                process = await asyncio.create_subprocess_exec(
                    "/usr/bin/ditto", "-x", "-k", str(archive), str(staging)
                )
                if await process.wait() != 0:
                    raise RuntimeError("Could not extract the macOS update")
            else:
                _safe_extract_zip(archive, staging)
            return await self._validate_staging(staging)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

    async def _validate_staging(self, staging: Path) -> Path:
        if self.context.platform == "win32":
            roots = [item for item in staging.iterdir() if item.is_dir()]
            candidate = roots[0] if len(roots) == 1 else staging
            executable = candidate / "Medical Deep Research.exe"
            if not executable.is_file():
                raise ValueError("The Windows update does not contain the application executable")
            return candidate
        if self.context.platform == "darwin":
            apps = list(staging.glob("*.app"))
            if len(apps) != 1:
                raise ValueError("The macOS update does not contain one application bundle")
            verify = await asyncio.create_subprocess_exec(
                "/usr/bin/codesign", "--verify", "--deep", "--strict", str(apps[0])
            )
            if await verify.wait() != 0:
                raise ValueError("The macOS application signature is invalid")
            return apps[0]
        raise ValueError("This platform cannot install application updates")

    def launch_installer(self, release: ReleaseInfo, staged_app: Path) -> Path:
        target = self.context.target
        if target is None:
            raise RuntimeError("No packaged application target was detected")
        if not _directory_is_writable(target.parent):
            raise PermissionError(f"The application directory is not writable: {target.parent}")

        state_dir = self.data_dir / "updates"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / "update-status.json"
        ack_path = state_dir / "startup-ok"
        ack_path.unlink(missing_ok=True)
        state_path.write_text(
            json.dumps({"status": "pending", "version": str(release.version)}),
            encoding="utf-8",
        )
        if self.context.platform == "win32":
            script = state_dir / "apply-update.ps1"
            script.write_text(_windows_installer_script(), encoding="utf-8")
            command = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                str(os.getpid()), str(target), str(staged_app), str(state_path), str(ack_path),
            ]
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            subprocess.Popen(command, close_fds=True, creationflags=flags)
        elif self.context.platform == "darwin":
            script = state_dir / "apply-update.sh"
            script.write_text(_mac_installer_script(), encoding="utf-8")
            script.chmod(0o700)
            subprocess.Popen(
                ["/bin/sh", str(script), str(os.getpid()), str(target), str(staged_app), str(state_path), str(ack_path)],
                close_fds=True,
                start_new_session=True,
            )
        else:
            raise RuntimeError("This platform cannot install application updates")
        return state_path


def read_update_status(data_dir: Path) -> dict[str, Any] | None:
    path = Path(data_dir) / "updates" / "update-status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def acknowledge_updated_startup(data_dir: Path) -> dict[str, Any] | None:
    status = read_update_status(data_dir)
    if status and status.get("status") == "pending":
        ack = Path(data_dir) / "updates" / "startup-ok"
        ack.write_text("ok", encoding="utf-8")
    return status


def clear_update_status(data_dir: Path) -> None:
    path = Path(data_dir) / "updates" / "update-status.json"
    path.unlink(missing_ok=True)


def _checksum_for_asset(manifest: str, asset_name: str) -> str | None:
    for line in manifest.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        if name.lstrip("*") == asset_name and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return digest
    return None


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            candidate = (destination / member.filename).resolve()
            if candidate != root and root not in candidate.parents:
                raise ValueError("The update archive contains an unsafe path")
        bundle.extractall(destination)


def _directory_is_writable(directory: Path) -> bool:
    try:
        fd, probe = tempfile.mkstemp(prefix=".mdr-update-", dir=directory)
        os.close(fd)
        Path(probe).unlink()
        return True
    except OSError:
        return False


def _windows_installer_script() -> str:
    return r'''param([int]$OldPid, [string]$Target, [string]$Staged, [string]$State, [string]$Ack)
$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Backup = "$Target.update-backup"
try {
  Wait-Process -Id $OldPid -ErrorAction SilentlyContinue
  if (Test-Path $Backup) { Remove-Item -Recurse -Force $Backup }
  Move-Item -LiteralPath $Target -Destination $Backup
  Move-Item -LiteralPath $Staged -Destination $Target
  $Exe = Join-Path $Target "Medical Deep Research.exe"
  $Process = Start-Process -FilePath $Exe -PassThru
  $Ready = $false
  for ($i = 0; $i -lt 180; $i++) {
    if (Test-Path $Ack) { $Ready = $true; break }
    if ($Process.HasExited) { break }
    Start-Sleep -Milliseconds 500
    $Process.Refresh()
  }
  if (-not $Ready) { throw "The updated application did not finish starting" }
  [System.IO.File]::WriteAllText($State, '{"status":"succeeded"}', $Utf8NoBom)
  Remove-Item -Recurse -Force $Backup
} catch {
  try {
    if ($null -ne $Process -and -not $Process.HasExited) {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
      Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue
    }
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
    if (Test-Path $Backup) { Move-Item -LiteralPath $Backup -Destination $Target }
    $Failure = @{status="failed"; message=$_.Exception.Message} | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($State, $Failure, $Utf8NoBom)
    $OldExe = Join-Path $Target "Medical Deep Research.exe"
    if (Test-Path $OldExe) { Start-Process -FilePath $OldExe }
  } catch {}
}
'''


def _mac_installer_script() -> str:
    return r'''#!/bin/sh
OLD_PID="$1"
TARGET="$2"
STAGED="$3"
STATE="$4"
ACK="$5"
BACKUP="${TARGET}.update-backup"
while kill -0 "$OLD_PID" 2>/dev/null; do sleep 0.2; done
fail() {
  rm -rf "$TARGET"
  [ -e "$BACKUP" ] && mv "$BACKUP" "$TARGET"
  printf '{"status":"failed","message":"%s"}' "$1" > "$STATE"
  open "$TARGET" >/dev/null 2>&1 || true
  exit 1
}
rm -rf "$BACKUP" || fail "Could not remove the previous backup"
mv "$TARGET" "$BACKUP" || fail "Could not back up the installed application"
mv "$STAGED" "$TARGET" || fail "Could not install the staged application"
open "$TARGET" || fail "Could not launch the updated application"
i=0
while [ "$i" -lt 180 ]; do
  [ -f "$ACK" ] && break
  sleep 0.5
  i=$((i + 1))
done
[ -f "$ACK" ] || fail "The updated application did not finish starting"
printf '{"status":"succeeded"}' > "$STATE"
rm -rf "$BACKUP"
'''
