#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WEB_DIR="$PROJECT_ROOT/web"
TAURI_DIR="$PROJECT_ROOT/src-tauri"

echo "=== Medical Deep Research — Desktop Build ==="
echo ""

# Detect platform
ARCH=$(uname -m)
OS=$(uname -s)

case "$OS-$ARCH" in
  Darwin-arm64)  TARGET_TRIPLE="aarch64-apple-darwin" ;;
  Darwin-x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
  Linux-x86_64)  TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64) TARGET_TRIPLE="aarch64-unknown-linux-gnu" ;;
  *) echo "Unsupported platform: $OS-$ARCH"; exit 1 ;;
esac

echo "Platform: $OS $ARCH ($TARGET_TRIPLE)"
echo ""

# --- Step 1: Ensure Bun sidecar binary exists ---
BUN_VERSION="1.3.11"
BUN_SIDECAR="$TAURI_DIR/binaries/bun-$TARGET_TRIPLE"

download_bun() {
  local triple="$1" dest="$2"
  case "$triple" in
    aarch64-apple-darwin) local suffix="darwin-aarch64" ;;
    x86_64-apple-darwin)  local suffix="darwin-x64" ;;
    x86_64-unknown-linux-gnu)  local suffix="linux-x64" ;;
    aarch64-unknown-linux-gnu) local suffix="linux-aarch64" ;;
  esac
  local url="https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-${suffix}.zip"
  echo "Downloading Bun $BUN_VERSION for $triple"
  local dl_tmp
  dl_tmp=$(mktemp -d)
  curl -fsSL "$url" -o "$dl_tmp/bun.zip"
  unzip -q "$dl_tmp/bun.zip" -d "$dl_tmp"
  cp "$dl_tmp"/bun-*/bun "$dest"
  chmod +x "$dest"
  rm -rf "$dl_tmp"
}

if [ ! -f "$BUN_SIDECAR" ]; then
  mkdir -p "$TAURI_DIR/binaries"
  download_bun "$TARGET_TRIPLE" "$BUN_SIDECAR"
  echo ""
fi

# For macOS universal builds, ensure both arch binaries exist
if [ "$OS" = "Darwin" ] && [ "${UNIVERSAL:-}" = "1" ]; then
  for TRIPLE in "aarch64-apple-darwin" "x86_64-apple-darwin"; do
    SIDECAR="$TAURI_DIR/binaries/bun-$TRIPLE"
    if [ ! -f "$SIDECAR" ]; then
      download_bun "$TRIPLE" "$SIDECAR"
    fi
  done
fi

# --- Step 1: Build Next.js standalone ---
echo "=== Step 1: Building Next.js standalone ==="
cd "$WEB_DIR"
npm run build
echo ""

# --- Step 2: Copy standalone output to Tauri resources ---
echo "=== Step 2: Copying standalone output to Tauri resources ==="
STANDALONE_DEST="$TAURI_DIR/resources/standalone"
rm -rf "$STANDALONE_DEST"
cp -r "$WEB_DIR/.next/standalone" "$STANDALONE_DEST"

# Copy static assets into standalone (Next.js standalone doesn't include these)
mkdir -p "$STANDALONE_DEST/.next/static"
cp -r "$WEB_DIR/.next/static/"* "$STANDALONE_DEST/.next/static/"

# Copy public dir if it exists
if [ -d "$WEB_DIR/public" ]; then
  cp -r "$WEB_DIR/public" "$STANDALONE_DEST/public"
fi

echo "Standalone server copied to $STANDALONE_DEST"
STANDALONE_SIZE=$(du -sh "$STANDALONE_DEST" | cut -f1)
echo "Size: $STANDALONE_SIZE"
echo ""

# --- Step 3: Build Tauri app ---
echo "=== Step 3: Building Tauri desktop app ==="
cd "$PROJECT_ROOT"

if [ "$OS" = "Darwin" ] && [ "${UNIVERSAL:-}" = "1" ]; then
  echo "Building universal macOS binary..."
  cargo tauri build --target universal-apple-darwin
elif [ "$OS" = "Darwin" ]; then
  cargo tauri build --bundles dmg
else
  cargo tauri build
fi

echo ""
echo "=== Build complete ==="

# Show output location
if [ "$OS" = "Darwin" ]; then
  echo "DMG: $TAURI_DIR/target/release/bundle/dmg/"
  ls -la "$TAURI_DIR/target/release/bundle/dmg/"*.dmg 2>/dev/null || echo "(no .dmg found — check target/release/bundle/)"
else
  echo "Output: $TAURI_DIR/target/release/bundle/"
  ls "$TAURI_DIR/target/release/bundle/" 2>/dev/null
fi
