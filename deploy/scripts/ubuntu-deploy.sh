#!/usr/bin/env bash
# Complete Ubuntu deployment for the Metallurgical Consultation app.
#
# On a fresh Ubuntu 22.04 or 24.04 server, from a checkout of this repo:
#
#   sudo bash deploy/scripts/ubuntu-deploy.sh
#
# What it does (safe to re-run):
#   1. Installs PostgreSQL 16 and pgvector
#   2. Creates database "onlinedb", schema "metag", tables, indexes, and seed data
#      (db/deploy.sql, db/schema.sql, db/seed.sql)
#   3. Creates the application database role and writes backend/.env when missing
#   4. Installs the FastAPI backend as the systemd service mc-backend
#   5. Builds the Angular app and serves it with nginx at /mc/
#
# Optional environment variables:
#   DB_USER          application role (default: mc). Ignored when backend/.env exists.
#   DB_PASSWORD      role password. Generated and stored in backend/.env when omitted.
#   JWT_SECRET       generated when backend/.env is created.
#   ADMIN_EMAIL      admin login (default: vidyanand@mc.local)
#   ADMIN_PASSWORD   admin password (default: vidyanand123)
#   ADMIN_FULL_NAME  admin display name (default: Vidyanand)
#
# An existing backend/.env is kept. Its DATABASE_URL must use database onlinedb.
# A non-local DATABASE_URL skips the local PostgreSQL install and applies
# db/deploy.sql to that server (the URL user must be allowed to create the
# database and the vector extension).
#
# After the API is healthy, the script creates or resets the admin account.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run this as root: sudo bash deploy/scripts/ubuntu-deploy.sh" >&2
    exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: this script is for Ubuntu." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
DEPLOY_SQL="$REPO_ROOT/db/deploy.sql"
NGINX_MC_CONF="$REPO_ROOT/deploy/nginx/mc.conf"
FRONTEND_DIST="/opt/mc/current/frontend-dist"
BUILD_DIR="$FRONTEND_DIR/dist/frontend/browser"
ENV_FILE="$BACKEND_DIR/.env"
DB_NAME="onlinedb"
DB_SCHEMA="metag"

export DEBIAN_FRONTEND=noninteractive

if [ ! -f "$DEPLOY_SQL" ] || [ ! -f "$BACKEND_DIR/requirements.txt" ] || [ ! -f "$FRONTEND_DIR/package.json" ]; then
    echo "ERROR: run this from a full checkout of the mc repository." >&2
    exit 1
fi

echo "==> Installing base packages"
apt-get update -qq
apt-get install -y -qq \
    ca-certificates curl gnupg openssl rsync nginx \
    python3 python3-venv python3-pip \
    postgresql-common >/dev/null

add_pgdg_repo() {
    if [ -f /etc/apt/sources.list.d/pgdg.list ]; then
        return
    fi
    echo "==> Adding the PostgreSQL APT repository"
    install -d /usr/share/postgresql-common/pgdg
    curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list
    apt-get update -qq
}

cluster16_exists() {
    command -v pg_lsclusters >/dev/null 2>&1 \
        && pg_lsclusters --no-header 2>/dev/null | awk '$1==16 && $2=="main" {found=1} END{exit !found}'
}

cluster16_port() {
    pg_lsclusters --no-header | awk '$1==16 && $2=="main" {print $3; exit}'
}

install_local_postgres() {
    echo "==> Installing PostgreSQL 16, contrib, and pgvector"
    if ! cluster16_exists; then
        add_pgdg_repo
    fi
    if ! apt-get install -y postgresql-16 postgresql-contrib-16 postgresql-16-pgvector; then
        add_pgdg_repo
        apt-get install -y postgresql-16 postgresql-contrib-16 postgresql-16-pgvector
    fi

    systemctl enable postgresql >/dev/null
    systemctl start postgresql

    DB_PORT="$(cluster16_port)"
    if [ -z "${DB_PORT}" ]; then
        echo "ERROR: PostgreSQL 16 cluster 'main' was not created." >&2
        exit 1
    fi
    if ! pg_lsclusters --no-header | awk -v port="$DB_PORT" '$1==16 && $2=="main" && $3==port && $4=="online" {found=1} END{exit !found}'; then
        pg_ctlcluster 16 main start
    fi
}

require_ident() {
    if ! [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        echo "ERROR: database user '$1' must be a plain identifier (letters, digits, underscore)." >&2
        exit 1
    fi
}

write_env_file() {
    local db_user="$1" db_password="$2" db_port="$3" jwt_secret="$4"
    local old_umask
    old_umask="$(umask)"
    umask 077
    cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql+asyncpg://${db_user}:${db_password}@127.0.0.1:${db_port}/${DB_NAME}
DB_SCHEMA=${DB_SCHEMA}

JWT_SECRET=${jwt_secret}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

UPLOAD_DIR=./uploads

ALLOW_EXTERNAL_KNOWLEDGE=false

EMBEDDING_DIM=384

LOG_LEVEL=INFO
EOF
    chmod 600 "$ENV_FILE"
    umask "$old_umask"
    echo "==> Wrote $ENV_FILE (mode 600). Keep this file; it holds the database password and JWT secret."
}

read_database_url() {
    local parsed
    parsed="$(
        DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)" \
        python3 - <<'PY'
import os
import shlex
from urllib.parse import urlparse

raw = os.environ.get("DATABASE_URL", "")
if not raw:
    raise SystemExit("DATABASE_URL is missing from backend/.env")
parsed = urlparse(raw.replace("postgresql+asyncpg://", "postgresql://", 1))
if not parsed.hostname or not parsed.username or parsed.password is None:
    raise SystemExit("DATABASE_URL must look like postgresql+asyncpg://user:password@host:5432/onlinedb")
name = parsed.path.lstrip("/")
if not name:
    raise SystemExit("DATABASE_URL is missing a database name")
fields = {
    "DB_USER": parsed.username,
    "DB_PASSWORD": parsed.password,
    "DB_HOST": parsed.hostname,
    "DB_PORT": str(parsed.port or 5432),
    "DB_NAME_PARSED": name,
}
for key, value in fields.items():
    print(f"{key}={shlex.quote(value)}")
PY
    )"
    # shellcheck disable=SC1090
    eval "$parsed"
    if [ "$DB_NAME_PARSED" != "$DB_NAME" ]; then
        echo "ERROR: DATABASE_URL uses database '$DB_NAME_PARSED', but this app creates '$DB_NAME'." >&2
        exit 1
    fi
}

# postgres cannot read a checkout under /root (mode 700). Copy the SQL
# somewhere it can read. \ir in deploy.sql loads schema.sql and seed.sql
# from the same directory.
apply_deploy_sql_as_postgres() {
    local sql_dir status
    sql_dir="$(mktemp -d /tmp/mc-deploy-sql.XXXXXX)"
    cp "$REPO_ROOT/db/deploy.sql" "$REPO_ROOT/db/schema.sql" "$REPO_ROOT/db/seed.sql" "$sql_dir/"
    chmod 755 "$sql_dir"
    chmod 644 "$sql_dir"/*.sql
    set +e
    sudo -u postgres psql -p "$DB_PORT" -d postgres -v ON_ERROR_STOP=1 -f "$sql_dir/deploy.sql"
    status=$?
    set -e
    rm -rf "$sql_dir"
    if [ "$status" -ne 0 ]; then
        exit "$status"
    fi
}

apply_schema_local() {
    echo "==> Creating database role '$DB_USER'"
    sudo -u postgres psql -p "$DB_PORT" -d postgres -v ON_ERROR_STOP=1 \
        -v dbuser="$DB_USER" -v dbpass="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'dbuser', :'dbpass')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'dbuser')\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'dbuser', :'dbpass')\gexec
SQL

    echo "==> Creating database, schema, and tables (db/deploy.sql)"
    apply_deploy_sql_as_postgres

    echo "==> Granting '$DB_USER' access to schema $DB_SCHEMA"
    sudo -u postgres psql -p "$DB_PORT" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
        -v dbuser="$DB_USER" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE onlinedb TO %I', :'dbuser')\gexec
SELECT format('GRANT USAGE ON SCHEMA metag, public TO %I', :'dbuser')\gexec
SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA metag TO %I', :'dbuser')\gexec
SELECT format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA metag TO %I', :'dbuser')\gexec
SELECT format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA metag, public TO %I', :'dbuser')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA metag GRANT ALL ON TABLES TO %I', :'dbuser')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA metag GRANT ALL ON SEQUENCES TO %I', :'dbuser')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA metag GRANT EXECUTE ON FUNCTIONS TO %I', :'dbuser')\gexec
SQL
}

apply_schema_remote() {
    echo "==> Applying db/deploy.sql on ${DB_HOST}:${DB_PORT} (remote database)"
    apt-get install -y -qq postgresql-client >/dev/null
    local maint_url
    maint_url="$(
        DB_USER="$DB_USER" DB_PASSWORD="$DB_PASSWORD" DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" \
        python3 - <<'PY'
import os
from urllib.parse import quote

user = quote(os.environ["DB_USER"], safe="")
password = quote(os.environ["DB_PASSWORD"], safe="")
host = os.environ["DB_HOST"]
port = os.environ["DB_PORT"]
print(f"postgresql://{user}:{password}@{host}:{port}/postgres")
PY
    )"
    psql "$maint_url" -v ON_ERROR_STOP=1 -f "$DEPLOY_SQL"
}

echo "==> Preparing backend environment"
if [ ! -f "$ENV_FILE" ]; then
    DB_USER="${DB_USER:-mc}"
    DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -hex 24)}"
    JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
    require_ident "$DB_USER"
    install_local_postgres
    write_env_file "$DB_USER" "$DB_PASSWORD" "$DB_PORT" "$JWT_SECRET"
    apply_schema_local
else
    read_database_url
    require_ident "$DB_USER"
    if [ "$DB_HOST" = "localhost" ] || [ "$DB_HOST" = "127.0.0.1" ]; then
        env_port="$DB_PORT"
        install_local_postgres
        if [ "$env_port" != "$DB_PORT" ]; then
            echo "ERROR: backend/.env uses port ${env_port}, but PostgreSQL 16 is listening on ${DB_PORT}." >&2
            exit 1
        fi
        if [ "$DB_USER" = "postgres" ]; then
            echo "==> Creating database, schema, and tables (db/deploy.sql)"
            apply_deploy_sql_as_postgres
        else
            apply_schema_local
        fi
    else
        apply_schema_remote
    fi
fi

mem_mb="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${mem_mb}" -lt 1500 ]; then
    echo "WARNING: about ${mem_mb} MB RAM is free. The API loads PyTorch; a machine with 2 GB or more is more reliable."
fi

echo "==> Installing backend dependencies"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
if [ -f "$VENV_PY" ] && ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    echo "==> Existing virtualenv has no pip; recreating it"
    rm -rf "$BACKEND_DIR/.venv"
fi
if [ ! -f "$VENV_PY" ]; then
    python3 -m venv "$BACKEND_DIR/.venv"
fi
"$VENV_PY" -m pip install --no-cache-dir --quiet --upgrade pip
"$VENV_PY" -m pip install --no-cache-dir -r "$BACKEND_DIR/requirements.txt"
mkdir -p "$BACKEND_DIR/uploads"

echo "==> Installing systemd service mc-backend"
cat > /etc/systemd/system/mc-backend.service <<EOF
[Unit]
Description=Metallurgical Consultation API (FastAPI/uvicorn)
After=network.target postgresql.service

[Service]
Type=simple
# root: the checkout may live under /root, which a service account cannot read.
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$BACKEND_DIR/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mc-backend >/dev/null
systemctl restart mc-backend

echo "==> Waiting for the API health check"
HEALTHY=0
for _ in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null; then
        HEALTHY=1
        break
    fi
    sleep 2
done
if [ "$HEALTHY" -ne 1 ]; then
    echo "ERROR: backend did not become healthy. Check: journalctl -u mc-backend -n 80 --no-pager" >&2
    exit 1
fi

ADMIN_EMAIL="${ADMIN_EMAIL:-vidyanand@mc.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-vidyanand123}"
ADMIN_FULL_NAME="${ADMIN_FULL_NAME:-Vidyanand}"
echo "==> Creating admin account $ADMIN_EMAIL"
(cd "$BACKEND_DIR" && "$VENV_PY" scripts/create_admin.py "$ADMIN_EMAIL" "$ADMIN_PASSWORD" "$ADMIN_FULL_NAME")

echo "==> Installing Node.js"
if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y nodejs
fi

echo "==> Building the Angular frontend"
cd "$FRONTEND_DIR"
export CI=true
export NG_CLI_ANALYTICS=false
npm ci
npx ng build --configuration production --base-href /mc/
if [ ! -f "$BUILD_DIR/index.html" ]; then
    echo "ERROR: build did not produce $BUILD_DIR/index.html" >&2
    exit 1
fi

echo "==> Publishing the frontend to $FRONTEND_DIST"
mkdir -p "$FRONTEND_DIST"
rsync -a --delete "$BUILD_DIR/" "$FRONTEND_DIST/"
# nginx (www-data) must be able to traverse these directories and read the files
chmod a+rx /opt/mc /opt/mc/current "$FRONTEND_DIST"
find "$FRONTEND_DIST" -type d -exec chmod a+rx {} +
find "$FRONTEND_DIST" -type f -exec chmod a+r {} +
# mc.conf uses root /opt/mc/current, so /mc/index.html is this path
if [ -d /opt/mc/current/mc ] && [ ! -L /opt/mc/current/mc ]; then
    rm -rf /opt/mc/current/mc
fi
ln -sfn frontend-dist /opt/mc/current/mc

echo "==> Configuring nginx"
if [ ! -f "$NGINX_MC_CONF" ]; then
    echo "ERROR: missing $NGINX_MC_CONF" >&2
    exit 1
fi
if [ -e /etc/nginx/sites-enabled/all-apps ]; then
    echo "    Unified site /etc/nginx/sites-enabled/all-apps is already enabled; leaving it in place."
    echo "    It serves this app at /mc/ from $FRONTEND_DIST."
else
    install -m 644 "$NGINX_MC_CONF" /etc/nginx/sites-available/mc
    ln -sf /etc/nginx/sites-available/mc /etc/nginx/sites-enabled/mc
    rm -f /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl enable nginx >/dev/null
systemctl reload nginx 2>/dev/null || systemctl restart nginx

HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/mc/ || true)"
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: nginx returned HTTP ${HTTP_CODE:-000} for http://127.0.0.1/mc/." >&2
    echo "       Expected index at /opt/mc/current/mc/index.html" >&2
    ls -l /opt/mc/current/mc/index.html >&2 || true
    exit 1
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    echo "==> Opening HTTP in ufw"
    ufw allow OpenSSH >/dev/null
    ufw allow 80/tcp >/dev/null
fi

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
SERVER_IP="${SERVER_IP:-<this-server>}"

echo
echo "Deployment finished."
echo "  App:      http://${SERVER_IP}/mc/"
echo "  API:      http://${SERVER_IP}/mc/api/docs"
echo "  Database: ${DB_NAME}, schema ${DB_SCHEMA}"
echo "  Backend:  systemctl status mc-backend"
echo "  Logs:     journalctl -u mc-backend -f"
echo "  Admin:    ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}"
