#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================================"
echo "  Starting IMNID Hub..."
echo "  Open your browser to: http://localhost:8085"
echo "================================================================"

if [ -f "./imnid-hub" ]; then
    ./imnid-hub
elif command -v python3 &>/dev/null; then
    python3 run_hub.py
else
    echo "Python 3 or bundled imnid-hub binary is required to start IMNID Hub."
    exit 1
fi

