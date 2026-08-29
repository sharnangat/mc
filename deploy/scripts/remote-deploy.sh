#!/usr/bin/env bash
# Runs ON THE TARGET SERVER (invoked by Jenkins over SSH). Not run by developers directly.
#
# Expects a release already rsynced by Jenkins to:
#   $APP_ROOT/releases/$RELEASE_ID/backend/       (repo backend/, minus .venv, uploads, __pycache__, .env)
#   $APP_ROOT/releases/$RELEASE_ID/frontend-dist/ (Angular production build output)
#   $APP_ROOT/releases/$RELEASE_ID/db/            (schema.sql, seed.sql, deploy.sql)
#
# and a shared backend .env already placed at $APP_ROOT/shared/backend.env
# (Jenkins copies this from a secret-file credential before calling this script).
#
# Flow: build venv -> apply DB migrations -> flip the `current` symlink ->
# restart the backend service -> health-check -> roll back on failure.
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/mc}"
RELEASE_ID="${1:?usage: remote-deploy.sh <release-id>}"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
CURRENT_LINK="$APP_ROOT/current"
KEEP_RELEASES=5

echo "==> Deploying release $RELEASE_ID"

if [ ! -d "$RELEASE_DIR/backend" ] || [ ! -d "$RELEASE_DIR/frontend-dist" ]; then
    echo "ERROR: $RELEASE_DIR is missing backend/ or frontend-dist/ - did the rsync step run?" >&2
    exit 1
fi

echo "==> Linking shared backend .env"
ln -sf "$APP_ROOT/shared/backend.env" "$RELEASE_DIR/backend/.env"

echo "==> Creating backend virtualenv and installing dependencies"
python3 -m venv "$RELEASE_DIR/backend/.venv"
"$RELEASE_DIR/backend/.venv/bin/pip" install --no-cache-dir --quiet --upgrade pip
"$RELEASE_DIR/backend/.venv/bin/pip" install --no-cache-dir --quiet -r "$RELEASE_DIR/backend/requirements.txt"

echo "==> Applying database schema/seed (idempotent)"
DB_URL=$(grep -E '^DATABASE_URL=' "$APP_ROOT/shared/backend.env" | head -1 | cut -d= -f2-)
if [ -z "$DB_URL" ]; then
    echo "ERROR: DATABASE_URL not found in $APP_ROOT/shared/backend.env" >&2
    exit 1
fi
# db/deploy.sql creates the target database itself, so connect to the
# "postgres" maintenance database first, same as running it by hand.
PG_URL=${DB_URL/postgresql+asyncpg:/postgresql:}
MAINT_URL=$(echo "$PG_URL" | sed -E 's#(postgresql://[^/]+)/[^?]*#\1/postgres#')
psql "$MAINT_URL" -v ON_ERROR_STOP=1 -f "$RELEASE_DIR/db/deploy.sql"

PREVIOUS_RELEASE=""
if [ -L "$CURRENT_LINK" ]; then
    PREVIOUS_RELEASE=$(readlink "$CURRENT_LINK")
fi

echo "==> Switching current -> $RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

echo "==> Restarting backend service"
sudo systemctl restart mc-backend

echo "==> Health-checking backend"
HEALTHY=0
for _ in $(seq 1 15); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null; then
        HEALTHY=1
        break
    fi
    sleep 2
done

if [ "$HEALTHY" -ne 1 ]; then
    echo "ERROR: backend failed health check after deploy" >&2
    if [ -n "$PREVIOUS_RELEASE" ]; then
        echo "==> Rolling back current -> $PREVIOUS_RELEASE"
        ln -sfn "$PREVIOUS_RELEASE" "$CURRENT_LINK"
        sudo systemctl restart mc-backend
    fi
    exit 1
fi

echo "==> Deploy successful, backend healthy"

echo "==> Pruning old releases (keeping last $KEEP_RELEASES)"
cd "$APP_ROOT/releases"
ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf --

echo "==> Done"
