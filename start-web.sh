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

# Run database migrations if needed
if [ ! -f "$WEB_DIR/data/medical-deep-research.db" ]; then
    echo ""
    echo "🗄️  Setting up database..."
    npm run db:generate 2>/dev/null || true
    npm run db:migrate 2>/dev/null || true
fi

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

# Start Next.js development server
npm run dev
