#!/usr/bin/env bash
#
# Build Medical Deep Research as a macOS .app bundle.
#
# Prerequisites:
#   - Python 3.12+
#   - uv (https://docs.astral.sh/uv/)
#
# Usage:
#   ./scripts/build-macos.sh            # build .app in dist/
#   ./scripts/build-macos.sh --dmg      # also create a .dmg installer
#
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="Medical Deep Research"
BUNDLE_ID="com.junhewk.medical-deep-research"

# ---------------------------------------------------------------------------
# 1. Sync dependencies (active provider extras, excluding legacy Claude SDK)
# ---------------------------------------------------------------------------
echo "--- Installing dependencies ---"
uv sync \
    --extra anthropic \
    --extra openai \
    --extra codex \
    --extra deepseek \
    --extra google \
    --extra langchain \
    --extra pdf
uv pip install pyinstaller

# Use uv run for all Python commands so they use the venv
VERSION=$(uv run python -c "
import tomllib, pathlib
p = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(p['project']['version'])
")
echo "=== Building ${APP_NAME} v${VERSION} for macOS ==="

# ---------------------------------------------------------------------------
# 2. Run PyInstaller (uses .spec file for full config including data filtering)
# ---------------------------------------------------------------------------
echo "--- Running PyInstaller ---"
uv run python -m PyInstaller \
    --noconfirm \
    --clean \
    "Medical Deep Research.spec"

# ---------------------------------------------------------------------------
# 3. Ad-hoc sign
# ---------------------------------------------------------------------------
echo "--- Ad-hoc signing app bundle ---"
codesign --force --deep --sign - "dist/${APP_NAME}.app"
codesign --verify --deep --strict --verbose=2 "dist/${APP_NAME}.app"

echo "--- Build complete ---"
echo "App bundle: dist/${APP_NAME}.app"
ls -lh "dist/${APP_NAME}.app/Contents/MacOS/${APP_NAME}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 4. Optionally create a DMG
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--dmg" ]]; then
    DMG_NAME="${APP_NAME// /-}-${VERSION}-macOS.dmg"
    echo "--- Creating DMG: ${DMG_NAME} ---"
    if command -v create-dmg &>/dev/null; then
        create-dmg \
            --volname "${APP_NAME}" \
            --window-size 600 400 \
            --app-drop-link 400 200 \
            --icon "${APP_NAME}.app" 200 200 \
            "dist/${DMG_NAME}" \
            "dist/${APP_NAME}.app"
    else
        # Fallback: simple hdiutil
        hdiutil create -volname "${APP_NAME}" \
            -srcfolder "dist/${APP_NAME}.app" \
            -ov -format UDZO \
            "dist/${DMG_NAME}"
    fi
    echo "--- Ad-hoc signing DMG ---"
    codesign --force --sign - "dist/${DMG_NAME}"
    codesign --verify --verbose=2 "dist/${DMG_NAME}"
    echo "DMG: dist/${DMG_NAME}"
fi

echo "=== Done ==="
