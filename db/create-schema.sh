#!/usr/bin/env bash
# Thin wrapper around db/deploy.sql (the actual schema/table source of truth -
# not duplicated here). Creates the "metag" database schema and all mc app
# tables on a Postgres server. Idempotent - safe to re-run.
#
# Usage:
#   ./create-schema.sh                                   # defaults below
#   DB_HOST=1.2.3.4 DB_USER=postgres ./create-schema.sh   # override via env
#   ./create-schema.sh -h 1.2.3.4 -U postgres             # or via flags
#
# Connects to the "postgres" maintenance database (not the app's own
# database) because db/deploy.sql creates the target database itself, and
# Postgres can't create/drop a database while connected to it.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"

while getopts "h:p:U:" opt; do
    case "$opt" in
        h) DB_HOST="$OPTARG" ;;
        p) DB_PORT="$OPTARG" ;;
        U) DB_USER="$OPTARG" ;;
        *) echo "Usage: $0 [-h host] [-p port] [-U user]" >&2; exit 1 ;;
    esac
done

echo "==> Applying db/deploy.sql to ${DB_HOST}:${DB_PORT} as ${DB_USER}"
echo "    (password prompt/lookup follows standard psql rules: PGPASSWORD, ~/.pgpass, or interactive)"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -f deploy.sql
