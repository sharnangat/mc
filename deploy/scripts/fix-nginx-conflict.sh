#!/usr/bin/env bash
# DEPRECATED: use /root/deploy/nginx/nginx-all.conf instead.
# This script merged per-app nginx blocks into a competing site config.
# All apps now share one config installed from deploy/nginx/nginx-all.conf.
set -euo pipefail

echo "This script is deprecated." >&2
echo "Install the unified config instead:" >&2
echo "  sudo cp /root/deploy/nginx/nginx-all.conf /etc/nginx/sites-available/all-apps" >&2
echo "  sudo ln -sf /etc/nginx/sites-available/all-apps /etc/nginx/sites-enabled/all-apps" >&2
echo "  sudo rm -f /etc/nginx/sites-enabled/{default,scm,mc,360feedback}" >&2
echo "  sudo nginx -t && sudo systemctl reload nginx" >&2
exit 1
