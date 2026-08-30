#!/usr/bin/env bash
# Standalone frontend deployment - run this directly on the target server, no
# Jenkins required. Installs Node if needed, builds the Angular app in
# production mode, deploys the build under /opt/mc/current/frontend-dist, and
# installs the unified nginx site from /root/deploy/nginx/nginx-all.conf.
# Companion to standalone-deploy.sh (the backend equivalent).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
BUILD_DIR="$FRONTEND_DIR/dist/frontend/browser"
DEPLOY_DIR="/opt/mc/current/frontend-dist"
NGINX_ALL_CONF="${NGINX_ALL_CONF:-/root/deploy/nginx/nginx-all.conf}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root (it installs nginx and a site config)." >&2
    exit 1
fi

if [ ! -f "$NGINX_ALL_CONF" ]; then
    echo "ERROR: unified nginx config not found at $NGINX_ALL_CONF" >&2
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

echo "==> Building for production (served from /mc/)"
npx ng build --configuration production --base-href /mc/

if [ ! -f "$BUILD_DIR/index.html" ]; then
    echo "ERROR: build did not produce $BUILD_DIR/index.html" >&2
    exit 1
fi

echo "==> Deploying frontend build to $DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"
rsync -a --delete "$BUILD_DIR/" "$DEPLOY_DIR/"

echo "==> Installing unified nginx site config"
install -m 644 "$NGINX_ALL_CONF" /etc/nginx/sites-available/all-apps
ln -sf /etc/nginx/sites-available/all-apps /etc/nginx/sites-enabled/all-apps
rm -f /etc/nginx/sites-enabled/{default,scm,mc,360feedback}

echo "==> Reloading nginx"
nginx -t
systemctl enable nginx >/dev/null
systemctl reload nginx 2>/dev/null || systemctl restart nginx

echo "==> Checking the frontend is served"
if ! curl -sf http://127.0.0.1/mc/ >/dev/null; then
    echo "ERROR: nginx did not serve the frontend at /mc/. Check: journalctl -u nginx -n 50 --no-pager" >&2
    exit 1
fi

echo "==> Frontend is up: http://$(curl -s -4 ifconfig.me 2>/dev/null || echo '<this-server-ip>')/mc/"
echo "    (API calls proxy through /mc/api/ to the backend - deploy it separately with standalone-deploy.sh if you haven't)"
