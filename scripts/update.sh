#!/bin/bash
set -e

# --- Configuration ---
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$REPO_ROOT/.kyberos/kyberos.pid"
WAS_RUNNING=false

echo "🔮 Initiating Kyberos Update Sequence..."

# --- 1. Check if Kyberos is Running ---

if [ -f "$PID_FILE" ]; then
    KYBEROS_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$KYBEROS_PID" ] && [ "$KYBEROS_PID" -eq "$KYBEROS_PID" ] 2>/dev/null; then
        if kill -0 "$KYBEROS_PID" 2>/dev/null; then
            echo "ℹ️  Kyberos is currently running (PID: $KYBEROS_PID)."
            WAS_RUNNING=true
            
            echo "🛑 Stopping Kyberos..."
            if kill "$KYBEROS_PID" 2>/dev/null; then
                echo "✅ Kyberos stopped."
            else
                echo "⚠️  Failed to stop Kyberos gracefully."
            fi
            
            # Give it a moment to fully shutdown
            sleep 2
        else
            echo "ℹ️  PID file exists but process is not running."
        fi
    fi
    # Clean up the PID file
    rm -f "$PID_FILE"
fi

# --- 2. Git Pull ---

echo "⬇️  Pulling latest code from git..."
cd "$REPO_ROOT"

if ! command -v git &> /dev/null; then
    echo "❌ Error: git is not installed."
    exit 1
fi

GIT_OUTPUT=$(git pull 2>&1) || {
    echo "❌ Error: Git pull failed: $GIT_OUTPUT"
    exit 1
}

if echo "$GIT_OUTPUT" | grep -q "Already up to date"; then
    echo "✅ Already up to date."
else
    echo "✅ Repository updated:"
    echo "$GIT_OUTPUT"
fi

# --- 3. Reinstall Package ---

echo "📦 Reinstalling Kyberos package..."

if [ -f "$REPO_ROOT/pyproject.toml" ]; then
    uv tool install "$REPO_ROOT" --force
    echo "✅ Kyberos reinstalled successfully."
else
    echo "⚠️  Warning: pyproject.toml not found. Skipping package reinstall."
fi

# --- 4. Restart if it was running ---

if [ "$WAS_RUNNING" = true ]; then
    echo "🚀 Restarting Kyberos..."
    
    KYBEROS_BIN=$(which kyberos 2>/dev/null || echo "$HOME/.local/bin/kyberos ")
    
    if [ -x "$KYBEROS_BIN" ]; then
        # Start kyberos in background so it doesn't block this script
        nohup "$KYBEROS_BIN" start > /dev/null 2>&1 &
        echo "✅ Kyberos restarted."
    else
        echo "⚠️  Warning: Could not find kyberos executable. Please start manually with: kyberos start"
    fi
fi

echo "✨ Kyberos update complete."

if [ "$WAS_RUNNING" = false ]; then
    echo "   Run 'kyberos start' to begin."
fi