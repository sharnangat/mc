#!/usr/bin/env bash
# Runs on the Jenkins agent (not the target). Looks up a DigitalOcean droplet
# by name and creates it only if it doesn't already exist - idempotent, so
# running this against an already-provisioned server just finds it and does
# nothing destructive.
#
# Prints ONLY the droplet's public IPv4 address to stdout (no trailing
# newline) on success - all progress/diagnostic output goes to stderr so a
# caller can safely capture just the IP. Exits non-zero on failure.
set -euo pipefail

DO_API_TOKEN="${DO_API_TOKEN:?DO_API_TOKEN is required}"
DROPLET_NAME="${DROPLET_NAME:?DROPLET_NAME is required}"
DROPLET_REGION="${DROPLET_REGION:-blr1}"
DROPLET_SIZE="${DROPLET_SIZE:-s-1vcpu-1gb}"
DROPLET_IMAGE="${DROPLET_IMAGE:-ubuntu-24-04-x64}"
DO_SSH_KEY_ID="${DO_SSH_KEY_ID:?DO_SSH_KEY_ID is required - fingerprint or numeric ID of an SSH key already uploaded to your DO account}"

API="https://api.digitalocean.com/v2"
AUTH_HEADER="Authorization: Bearer ${DO_API_TOKEN}"

echo "==> Looking for an existing droplet named ${DROPLET_NAME}" >&2
EXISTING=$(curl -sf -H "$AUTH_HEADER" "${API}/droplets?name=${DROPLET_NAME}")
DROPLET_ID=$(echo "$EXISTING" | python3 -c "import json,sys; d=json.load(sys.stdin)['droplets']; print(d[0]['id'] if d else '')")

if [ -z "$DROPLET_ID" ]; then
    echo "==> Not found - creating a new droplet" >&2
    CREATED=$(curl -sf -X POST -H "$AUTH_HEADER" -H "Content-Type: application/json" \
      -d "{\"name\":\"${DROPLET_NAME}\",\"region\":\"${DROPLET_REGION}\",\"size\":\"${DROPLET_SIZE}\",\"image\":\"${DROPLET_IMAGE}\",\"ssh_keys\":[\"${DO_SSH_KEY_ID}\"]}" \
      "${API}/droplets")
    DROPLET_ID=$(echo "$CREATED" | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['id'])")
else
    echo "==> Found existing droplet, id ${DROPLET_ID}" >&2
fi

echo "==> Waiting for droplet ${DROPLET_ID} to become active with a public IP" >&2
for _ in $(seq 1 60); do
    INFO=$(curl -sf -H "$AUTH_HEADER" "${API}/droplets/${DROPLET_ID}")
    STATUS=$(echo "$INFO" | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['status'])")
    if [ "$STATUS" = "active" ]; then
        IP=$(echo "$INFO" | python3 -c "
import json, sys
d = json.load(sys.stdin)['droplet']
v4 = [n['ip_address'] for n in d['networks']['v4'] if n['type'] == 'public']
print(v4[0] if v4 else '')
")
        if [ -n "$IP" ]; then
            printf '%s' "$IP"
            exit 0
        fi
    fi
    sleep 5
done

echo "ERROR: timed out waiting for droplet to become active" >&2
exit 1
