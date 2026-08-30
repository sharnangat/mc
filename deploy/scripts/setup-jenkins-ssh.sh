#!/usr/bin/env bash
# One-time Jenkins SSH setup for the mc pipeline on this server.
# - Installs the ssh-agent plugin (required by Jenkinsfile sshagent { ... })
# - Generates a deploy SSH key for Jenkins
# - Bootstraps the local deploy user (this server is also the deploy target)
# - Registers Jenkins credentials: mc-deploy-ssh, mc-backend-env
# - Enables Jenkins inbound SSH (sshd plugin) on port 2222
#
# Run as root:
#   sudo bash deploy/scripts/setup-jenkins-ssh.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
JENKINS_HOME="${JENKINS_HOME:-/var/lib/jenkins}"
SSH_DIR="$JENKINS_HOME/.ssh"
DEPLOY_KEY="$SSH_DIR/mc-deploy"
BACKEND_ENV_SRC="${BACKEND_ENV_SRC:-$REPO_ROOT/backend/.env}"
GROOVY_INIT="$JENKINS_HOME/init.groovy.d/mc-ssh-credentials.groovy"
SERVER_IP="${SERVER_IP:-$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')}"

echo "==> Installing Jenkins ssh-agent plugin"
PLUGIN_VERSION="$(
  curl -fsSL https://updates.jenkins.io/current/update-center.actual.json \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['plugins']['ssh-agent']['version'])"
)"
curl -fsSL \
  -o "$JENKINS_HOME/plugins/ssh-agent.jpi" \
  "https://updates.jenkins.io/download/plugins/ssh-agent/${PLUGIN_VERSION}/ssh-agent.hpi"
chown jenkins:jenkins "$JENKINS_HOME/plugins/ssh-agent.jpi"
touch "$JENKINS_HOME/plugins/ssh-agent.jpi.dodeploy"

echo "==> Generating deploy SSH key for Jenkins"
install -d -m 700 -o jenkins -g jenkins "$SSH_DIR"
if [ ! -f "$DEPLOY_KEY" ]; then
  sudo -u jenkins ssh-keygen -t ed25519 -N '' -f "$DEPLOY_KEY" -C 'jenkins-mc-deploy'
fi
chmod 600 "$DEPLOY_KEY"
chmod 644 "${DEPLOY_KEY}.pub"

echo "==> Bootstrapping deploy user on this server"
DEPLOY_PUBKEY="$(cat "${DEPLOY_KEY}.pub")"
NGINX_ALL_CONF="${NGINX_ALL_CONF:-/root/deploy/nginx/nginx-all.conf}" \
  bash "$SCRIPT_DIR/bootstrap-server.sh" "$DEPLOY_PUBKEY"

echo "==> Allowing deploy user to SSH to this server as itself"
if ! sudo -u jenkins ssh -i "$DEPLOY_KEY" \
  -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
  "deploy@${SERVER_IP}" 'echo ok' >/dev/null 2>&1; then
  echo "WARNING: deploy@${SERVER_IP} SSH test failed - check authorized_keys and firewall." >&2
else
  echo "    SSH deploy@${SERVER_IP} OK"
fi

if [ ! -f "$BACKEND_ENV_SRC" ]; then
  echo "ERROR: backend env file not found at $BACKEND_ENV_SRC" >&2
  echo "       Create it from backend/.env.example, then re-run this script." >&2
  exit 1
fi
install -d -m 750 -o jenkins -g jenkins "$JENKINS_HOME/secrets/mc"
install -m 640 -o jenkins -g jenkins "$BACKEND_ENV_SRC" "$JENKINS_HOME/secrets/mc/backend.env"

echo "==> Writing Jenkins init script for SSH credentials"
install -d -m 755 "$JENKINS_HOME/init.groovy.d"
cat > "$GROOVY_INIT" <<'GROOVY'
import com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.Domain
import org.jenkinsci.plugins.plaincredentials.impl.FileCredentialsImpl
import jenkins.model.Jenkins

def jenkinsHome = System.getenv('JENKINS_HOME') ?: '/var/lib/jenkins'
def store = Jenkins.get().getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0].getStore()
def domain = Domain.global()
def existing = store.getCredentials(domain)*.id

if (!existing.contains('mc-deploy-ssh')) {
  def deployKey = new File("${jenkinsHome}/.ssh/mc-deploy").text
  store.addCredentials(domain, new BasicSSHUserPrivateKey(
    CredentialsScope.GLOBAL,
    'mc-deploy-ssh',
    'deploy',
    new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(deployKey),
    '',
    'MC deploy SSH key (local server)'
  ))
  println '[mc-ssh-setup] Added credential: mc-deploy-ssh'
} else {
  println '[mc-ssh-setup] Credential already exists: mc-deploy-ssh'
}

if (!existing.contains('mc-backend-env')) {
  def backendEnv = new File("${jenkinsHome}/secrets/mc/backend.env")
  store.addCredentials(domain, new FileCredentialsImpl(
    CredentialsScope.GLOBAL,
    'mc-backend-env',
    'MC backend production .env',
    'backend.env',
    SecretBytes.fromBytes(backendEnv.bytes)
  ))
  println '[mc-ssh-setup] Added credential: mc-backend-env'
} else {
  println '[mc-ssh-setup] Credential already exists: mc-backend-env'
}
GROOVY
chown jenkins:jenkins "$GROOVY_INIT"
chmod 644 "$GROOVY_INIT"

echo "==> Enabling Jenkins inbound SSH (sshd plugin) on port 2222"
SSHD_GROOVY="$JENKINS_HOME/init.groovy.d/mc-enable-jenkins-sshd.groovy"
cat > "$SSHD_GROOVY" <<'GROOVY'
import org.jenkinsci.main.modules.sshd.SSHD

def sshd = SSHD.get()
if (sshd.getPort() != 2222) {
  sshd.setPort(2222)
  sshd.save()
  sshd.restart()
  println '[mc-ssh-setup] Jenkins SSHD enabled on port 2222'
} else {
  println '[mc-ssh-setup] Jenkins SSHD already on port 2222'
}
GROOVY
chown jenkins:jenkins "$SSHD_GROOVY"
chmod 644 "$SSHD_GROOVY"

echo "==> Ensuring Jenkins agent tools are available"
apt-get update -qq
apt-get install -y -qq rsync openssh-client postgresql-client python3-venv >/dev/null

echo "==> Restarting Jenkins to load plugins and init scripts"
systemctl restart jenkins

echo "==> Waiting for Jenkins to come back..."
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null http://127.0.0.1:8080/login; then
    break
  fi
  sleep 2
done

if ! curl -sf -o /dev/null http://127.0.0.1:8080/login; then
  echo "ERROR: Jenkins did not restart in time. Check: journalctl -u jenkins -n 50" >&2
  exit 1
fi

echo ""
echo "==> Jenkins SSH setup complete"
echo "  Deploy SSH credential : mc-deploy-ssh (user: deploy)"
echo "  Backend env credential: mc-backend-env"
echo "  Deploy target         : deploy@${SERVER_IP}"
echo "  Jenkins SSHD          : ssh -p 2222 <jenkins-user>@${SERVER_IP}"
echo "  Pipeline job          : mc (uses sshagent in Jenkinsfile)"
echo ""
echo "Optional (only for PROVISION_SERVER builds):"
echo "  - Add Jenkins credential do-api-token (Secret text)"
echo "  - Add Jenkins credential mc-provision-ssh (root SSH key for DigitalOcean)"
