#!/usr/bin/env bash
# Standalone frontend deployment - run this directly on the target server, no
# Jenkins required. Installs Node if needed, builds the Angular app in
# production mode, and installs/reloads an nginx site that serves it and
# proxies /api/ to the backend on 127.0.0.1:8000. Companion to
# standalone-deploy.sh (the backend equivalent) - run that one too (either
# order is fine, this doesn't depend on the backend being up yet).
#
# Unlike deploy/nginx/mc.conf (the Jenkins-driven template, which serves
# from /opt/mc/current/frontend-dist - a release symlink Jenkins manages),
# this points nginx directly at this checkout's own build output, matching
# standalone-deploy.sh's "run in place" approach.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
BUILD_DIR="$FRONTEND_DIR/dist/frontend/browser"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root (it installs nginx and a site config)." >&2
    exit 1
fi

echo "==> Ensuring nginx is installed"
apt-get update -qq
apt-get install -y -qq nginx

if ! command -v node >/dev/null 2>&1; then
    echo "==> Installing Node.js (NodeSource, 22.x)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y -qq nodejs
fi

echo "==> Installing frontend dependencies"
cd "$FRONTEND_DIR"
npm ci

echo "==> Building for production"
npx ng build --configuration production

if [ ! -f "$BUILD_DIR/index.html" ]; then
    echo "ERROR: build did not produce $BUILD_DIR/index.html" >&2
    exit 1
fi

echo "==> Installing nginx site config"
tee /etc/nginx/sites-available/mc.conf > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    root $BUILD_DIR;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

ln -sf /etc/nginx/sites-available/mc.conf /etc/nginx/sites-enabled/mc.conf
rm -f /etc/nginx/sites-enabled/default

echo "==> Reloading nginx"
nginx -t
systemctl enable nginx >/dev/null
systemctl reload nginx 2>/dev/null || systemctl restart nginx

echo "==> Checking the frontend is served"
if ! curl -sf http://127.0.0.1/ >/dev/null; then
    echo "ERROR: nginx did not serve the frontend. Check: journalctl -u nginx -n 50 --no-pager" >&2
    exit 1
fi

echo "==> Frontend is up: http://$(curl -s -4 ifconfig.me 2>/dev/null || echo '<this-server-ip>')/"
echo "    (API calls proxy through /api/ to the backend - deploy it separately with standalone-deploy.sh if you haven't)"
