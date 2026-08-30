#!/usr/bin/env bash
# Put Jenkins behind nginx HTTPS and bind the Java process to localhost only.
#
# Run as root:
#   sudo bash deploy/scripts/setup-jenkins-https.sh
#
# Optional env:
#   JENKINS_DOMAIN=ci.example.com   Use Let's Encrypt instead of a self-signed cert
#   SERVER_IP=139.59.81.129           Public IP for Jenkins root URL (auto-detected)
#   JENKINS_HTTP_PORT=8080            Local Jenkins port (default 8080)
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NGINX_SRC="${NGINX_SRC:-$REPO_ROOT/deploy/nginx/jenkins.conf}"
SSL_DIR=/etc/nginx/ssl/jenkins
JENKINS_DEFAULTS=/etc/default/jenkins
JENKINS_HOME="${JENKINS_HOME:-/var/lib/jenkins}"
JENKINS_HTTP_PORT="${JENKINS_HTTP_PORT:-8080}"
SERVER_IP="${SERVER_IP:-$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')}"
JENKINS_URL="https://${JENKINS_DOMAIN:-$SERVER_IP}/"

echo "==> Jenkins will be served at $JENKINS_URL"

install -d -m 755 "$SSL_DIR"

if [ -n "${JENKINS_DOMAIN:-}" ]; then
  echo "==> Obtaining Let's Encrypt certificate for $JENKINS_DOMAIN"
  apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
  if [ ! -f "$NGINX_SRC" ]; then
    echo "ERROR: nginx config not found at $NGINX_SRC" >&2
    exit 1
  fi
  install -m 644 "$NGINX_SRC" /etc/nginx/sites-available/jenkins
  ln -sf /etc/nginx/sites-available/jenkins /etc/nginx/sites-enabled/jenkins
  nginx -t
  systemctl reload nginx
  certbot certonly --nginx -d "$JENKINS_DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email || certbot certonly --nginx -d "$JENKINS_DOMAIN"
  ln -sf "/etc/letsencrypt/live/$JENKINS_DOMAIN/fullchain.pem" "$SSL_DIR/fullchain.pem"
  ln -sf "/etc/letsencrypt/live/$JENKINS_DOMAIN/privkey.pem" "$SSL_DIR/privkey.pem"
else
  echo "==> Generating self-signed certificate for $SERVER_IP"
  if [ ! -f "$SSL_DIR/fullchain.pem" ]; then
    openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
      -keyout "$SSL_DIR/privkey.pem" \
      -out "$SSL_DIR/fullchain.pem" \
      -subj "/CN=$SERVER_IP" \
      -addext "subjectAltName=IP:$SERVER_IP" 2>/dev/null \
      || openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout "$SSL_DIR/privkey.pem" \
        -out "$SSL_DIR/fullchain.pem" \
        -subj "/CN=$SERVER_IP"
  fi
  chmod 600 "$SSL_DIR/privkey.pem"
  chmod 644 "$SSL_DIR/fullchain.pem"

  echo "==> Installing nginx site for Jenkins"
  install -m 644 "$NGINX_SRC" /etc/nginx/sites-available/jenkins
  ln -sf /etc/nginx/sites-available/jenkins /etc/nginx/sites-enabled/jenkins
fi

echo "==> Binding Jenkins to localhost:$JENKINS_HTTP_PORT"
mkdir -p /etc/systemd/system/jenkins.service.d
cat > /etc/systemd/system/jenkins.service.d/localhost-only.conf <<EOF
[Service]
Environment="JENKINS_LISTEN_ADDRESS=127.0.0.1"
Environment="JENKINS_PORT=$JENKINS_HTTP_PORT"
EOF

# Legacy /etc/default/jenkins is ignored by modern systemd units; keep in sync anyway.
if grep -q '^HTTP_PORT=' "$JENKINS_DEFAULTS" 2>/dev/null; then
  sed -i "s|^HTTP_PORT=.*|HTTP_PORT=$JENKINS_HTTP_PORT|" "$JENKINS_DEFAULTS"
fi

echo "==> Setting Jenkins root URL to $JENKINS_URL"
install -d -m 755 "$JENKINS_HOME/init.groovy.d"
cat > "$JENKINS_HOME/init.groovy.d/mc-jenkins-https.groovy" <<GROOVY
import jenkins.model.JenkinsLocationConfiguration

def url = '${JENKINS_URL}'
def loc = JenkinsLocationConfiguration.get()
if (loc.getUrl() != url) {
  loc.setUrl(url)
  loc.save()
  println "[mc-jenkins-https] Jenkins URL set to \${url}"
} else {
  println "[mc-jenkins-https] Jenkins URL already \${url}"
}
GROOVY
chown jenkins:jenkins "$JENKINS_HOME/init.groovy.d/mc-jenkins-https.groovy"

nginx -t
systemctl reload nginx
systemctl daemon-reload
systemctl restart jenkins

echo "==> Restricting firewall: allow HTTPS, close public Jenkins port"
ufw allow 443/tcp >/dev/null 2>&1 || true
ufw delete allow 8080/tcp >/dev/null 2>&1 || true

echo "==> Waiting for Jenkins"
for _ in $(seq 1 30); do
  if curl -skf "https://127.0.0.1/login" >/dev/null 2>&1; then
    echo "==> Jenkins HTTPS is up at $JENKINS_URL"
    exit 0
  fi
  sleep 2
done

echo "WARNING: Jenkins did not respond on HTTPS within 60s - check: journalctl -u jenkins -n 50" >&2
exit 1
