#!/usr/bin/env bash
# Runs ON THE TARGET DROPLET as root (piped over SSH by the Jenkins
# "Provision server" stage, right after deploy/systemd/mc-backend.service and
# deploy/nginx/mc.conf have already been rsynced into place). One-time
# machine setup: packages, service accounts, sudoers rule, /opt/mc layout,
# enabling the systemd unit and nginx site. Safe to re-run - every step is
# idempotent, so running this against an already-bootstrapped server just
# confirms everything is still in place.
set -euo pipefail

DEPLOY_PUBKEY="${1:?usage: bootstrap-server.sh <deploy-user-ssh-public-key>}"

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip rsync nginx postgresql-client curl >/dev/null
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y -qq nodejs >/dev/null
fi

echo "==> Creating service accounts"
getent group mc >/dev/null || groupadd --system mc
id -u mc >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin --gid mc mc
id -u deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --groups mc deploy

echo "==> Authorizing the deploy key"
mkdir -p /home/deploy/.ssh
grep -qxF "$DEPLOY_PUBKEY" /home/deploy/.ssh/authorized_keys 2>/dev/null \
  || echo "$DEPLOY_PUBKEY" >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

echo "==> Restricted sudo rule for the deploy user"
echo 'deploy ALL=(root) NOPASSWD: /bin/systemctl restart mc-backend' > /etc/sudoers.d/mc-deploy
chmod 440 /etc/sudoers.d/mc-deploy

echo "==> /opt/mc layout"
mkdir -p /opt/mc/releases /opt/mc/shared/uploads
chown -R deploy:mc /opt/mc
chmod 2755 /opt/mc/releases
chmod 2775 /opt/mc/shared/uploads
chmod 750 /opt/mc/shared

echo "==> Enabling the backend service"
systemctl daemon-reload
systemctl enable mc-backend >/dev/null

echo "==> Enabling the nginx site"
ln -sf /etc/nginx/sites-available/mc.conf /etc/nginx/sites-enabled/mc.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    echo "==> Opening firewall ports"
    ufw allow OpenSSH >/dev/null
    ufw allow 80/tcp >/dev/null
fi

echo "==> Bootstrap complete"
