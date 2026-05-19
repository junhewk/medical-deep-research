<#
Build Medical Deep Research as a Windows PyInstaller onedir app.

Prerequisites:
  - Python 3.12+
  - uv (https://docs.astral.sh/uv/)

Usage:
  powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1 -Zip
#>

param(
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$AppName = "Medical Deep Research"

Write-Host "--- Installing dependencies ---"
uv sync --all-extras
uv pip install pyinstaller

$Version = uv run python -c "import tomllib, pathlib; p = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(p['project']['version'])"
Write-Host "=== Building $AppName v$Version for Windows ==="

Write-Host "--- Running PyInstaller ---"
uv run python -m PyInstaller --noconfirm --clean "Medical Deep Research.spec"

$ExePath = "dist\$AppName\$AppName.exe"
Write-Host "--- Build complete ---"
Write-Host "EXE: $ExePath"
if (Test-Path $ExePath) {
    Get-Item $ExePath | Format-List FullName, Length
}

if ($Zip) {
    $ZipName = "Medical-Deep-Research-$Version-Windows.zip"
    $ZipPath = "dist\$ZipName"
    Write-Host "--- Creating ZIP: $ZipPath ---"
    Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath
    Compress-Archive -Path "dist\$AppName\*" -DestinationPath $ZipPath
    Write-Host "ZIP: $ZipPath"
}

Write-Host "=== Done ==="
