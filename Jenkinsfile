// Jenkins pipeline: build + deploy both the FastAPI backend and the Angular
// frontend to a single Linux target server (bare process, no containers).
// Optionally provisions that server itself via the DigitalOcean API first.
//
// --- Target server setup ----------------------------------------------------
// Either do this once by hand, OR check PROVISION_SERVER when building and
// let the "Provision server" stage do it (idempotent - safe against an
// already-set-up server too, it just confirms everything's in place):
//   1. Create a deploy user (e.g. "deploy") with a home dir and passwordless
//      sudo restricted to restarting the backend service:
//        echo 'deploy ALL=(root) NOPASSWD: /bin/systemctl restart mc-backend' \
//          | sudo tee /etc/sudoers.d/mc-deploy
//   2. mkdir -p /opt/mc/{releases,shared} && chown -R deploy:deploy /opt/mc
//   3. Install deploy/systemd/mc-backend.service to /etc/systemd/system/,
//      then `systemctl daemon-reload && systemctl enable mc-backend`.
//   4. Install deploy/nginx/mc.conf to /etc/nginx/sites-available/, symlink
//      into sites-enabled, `nginx -t && systemctl reload nginx`.
//   5. Postgres must be reachable from the target server (this pipeline runs
//      db/deploy.sql there on every deploy - it's idempotent, see db/deploy.sql).
// (deploy/scripts/bootstrap-server.sh is what PROVISION_SERVER runs to do 1-4.)
//
// --- One-time setup in Jenkins -----------------------------------------------
//   - Install plugins: "SSH Agent", "Pipeline".
//   - Agent must have on PATH: python3 (3.13), node/npm (20+), rsync, ssh, psql.
//   - Credentials:
//       mc-deploy-ssh    (SSH Username with private key) - the "deploy" user's key
//       mc-backend-env   (Secret file) - production backend/.env contents
//     Only needed if you'll use PROVISION_SERVER:
//       do-api-token     (Secret text) - a DigitalOcean API token
//       mc-provision-ssh (SSH Username with private key, username "root") - a
//                        key whose PUBLIC half is already uploaded to your DO
//                        account's SSH Keys (Settings > Security), so new
//                        droplets get root access baked in at creation. Its
//                        fingerprint/ID is what DO_SSH_KEY_ID below must be.
//   - Configure DEPLOY_HOST below (or override as a build parameter).
//
// Rollback: remote-deploy.sh keeps the last 5 releases under /opt/mc/releases
// and automatically re-points /opt/mc/current at the previous release if the
// new one fails its post-deploy health check.
//
// SECURITY NOTE: never paste a real API token or private key into this file
// or into chat/logs - they belong ONLY in the Jenkins credential store above.

pipeline {
    agent any

    parameters {
        string(name: 'DEPLOY_HOST', defaultValue: '139.59.81.129', description: 'Target server hostname/IP (overwritten by discovery if PROVISION_SERVER is checked)')
        string(name: 'DEPLOY_USER', defaultValue: 'deploy', description: 'SSH user on the target server')
        booleanParam(name: 'SKIP_FRONTEND_TESTS', defaultValue: false, description: 'Skip `ng test` (requires Chrome on the agent)')
        booleanParam(name: 'PROVISION_SERVER', defaultValue: false, description: 'Create/bootstrap the target droplet via the DigitalOcean API before deploying. Idempotent - leave unchecked for routine deploys to an already-set-up server.')
        string(name: 'DROPLET_NAME', defaultValue: 'ubuntu-s-1vcpu-1gb-blr1-01', description: 'DigitalOcean droplet name (looked up, or created if missing) - only used when PROVISION_SERVER is checked')
        string(name: 'DROPLET_REGION', defaultValue: 'blr1', description: 'DigitalOcean region slug')
        string(name: 'DROPLET_SIZE', defaultValue: 's-1vcpu-1gb', description: 'DigitalOcean size slug')
        string(name: 'DROPLET_IMAGE', defaultValue: 'ubuntu-24-04-x64', description: 'DigitalOcean image slug')
        string(name: 'DO_SSH_KEY_ID', defaultValue: '', description: 'Fingerprint or numeric ID of an SSH key already uploaded to your DO account - required when PROVISION_SERVER is checked')
    }

    environment {
        APP_ROOT   = '/opt/mc'
        RELEASE_ID = "${BUILD_NUMBER}"
    }

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'echo "Deploying commit: $(git rev-parse HEAD)"'
            }
        }

        stage('Backend: install & sanity check') {
            steps {
                dir('backend') {
                    sh '''
                        set -eu
                        python3 -m venv .ci-venv
                        .ci-venv/bin/pip install --no-cache-dir --quiet --upgrade pip
                        .ci-venv/bin/pip install --no-cache-dir --quiet -r requirements.txt
                        .ci-venv/bin/python -m compileall -q app
                    '''
                }
            }
        }

        stage('Frontend: install & build') {
            steps {
                dir('frontend') {
                    sh 'npm ci'
                    sh '''
                        set -eu
                        if [ "${SKIP_FRONTEND_TESTS}" != "true" ]; then
                            npx ng test --watch=false --browsers=ChromeHeadless
                        fi
                    '''
                    sh 'npx ng build --configuration production'
                }
            }
        }

        stage('Provision server (DigitalOcean)') {
            when {
                expression { params.PROVISION_SERVER }
            }
            steps {
                sshagent(credentials: ['mc-provision-ssh']) {
                    withCredentials([
                        string(credentialsId: 'do-api-token', variable: 'DO_API_TOKEN'),
                        sshUserPrivateKey(credentialsId: 'mc-deploy-ssh', keyFileVariable: 'DEPLOY_KEY_FILE')
                    ]) {
                        sh '''
                            set -eu
                            bash deploy/scripts/provision-droplet.sh > .droplet_ip

                            SSH_OPTS="-o StrictHostKeyChecking=accept-new"
                            IP=$(cat .droplet_ip)
                            DEPLOY_PUBKEY=$(ssh-keygen -y -f "$DEPLOY_KEY_FILE")

                            rsync -az -e "ssh $SSH_OPTS" deploy/systemd/mc-backend.service "root@${IP}:/etc/systemd/system/mc-backend.service"
                            rsync -az -e "ssh $SSH_OPTS" deploy/nginx/mc.conf "root@${IP}:/etc/nginx/sites-available/mc.conf"
                            ssh $SSH_OPTS "root@${IP}" "bash -s" -- "$DEPLOY_PUBKEY" < deploy/scripts/bootstrap-server.sh
                        '''
                    }
                }
                script {
                    env.DEPLOY_HOST = readFile('.droplet_ip')
                }
            }
        }

        stage('Ship release to target server') {
            steps {
                sh '''
                    set -eu
                    if [ -z "${DEPLOY_HOST:-}" ]; then
                        echo "ERROR: DEPLOY_HOST is required (pass it as a build parameter)." >&2
                        exit 1
                    fi
                '''
                sshagent(credentials: ['mc-deploy-ssh']) {
                    withCredentials([file(credentialsId: 'mc-backend-env', variable: 'BACKEND_ENV_FILE')]) {
                        sh '''
                            set -eu
                            SSH_OPTS="-o StrictHostKeyChecking=accept-new"
                            TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
                            RELEASE_DIR="${APP_ROOT}/releases/${RELEASE_ID}"

                            ssh $SSH_OPTS "$TARGET" "mkdir -p ${RELEASE_DIR}/backend ${RELEASE_DIR}/frontend-dist ${RELEASE_DIR}/db ${APP_ROOT}/shared"

                            # Backend source, minus dev-only/runtime-only content.
                            rsync -az --delete \
                              --exclude '.venv' --exclude '.ci-venv' --exclude '__pycache__' \
                              --exclude 'uploads' --exclude '.env' \
                              -e "ssh $SSH_OPTS" \
                              backend/ "$TARGET:${RELEASE_DIR}/backend/"

                            # Schema/seed/deploy scripts, applied idempotently on the target.
                            rsync -az --delete -e "ssh $SSH_OPTS" db/ "$TARGET:${RELEASE_DIR}/db/"

                            # Built Angular app.
                            rsync -az --delete -e "ssh $SSH_OPTS" \
                              frontend/dist/frontend/browser/ "$TARGET:${RELEASE_DIR}/frontend-dist/"

                            # Remote deploy script itself (kept alongside the release it deploys).
                            rsync -az -e "ssh $SSH_OPTS" deploy/scripts/remote-deploy.sh "$TARGET:${RELEASE_DIR}/remote-deploy.sh"

                            # Production secrets, from the Jenkins credential store (single source of truth).
                            scp $SSH_OPTS "$BACKEND_ENV_FILE" "$TARGET:${APP_ROOT}/shared/backend.env"

                            ssh $SSH_OPTS "$TARGET" "chmod +x ${RELEASE_DIR}/remote-deploy.sh && APP_ROOT=${APP_ROOT} ${RELEASE_DIR}/remote-deploy.sh ${RELEASE_ID}"
                        '''
                    }
                }
            }
        }
    }

    post {
        success {
            echo "Deployed release ${env.RELEASE_ID} to ${env.DEPLOY_HOST}"
        }
        failure {
            echo "Deploy failed - check the 'Ship release to target server' stage log. remote-deploy.sh auto-rolls back the backend on a failed health check, but verify manually."
        }
        always {
            dir('backend') {
                sh 'rm -rf .ci-venv || true'
            }
        }
    }
}
