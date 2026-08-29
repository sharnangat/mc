#!/usr/bin/env bash
# Fixes: a separate app's nginx site (already using server_name _ / no
# distinguishing server_name) was "winning" the shared port-80 slot on this
# IP, so our own mc.conf server block was never being selected at all - its
# /mc/ location was correct but simply never evaluated for any request.
#
# nginx can't split two different catch-all apps by hostname when both are
# reached via the same bare IP (no domain names to distinguish them), so the
# only way for both to coexist is putting both sets of locations in the SAME
# server block. This finds the other app's config and injects our /mc/,
# /api/, and /health locations into it directly, right before its closing
# brace - backing it up first and rolling back automatically if the result
# doesn't pass `nginx -t`, so this can't leave nginx in a broken state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$REPO_ROOT/frontend/dist/frontend/browser"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run as root." >&2
    exit 1
fi

if [ ! -f "$BUILD_DIR/index.html" ]; then
    echo "ERROR: $BUILD_DIR/index.html not found - run standalone-deploy-frontend.sh first." >&2
    exit 1
fi

mapfile -t OTHER_CONFIGS < <(
    grep -l "listen 80" /etc/nginx/sites-enabled/* 2>/dev/null | grep -vF "/mc.conf" || true
)

if [ "${#OTHER_CONFIGS[@]}" -eq 0 ]; then
    echo "No other nginx site on port 80 found under sites-enabled/ - the conflict may be elsewhere."
    echo "Share the output of: nginx -T"
    exit 1
fi

FIXED_ANY=0
for CONF in "${OTHER_CONFIGS[@]}"; do
    echo "==> Found competing config: $CONF"

    if grep -q "location /mc/" "$CONF"; then
        echo "    Already has a /mc/ location - skipping."
        continue
    fi

    BACKUP="${CONF}.bak.$(date +%s)"
    cp "$CONF" "$BACKUP"
    echo "    Backed up to $BACKUP"

    python3 - "$CONF" "$BUILD_DIR" <<'PYEOF'
import sys

path, build_dir = sys.argv[1], sys.argv[2]
inject = f"""
    location /api/ {{
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location = /health {{
        proxy_pass http://127.0.0.1:8000/health;
    }}

    location /mc/ {{
        alias {build_dir}/;
        try_files $uri $uri/ /mc/index.html;
    }}

    location = /mc {{
        return 301 /mc/;
    }}
"""

with open(path) as f:
    content = f.read()

idx = content.rstrip().rfind('}')
if idx == -1:
    print("Could not find a closing brace to inject before.", file=sys.stderr)
    sys.exit(1)

with open(path, 'w') as f:
    f.write(content[:idx] + inject + "\n" + content[idx:])
PYEOF

    echo "==> Validating nginx config"
    if nginx -t 2>&1; then
        echo "    OK"
        FIXED_ANY=1
    else
        echo "    Invalid - rolling back $CONF"
        cp "$BACKUP" "$CONF"
        nginx -t
        echo "ERROR: automated merge failed for $CONF. Paste its content (cat $BACKUP) so this can be fixed by hand instead." >&2
        exit 1
    fi
done

if [ "$FIXED_ANY" -eq 1 ]; then
    systemctl reload nginx
    echo "==> Reloaded nginx. Try: http://<server-ip>/mc/"
else
    echo "Nothing changed."
fi
