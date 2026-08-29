#!/usr/bin/env bash
# Standalone backend deployment - run this directly on the target server, no
# Jenkins required. Sets up the venv, installs/enables a systemd service, and
# starts it via systemctl. For the Jenkins-driven release/rollback pipeline
# instead (separate deploy user, /opt/mc layout, DB migration, auto-rollback
# on failed health check), see remote-deploy.sh - that's the hardened,
# production path; this is the quick manual alternative.
#
# Runs the service as root, deliberately - unlike remote-deploy.sh's setup
# (a dedicated "mc" user under /opt/mc), this script assumes the repo is
# checked out somewhere only root can reach (e.g. /root/mc), so a
# least-privilege service user would be unable to even read the app files.
#
# Prerequisites (not done by this script):
#   - backend/.env must already exist with real values
#     (copy backend/.env.production.example and fill it in)
#   - The database schema must already exist - see db/create-schema.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root (it installs a systemd service)." >&2
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "ERROR: $BACKEND_DIR/.env is missing." >&2
    echo "        cp backend/.env.production.example backend/.env, then fill in real values." >&2
    exit 1
fi

echo "==> Ensuring Python/venv support is installed"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip

VENV_PY="$BACKEND_DIR/.venv/bin/python"
if [ -f "$VENV_PY" ] && ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    echo "==> Existing .venv is broken (no pip) - recreating it"
    rm -rf "$BACKEND_DIR/.venv"
fi
if [ ! -f "$VENV_PY" ]; then
    echo "==> Creating virtual environment"
    python3 -m venv "$BACKEND_DIR/.venv"
fi

echo "==> Installing dependencies"
"$VENV_PY" -m pip install --no-cache-dir --quiet --upgrade pip
"$VENV_PY" -m pip install --no-cache-dir -r "$BACKEND_DIR/requirements.txt"

echo "==> Installing systemd unit"
tee /etc/systemd/system/mc-backend.service > /dev/null <<EOF
[Unit]
Description=Metallurgical Consultation API (FastAPI/uvicorn)
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
# --workers 1: a small droplet (e.g. 1GB RAM) can't comfortably run two full
# copies of this app (it loads sentence-transformers into memory).
ExecStart=$BACKEND_DIR/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting the service"
systemctl daemon-reload
systemctl enable mc-backend >/dev/null
systemctl restart mc-backend

echo "==> Health-checking"
HEALTHY=0
for _ in $(seq 1 15); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null; then
        HEALTHY=1
        break
    fi
    sleep 2
done

if [ "$HEALTHY" -ne 1 ]; then
    echo "ERROR: backend did not become healthy. Check: journalctl -u mc-backend -n 50 --no-pager" >&2
    exit 1
fi

echo "==> Backend is up: http://127.0.0.1:8000/health"
echo "    Logs: journalctl -u mc-backend -f"
echo "    Status: systemctl status mc-backend"
