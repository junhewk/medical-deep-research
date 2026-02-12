#!/bin/bash

# Medical Deep Research v2.0 - Startup Script
# TypeScript-only stack (Next.js + Drizzle ORM + SQLite)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"

echo "╔══════════════════════════════════════╗"
echo "║  Medical Deep Research v2.0          ║"
echo "║  Evidence-Based Research Assistant   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Error: Node.js is not installed"
    echo "   Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Error: Node.js 18+ is required (found v$NODE_VERSION)"
    echo "   Please upgrade Node.js from https://nodejs.org/"
    exit 1
fi

echo "✓ Node.js $(node -v) detected"

# Check if web directory exists
if [ ! -d "$WEB_DIR" ]; then
    echo "❌ Error: web directory not found"
    echo "   Please run this script from the medical-deep-research root"
    exit 1
fi

cd "$WEB_DIR"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo ""
    echo "📦 Installing dependencies..."
    npm install
fi

# Create data directory
mkdir -p "$WEB_DIR/data"

# Initialize/upgrade database schema (safe for both new and existing databases)
echo ""
echo "🗄️  Initializing database..."
npx drizzle-kit push

# Copy .env if it doesn't exist
if [ ! -f "$WEB_DIR/.env" ] && [ -f "$WEB_DIR/.env.example" ]; then
    cp "$WEB_DIR/.env.example" "$WEB_DIR/.env"
    echo "📝 Created .env from .env.example"
fi

echo ""
echo "🚀 Starting Medical Deep Research..."
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Web UI: http://localhost:3000       ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "📌 First time? Configure API keys at:"
echo "   http://localhost:3000/settings/api-keys"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Function to open browser based on OS
open_browser() {
    local url="http://localhost:3000"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open "$url"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v xdg-open &> /dev/null; then
            xdg-open "$url"
        elif command -v gnome-open &> /dev/null; then
            gnome-open "$url"
        fi
    elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]]; then
        start "$url"
    fi
}

# Wait for server to be ready and open browser in background
(
    echo "⏳ Waiting for server to be ready..."
    max_attempts=30
    attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:3000 > /dev/null 2>&1; then
            echo "✓ Server is ready!"
            open_browser
            exit 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    echo "⚠️  Timeout waiting for server. Please open http://localhost:3000 manually."
) &

# Start Next.js development server
npm run dev
