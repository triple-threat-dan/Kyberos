 #!/bin/bash
set -e

# --- Configuration ---
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KYBEROS_HOME="$REPO_ROOT/.kyberos"
TEMPLATE_DIR="$REPO_ROOT/src/kyberos/templates"
SERVICE_FILE="$HOME/.config/systemd/user/kyberos.service"

echo "🔮 Initiating Kyberos First Contact Sequence..."

# --- 1. Pre-flight Checks ---

# Check Python version >= 3.12
if ! command -v python3 &> /dev/null; then
  echo "❌ Error: python3 is not installed."
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED_VERSION="3.12"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Error: Python 3.12+ is required. Found $PYTHON_VERSION."
    exit 1
fi
echo "✅ Python $PYTHON_VERSION detected."

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "⚠️  'uv' not found. Installing via Astral's script..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Ensure uv is in path for this session if just installed
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "✅ 'uv' is installed."
fi

# --- 2. The Setup ---

echo "📂 Setting up ./kyberos..."
mkdir -p "$KYBEROS_HOME"

# Copy templates without overwriting existing config
if [ -d "$TEMPLATE_DIR" ]; then
    echo "📜 Copying Default Knowledge Pack..."
    # rsync is safer but cp -n is standard. We'll use a loop to be safe and interactive-ish logic implies soft skip.
    # We want to copy contents of .kyberos/ to ./kyberos/
    # Using cp -rn to not overwrite
    cp -rn "$TEMPLATE_DIR/"* "$KYBEROS_HOME/" || true
    echo "✅ Templates copied (existing files preserved)."
else
    echo "⚠️  Warning: Template directory $TEMPLATE_DIR not found within repo."
fi

# Permissions
echo "🔒 Securing Archive..."
if [ -f "$KYBEROS_HOME/kyberos.json" ]; then
    chmod 600 "$KYBEROS_HOME/kyberos.json"
fi
if [ -f "$KYBEROS_HOME/SOUL.md" ]; then
    chmod 600 "$KYBEROS_HOME/SOUL.md"
fi
echo "✅ Permissions applied."

# --- 2.5 Package Installation ---

echo "📦 Installing Kyberos binary..."
if [ -f "$REPO_ROOT/pyproject.toml" ]; then
    uv tool install "$REPO_ROOT" --force
    echo "✅ Kyberos installed globally via uv."
    
    # Ensure local bin is in PATH for this session so we can find 'kyberos' immediately
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "⚠️  pyproject.toml not found. Skipping global tool install."
fi

# --- 3. System Integration ---

# Check if running in a systemd environment (WSL2 might not have it active)
if pidof systemd >/dev/null 2>&1 || pidof systemd-init >/dev/null 2>&1; then
    echo "⚙️  Configuring Systemd Service..."
    mkdir -p "$(dirname "$SERVICE_FILE")"

    # Assume 'uv tool install' has been or will be run, but for development/source installation,
    # we point to the venv python in the repository or rely on 'kyberos' being in PATH.
    # Since install.sh is typically run from the repo:
    # Option A: Run from source venv (common for devs)
    # Option B: Run installed tool.
    # The requirement says "Should point to the `kyberos start` entry point (assumes `uv tool install .` or similar setup has occurred...)"
    
    # We will locate `kyberos` path.
    KYBEROS_BIN=$(which kyberos || echo "$HOME/.local/bin/kyberos ")
    
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Kyberos "The Recursive Learning Agent" Daemon
After=network.target

[Service]
ExecStart=$KYBEROS_BIN start
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable kyberos.service
    systemctl --user start kyberos.service
    echo "✅ systemd service started and enabled."
else
    echo "⚠️  Systemd not detected (common in some WSL configurations)."
    echo "   You may need to run 'kyberos start' manually or configure your specific init system."
fi

echo "✨ Kyberos installation complete. The Agent awaits."
