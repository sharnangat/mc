#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_PY=".venv/Scripts/python.exe"   # Windows venv layout (this project targets Windows/Git Bash)
if [ ! -f "$VENV_PY" ]; then
    VENV_PY=".venv/bin/python"       # fall back to a POSIX venv layout
fi

if [ ! -f "$VENV_PY" ]; then
    echo "Creating virtual environment with Python 3.13..."
    if command -v py >/dev/null 2>&1; then
        py -3.13 -m venv .venv
    else
        python3.13 -m venv .venv
    fi
    echo "Installing dependencies..."
    "$VENV_PY" -m pip install --no-cache-dir -r requirements.txt
fi

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo "Starting API at http://127.0.0.1:8000  (docs at /docs)"
exec "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
