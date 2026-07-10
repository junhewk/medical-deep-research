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
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#       NOTARYTOOL_PROFILE=medical-deep-research \
#       ./scripts/build-macos.sh --dmg --notarize
#
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="Medical Deep Research"
export BUNDLE_ID="${BUNDLE_ID:-com.junhewk.medical-deep-research}"
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:-}"
ENTITLEMENTS_FILE="${ENTITLEMENTS_FILE:-scripts/macos-entitlements.plist}"
NOTARYTOOL_PROFILE="${NOTARYTOOL_PROFILE:-}"
APPLE_ID="${APPLE_ID:-}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
APPLE_APP_PASSWORD="${APPLE_APP_PASSWORD:-}"
CREATE_DMG=false
NOTARIZE=false
DMG_NAME=""

usage() {
    cat <<EOF
Usage: ./scripts/build-macos.sh [--dmg] [--notarize]

Environment:
  BUNDLE_ID            App bundle identifier. Default: ${BUNDLE_ID}
  CODESIGN_IDENTITY    Developer ID Application identity for distribution.
  ENTITLEMENTS_FILE    Entitlements plist. Default: ${ENTITLEMENTS_FILE}
  NOTARYTOOL_PROFILE   notarytool keychain profile name.

Alternative notarization credentials:
  APPLE_ID             Apple ID email.
  APPLE_TEAM_ID        Apple Developer Team ID.
  APPLE_APP_PASSWORD   App-specific password.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dmg)
            CREATE_DMG=true
            ;;
        --notarize)
            NOTARIZE=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [[ "${NOTARIZE}" == true && -z "${CODESIGN_IDENTITY}" ]]; then
    echo "Notarization requires CODESIGN_IDENTITY with a Developer ID Application certificate." >&2
    exit 2
fi

notarytool_auth_args=()
if [[ -n "${NOTARYTOOL_PROFILE}" ]]; then
    notarytool_auth_args=(--keychain-profile "${NOTARYTOOL_PROFILE}")
elif [[ -n "${APPLE_ID}" || -n "${APPLE_TEAM_ID}" || -n "${APPLE_APP_PASSWORD}" ]]; then
    if [[ -z "${APPLE_ID}" || -z "${APPLE_TEAM_ID}" || -z "${APPLE_APP_PASSWORD}" ]]; then
        echo "APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD must all be set for direct notarization auth." >&2
        exit 2
    fi
    notarytool_auth_args=(--apple-id "${APPLE_ID}" --team-id "${APPLE_TEAM_ID}" --password "${APPLE_APP_PASSWORD}")
fi

if [[ "${NOTARIZE}" == true && ${#notarytool_auth_args[@]} -eq 0 ]]; then
    echo "Notarization requires NOTARYTOOL_PROFILE or APPLE_ID/APPLE_TEAM_ID/APPLE_APP_PASSWORD." >&2
    exit 2
fi

sign_code_path() {
    local path="$1"
    local entitlements_file="${2:-}"
    if [[ -n "${CODESIGN_IDENTITY}" ]]; then
        if [[ -n "${entitlements_file}" ]]; then
            codesign --force --options runtime --timestamp \
                --entitlements "${entitlements_file}" \
                --sign "${CODESIGN_IDENTITY}" \
                "${path}"
        else
            codesign --force --options runtime --timestamp \
                --sign "${CODESIGN_IDENTITY}" \
                "${path}"
        fi
    else
        codesign --force --sign - "${path}"
    fi
}

sign_flat_path() {
    local path="$1"
    if [[ -n "${CODESIGN_IDENTITY}" ]]; then
        echo "--- Developer ID signing: ${path} ---"
    else
        echo "--- Ad-hoc signing: ${path} ---"
    fi
    sign_code_path "${path}"
    codesign --verify --verbose=2 "${path}"
}

is_macho_file() {
    local path="$1"
    file -b "${path}" | grep -q 'Mach-O'
}

sign_app_bundle() {
    local app_path="$1"
    if [[ -n "${CODESIGN_IDENTITY}" ]]; then
        echo "--- Developer ID signing app bundle: ${app_path} ---"
    else
        echo "--- Ad-hoc signing app bundle: ${app_path} ---"
    fi

    echo "--- Signing nested Mach-O files ---"
    while IFS= read -r -d '' path; do
        case "${path}" in
            */_CodeSignature/*) continue ;;
        esac
        if is_macho_file "${path}"; then
            sign_code_path "${path}"
        fi
    done < <(find "${app_path}/Contents" -type f -print0)

    echo "--- Signing nested code bundles ---"
    find "${app_path}/Contents" -type d \( \
        -name '*.app' -o \
        -name '*.appex' -o \
        -name '*.framework' -o \
        -name '*.xpc' \
    \) \
        | awk '{ print length($0) " " $0 }' \
        | sort -rn \
        | cut -d' ' -f2- \
        | while IFS= read -r path; do
            sign_code_path "${path}"
        done

    echo "--- Signing outer app bundle ---"
    sign_code_path "${app_path}" "${ENTITLEMENTS_FILE}"
    codesign --verify --deep --strict --verbose=2 "${app_path}"
}

sign_path() {
    local path="$1"
    if [[ "${path}" == *.app ]]; then
        sign_app_bundle "${path}"
    else
        sign_flat_path "${path}"
    fi
}

submit_notarization() {
    local path="$1"
    echo "--- Notarizing: ${path} ---"
    xcrun notarytool submit "${path}" "${notarytool_auth_args[@]}" --wait
}

staple_path() {
    local path="$1"
    echo "--- Stapling notarization ticket: ${path} ---"
    xcrun stapler staple "${path}"
    xcrun stapler validate "${path}"
}

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
echo "Bundle ID: ${BUNDLE_ID}"

# ---------------------------------------------------------------------------
# 2. Run PyInstaller (uses .spec file for full config including data filtering)
# ---------------------------------------------------------------------------
echo "--- Running PyInstaller ---"
uv run python -m PyInstaller \
    --noconfirm \
    --clean \
    "Medical Deep Research.spec"

# ---------------------------------------------------------------------------
# 3. Sign
# ---------------------------------------------------------------------------
sign_path "dist/${APP_NAME}.app"

if [[ "${NOTARIZE}" == true ]]; then
    APP_ZIP="dist/${APP_NAME// /-}-${VERSION}-macOS-app.zip"
    echo "--- Creating notarization ZIP: ${APP_ZIP} ---"
    ditto -c -k --keepParent "dist/${APP_NAME}.app" "${APP_ZIP}"
    submit_notarization "${APP_ZIP}"
    staple_path "dist/${APP_NAME}.app"
    spctl --assess --type execute --verbose=4 "dist/${APP_NAME}.app"
fi

echo "--- Build complete ---"
echo "App bundle: dist/${APP_NAME}.app"
ls -lh "dist/${APP_NAME}.app/Contents/MacOS/${APP_NAME}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 4. Optionally create a DMG
# ---------------------------------------------------------------------------
if [[ "${CREATE_DMG}" == true ]]; then
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
    sign_path "dist/${DMG_NAME}"
    if [[ "${NOTARIZE}" == true ]]; then
        submit_notarization "dist/${DMG_NAME}"
        staple_path "dist/${DMG_NAME}"
        spctl --assess --type open --verbose=4 "dist/${DMG_NAME}"
    fi
    echo "DMG: dist/${DMG_NAME}"
fi

echo "=== Done ==="
