#!/usr/bin/env bash
# Configure the Jenkins "mc" pipeline job for automatic build + deploy.
#
# Run once on the Jenkins server (as root):
#   sudo bash deploy/scripts/setup-jenkins-pipeline.sh
#
# Prerequisites:
#   - Jenkins installed and running
#   - deploy/scripts/setup-jenkins-ssh.sh already run (SSH credentials)
#   - GitHub credential for sharnangat/mc.git checkout
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
JENKINS_HOME="${JENKINS_HOME:-/var/lib/jenkins}"
JOB_NAME="mc"
JOB_DIR="$JENKINS_HOME/jobs/$JOB_NAME"
SERVER_IP="${SERVER_IP:-$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')}"
GIT_CREDENTIAL_ID="${GIT_CREDENTIAL_ID:-f482ef30-04be-4fab-8730-7c142512addb}"

echo "==> Ensuring SSH credentials exist"
if ! grep -q 'mc-deploy-ssh' "$JENKINS_HOME/credentials.xml" 2>/dev/null; then
  bash "$SCRIPT_DIR/setup-jenkins-ssh.sh"
fi

echo "==> Tuning Jenkins JVM for low-memory droplet (1GB RAM)"
JENKINS_DEFAULTS=/etc/default/jenkins
if [ -f "$JENKINS_DEFAULTS" ]; then
  if ! grep -q 'BourneShellScript.HEARTBEAT_CHECK_INTERVAL' "$JENKINS_DEFAULTS"; then
    sed -i 's|^JAVA_ARGS=.*|JAVA_ARGS="-Djava.awt.headless=true -Xmx256m -XX:+UseSerialGC -Dorg.jenkinsci.plugins.durabletask.BourneShellScript.HEARTBEAT_CHECK_INTERVAL=300"|' "$JENKINS_DEFAULTS"
    systemctl restart jenkins
    for _ in $(seq 1 30); do
      curl -sf -o /dev/null http://127.0.0.1:8080/login && break
      sleep 2
    done
  fi
fi

echo "==> Ensuring build tools are available for the jenkins user"
apt-get update -qq
apt-get install -y -qq git rsync openssh-client postgresql-client python3-venv curl >/dev/null
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
  apt-get install -y -qq nodejs >/dev/null
fi

echo "==> Creating/updating Jenkins job: $JOB_NAME"
install -d -o jenkins -g jenkins "$JOB_DIR"

cat > "$JOB_DIR/config.xml" <<EOF
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job@1595.v0ee1a_de2c0a_3">
  <description>MC project - automatic build and deploy to ${SERVER_IP} on every push to main.</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty>
      <abortPrevious>true</abortPrevious>
    </org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty>
    <com.coravy.hudson.plugins.github.GithubProjectProperty plugin="github@1.47.0">
      <projectUrl>https://github.com/sharnangat/mc.git/</projectUrl>
      <displayName>mc</displayName>
    </com.coravy.hudson.plugins.github.GithubProjectProperty>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>DEPLOY_HOST</name>
          <description>Target server hostname/IP</description>
          <defaultValue>${SERVER_IP}</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DEPLOY_USER</name>
          <description>SSH user on the target server</description>
          <defaultValue>deploy</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.BooleanParameterDefinition>
          <name>SKIP_FRONTEND_TESTS</name>
          <description>Skip ng test (no Chrome on CI agent)</description>
          <defaultValue>true</defaultValue>
        </hudson.model.BooleanParameterDefinition>
        <hudson.model.BooleanParameterDefinition>
          <name>PROVISION_SERVER</name>
          <description>Create/bootstrap DigitalOcean droplet before deploy</description>
          <defaultValue>false</defaultValue>
        </hudson.model.BooleanParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DROPLET_NAME</name>
          <defaultValue>ubuntu-s-1vcpu-1gb-blr1-01</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DROPLET_REGION</name>
          <defaultValue>blr1</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DROPLET_SIZE</name>
          <defaultValue>s-1vcpu-1gb</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DROPLET_IMAGE</name>
          <defaultValue>ubuntu-24-04-x64</defaultValue>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>DO_SSH_KEY_ID</name>
          <description>DigitalOcean SSH key ID (only for PROVISION_SERVER)</description>
          <trim>false</trim>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition" plugin="workflow-cps@4370.v49a_6937566b_6">
    <scm class="hudson.plugins.git.GitSCM" plugin="git@5.10.1">
      <configVersion>2</configVersion>
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>https://github.com/sharnangat/mc.git</url>
          <credentialsId>${GIT_CREDENTIAL_ID}</credentialsId>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
      <branches>
        <hudson.plugins.git.BranchSpec>
          <name>*/main</name>
        </hudson.plugins.git.BranchSpec>
      </branches>
      <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>
      <submoduleCfg class="empty-list"/>
      <extensions/>
    </scm>
    <scriptPath>Jenkinsfile</scriptPath>
    <lightweight>true</lightweight>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>
EOF

chown jenkins:jenkins "$JOB_DIR/config.xml"
chmod 644 "$JOB_DIR/config.xml"

echo "==> Reloading Jenkins job configuration"
systemctl reload jenkins 2>/dev/null || systemctl restart jenkins
for _ in $(seq 1 30); do
  curl -sf -o /dev/null http://127.0.0.1:8080/login && break
  sleep 2
done

echo ""
echo "==> Jenkins pipeline configured"
echo "  Job URL     : http://${SERVER_IP}:8080/job/${JOB_NAME}/"
echo "  Triggers    : poll SCM every 2 min + GitHub push (via Jenkinsfile)"
echo "  Deploy target: deploy@${SERVER_IP}"
echo ""
echo "For instant builds on git push, add a GitHub webhook:"
echo "  Payload URL : http://${SERVER_IP}:8080/github-webhook/"
echo "  Content type: application/json"
echo "  Events      : Just the push event"
echo ""
echo "To run a build now:"
echo "  curl -X POST http://${SERVER_IP}:8080/job/${JOB_NAME}/build"
