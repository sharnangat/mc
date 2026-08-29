#!/usr/bin/env bash
# Installs Python + the backend's dependencies and runs the API directly on
# Ubuntu (foreground, with --reload) - for quick manual testing on a server,
# not a production run. Production deploys go through the Jenkins pipeline
# (systemd + nginx, see ../deploy/), which this script does not touch.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Always run this (not gated on `python3 -c "import venv"` succeeding) -
# that module import succeeds even without python3-venv installed, since the
# venv module itself ships in base python3 while the ensurepip bootstrap
# files it needs at creation time live in the separate python3-venv package.
# apt is a fast no-op when everything's already installed.
echo "Ensuring Python, pip, and venv support are installed..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip

VENV_PY=".venv/bin/python"
if [ -f "$VENV_PY" ] && ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    echo "Existing .venv is broken (no pip) - recreating it..."
    rm -rf .venv
fi
if [ ! -f "$VENV_PY" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Always (re)install - pip is a fast no-op when everything's already
# satisfied, and this fixes itself if a previous run created the venv but
# failed partway through before dependencies were installed.
echo "Installing dependencies..."
"$VENV_PY" -m pip install --no-cache-dir --quiet --upgrade pip
"$VENV_PY" -m pip install --no-cache-dir -r requirements.txt

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example - edit it with real values before relying on this."
    cp .env.example .env
fi

echo "Starting API at http://139.59.81.129:8000  (docs at /docs)"
exec "$VENV_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
