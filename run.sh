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
