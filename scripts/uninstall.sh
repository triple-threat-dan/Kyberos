#!/bin/bash
set -e

SERVICE_FILE="$HOME/.config/systemd/user/kyberos.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KYBEROS_HOME="$REPO_ROOT/.kyberos"

echo "🛑 Initiating Kyberos Removal Protocol..."

# --- 1. The Clean Slate ---

# Stop Service
if systemctl --user is-active --quiet kyberos.service 2>/dev/null; then
    echo "⚙️  Stopping kyberos.service..."
    systemctl --user stop kyberos.service
    systemctl --user disable kyberos.service
fi

if [ -f "$SERVICE_FILE" ]; then
    rm "$SERVICE_FILE"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "✅ Service file removed."
fi

# Prompt for Data Removal
echo "This will permanently delete all memory and configuration in $KYBEROS_HOME."
read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "🚫 Operation cancelled. Configuration preserved."
    exit 0
fi

if [ -d "$KYBEROS_HOME" ]; then
    rm -rf "$KYBEROS_HOME"
    echo "✅ ./.kyberos directory obliterated."
fi

# Uninstall Package
if command -v uv &> /dev/null; then
    echo "📦 Uninstalling kyberos via uv..."
    uv tool uninstall kyberos || echo "⚠️  Could not uninstall via uv tool (maybe it wasn't installed that way)."
else
    echo "ℹ️  'uv' not found, skipping tool uninstall."
fi

echo "👋 Kyberos uninstalled throughout the system."
