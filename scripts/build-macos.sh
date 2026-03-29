#!/usr/bin/env bash
#
# Build Medical Deep Research as a macOS .app bundle.
#
# Prerequisites:
#   - Python 3.12+
#   - uv (https://docs.astral.sh/uv/)
#   - Java 11+ (for opendataloader-pdf)
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
# 1. Sync dependencies (all extras for a full-featured build)
# ---------------------------------------------------------------------------
echo "--- Installing dependencies ---"
uv sync --all-extras
uv pip install pyinstaller pywebview

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
# 3. Strip unused NiceGUI element bundles to reduce size and startup time
# ---------------------------------------------------------------------------
echo "--- Stripping unused NiceGUI element JS bundles ---"
for elem in plotly echart mermaid codemirror json_editor aggrid scene leaflet xterm joystick; do
    # Remove heavy JS dist bundles only — keep .py and __init__.py so nicegui imports work
    rm -rf "dist/${APP_NAME}.app/Contents/Resources/nicegui/elements/${elem}/dist"
    rm -rf "dist/${APP_NAME}.app/Contents/Resources/nicegui/elements/${elem}/src"
done
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
    echo "DMG: dist/${DMG_NAME}"
fi

echo "=== Done ==="
