#!/usr/bin/env bash
# Safe startup wrapper for Balebot on Ubuntu 24.04 VPS (no Docker).
# Run this script inside a tmux/screen session so the bot survives SSH disconnect.
#
# Usage:
#   chmod +x run.sh
#   ./run.sh

set -euo pipefail

# Hard resource guardrails so the bot cannot exhaust the VPS and lock out SSH.
# Adjust these to fit your server size; they are intentionally generous for a
# media downloader bot.
ulimit -n 4096          # max open files
ulimit -u 512           # max user processes
ulimit -v 4194304       # max virtual memory (KB) ~ 4 GB
ulimit -m 4194304       # max resident memory (KB) ~ 4 GB
ulimit -f 20971520      # max file size (KB) ~ 20 GB

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Load environment variables from .env so shell checks (e.g. YTDLP_POT_ENABLED) work.
if [[ -f ".env" ]]; then
    # shellcheck source=/dev/null
    set -a
    source .env
    set +a
fi

# Ensure a virtual environment exists
if [[ ! -d "venv" ]]; then
    echo "[run.sh] Virtual environment not found. Creating venv..."
    python3 -m venv venv
fi

# Install/upgrade dependencies
source venv/bin/activate
pip install -q -r requirements.txt

# Ensure runtime directories exist
mkdir -p logs cache

# Clone the PO-token provider if it is missing and PO tokens are enabled.
if [[ "${YTDLP_POT_ENABLED:-false}" == "true" ]] && [[ ! -d "bgutil-provider" ]]; then
    if command -v git >/dev/null 2>&1; then
        echo "[run.sh] PO-token provider missing. Cloning bgutil-ytdlp-pot-provider..."
        git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git bgutil-provider
    else
        echo "[run.sh] WARNING: git not found. Cannot clone PO-token provider automatically."
    fi
fi

# Node.js check (required for the PO-token provider)
if ! command -v node >/dev/null 2>&1; then
    echo "[run.sh] WARNING: Node.js not found. YouTube PO-token support will be disabled."
    echo "[run.sh] To enable, install Node.js >= 20: sudo apt-get install -y nodejs"
else
    NODE_MAJOR=$(node -p 'process.version.match(/^v(\d+)/)[1]')
    if [ "$NODE_MAJOR" -lt 20 ]; then
        echo "[run.sh] WARNING: Node.js $NODE_MAJOR found; provider requires Node >= 20."
    else
        echo "[run.sh] Node.js $(node -p 'process.version') detected."
    fi
fi

# Warn if disk is getting full
python3 - <<'PY'
import shutil, sys
usage = shutil.disk_usage('.')
used_pct = (usage.used / usage.total) * 100
free_gb = usage.free / (1024 ** 3)
print(f"[run.sh] Disk usage: {used_pct:.1f}% used, {free_gb:.2f} GB free.")
if used_pct > 90:
    print("[run.sh] WARNING: disk usage is above 90%. Clean up before heavy downloads.", file=sys.stderr)
PY

# Start the bot
exec python main.py
