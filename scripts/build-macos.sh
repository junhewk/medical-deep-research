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
VERSION=$(python -c "
import tomllib, pathlib
p = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(p['project']['version'])
")
echo "=== Building ${APP_NAME} v${VERSION} for macOS ==="

# ---------------------------------------------------------------------------
# 1. Sync dependencies (all extras for a full-featured build)
# ---------------------------------------------------------------------------
echo "--- Installing dependencies ---"
uv sync --all-extras
uv pip install pyinstaller pywebview

# ---------------------------------------------------------------------------
# 2. Collect paths for --add-data
# ---------------------------------------------------------------------------
NICEGUI_DIR=$(python -c "import nicegui, pathlib; print(pathlib.Path(nicegui.__file__).parent)")
SRC_DIR="src/medical_deep_research"
SEP=":"  # macOS/Linux path separator for PyInstaller

# ---------------------------------------------------------------------------
# 3. Run PyInstaller via nicegui-pack (or directly)
# ---------------------------------------------------------------------------
echo "--- Running PyInstaller ---"
python -m PyInstaller \
    --name "${APP_NAME}" \
    --windowed \
    --onedir \
    --noconfirm \
    --clean \
    --osx-bundle-identifier "${BUNDLE_ID}" \
    --add-data "${NICEGUI_DIR}${SEP}nicegui" \
    --add-data "${SRC_DIR}${SEP}medical_deep_research" \
    --hidden-import medical_deep_research \
    --hidden-import medical_deep_research.main \
    --hidden-import medical_deep_research.ui \
    --hidden-import medical_deep_research.config \
    --hidden-import medical_deep_research.models \
    --hidden-import medical_deep_research.persistence \
    --hidden-import medical_deep_research.service \
    --hidden-import medical_deep_research.runtime \
    --hidden-import medical_deep_research.agentic_tools \
    --hidden-import medical_deep_research.tools \
    --hidden-import medical_deep_research.research \
    --hidden-import medical_deep_research.research.planning \
    --hidden-import medical_deep_research.research.search \
    --hidden-import medical_deep_research.research.scoring \
    --hidden-import medical_deep_research.research.verification \
    --hidden-import medical_deep_research.research.reporting \
    --hidden-import medical_deep_research.research.models \
    --hidden-import medical_deep_research.mcp \
    --hidden-import medical_deep_research.mcp.servers \
    --hidden-import pydantic_settings \
    --hidden-import sqlmodel \
    --hidden-import nicegui \
    --hidden-import httpx \
    --hidden-import anyio \
    --collect-all nicegui \
    --collect-submodules medical_deep_research \
    scripts/desktop_entry.py

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
