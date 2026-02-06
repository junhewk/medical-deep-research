#!/bin/bash

# Medical Deep Research - Upgrade Script
# Safely upgrades the database and dependencies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"
DATA_DIR="$WEB_DIR/data"
DB_FILE="$DATA_DIR/medical-deep-research.db"
BACKUP_DIR="$DATA_DIR/backups"

echo "╔══════════════════════════════════════╗"
echo "║  Medical Deep Research - Upgrade     ║"
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
    exit 1
fi

echo "✓ Node.js $(node -v) detected"

# Check if web directory exists
if [ ! -d "$WEB_DIR" ]; then
    echo "❌ Error: web directory not found"
    echo "   Please run this script from the medical-deep-research root"
    exit 1
fi

# Step 1: Backup database if exists
if [ -f "$DB_FILE" ]; then
    echo ""
    echo "📦 Backing up database..."
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/medical-deep-research_$TIMESTAMP.db"
    cp "$DB_FILE" "$BACKUP_FILE"
    echo "   ✓ Backed up to backups/medical-deep-research_$TIMESTAMP.db"

    # Show current table count
    if command -v sqlite3 &> /dev/null; then
        BEFORE_TABLES=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>/dev/null || echo "?")
        echo "   Current tables: $BEFORE_TABLES"
    fi
else
    echo ""
    echo "ℹ️  No existing database found (new installation)"
fi

# Step 2: Pull latest changes if git repo
if [ -d "$SCRIPT_DIR/.git" ]; then
    echo ""
    echo "🔄 Checking for updates..."
    cd "$SCRIPT_DIR"

    # Check for uncommitted changes
    if git diff --quiet 2>/dev/null; then
        # Try to pull latest
        if git pull --ff-only 2>/dev/null; then
            echo "   ✓ Updated to latest version"
        else
            echo "   ℹ️  Could not auto-update (may have local changes)"
        fi
    else
        echo "   ℹ️  Skipping git pull (local changes detected)"
    fi
fi

# Step 3: Update dependencies
cd "$WEB_DIR"
echo ""
echo "📦 Updating dependencies..."
npm install

# Step 4: Run database migration
echo ""
echo "🗄️  Upgrading database schema..."
npm run db:init

# Step 5: Verify database
if [ -f "$DB_FILE" ] && command -v sqlite3 &> /dev/null; then
    echo ""
    echo "🔍 Verifying database..."
    AFTER_TABLES=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>/dev/null)
    AFTER_INDEXES=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='index'" 2>/dev/null)
    echo "   Tables: $AFTER_TABLES"
    echo "   Indexes: $AFTER_INDEXES"

    # List all tables
    echo ""
    echo "   Tables in database:"
    sqlite3 "$DB_FILE" "SELECT '   - ' || name FROM sqlite_master WHERE type='table' ORDER BY name" 2>/dev/null
fi

# Step 6: Clean up old backups (keep last 5)
if [ -d "$BACKUP_DIR" ]; then
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.db 2>/dev/null | wc -l)
    if [ "$BACKUP_COUNT" -gt 5 ]; then
        echo ""
        echo "🧹 Cleaning old backups (keeping last 5)..."
        ls -1t "$BACKUP_DIR"/*.db | tail -n +6 | xargs rm -f
    fi
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  ✅ Upgrade complete!                ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Run './start-web.sh' to start the application."
echo ""
