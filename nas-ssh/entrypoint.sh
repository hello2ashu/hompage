#!/bin/bash
set -e

# Detect the Docker bridge gateway IP — this is always the NAS host's
# address as seen from inside this container, even if it changes.
GATEWAY_IP=$(ip route show default | awk '/default/ {print $3; exit}')

if [ -z "$GATEWAY_IP" ]; then
  echo "[entrypoint] ERROR: could not detect gateway IP" >&2
  exit 1
fi
echo "[entrypoint] Using NAS host IP: $GATEWAY_IP"

SSH_PORT="${SSH_PORT:-22}"
SSH_USER="${SSH_USER:-ashish}"
KNOWN_HOSTS=/tmp/known_hosts

# Scan the host key fresh each start against whatever the gateway IP
# turns out to be right now — no stale known_hosts file to maintain.
ssh-keyscan -p "$SSH_PORT" "$GATEWAY_IP" > "$KNOWN_HOSTS" 2>/dev/null

exec ttyd \
  -p 7681 \
  -c "${TTYD_USER}:${TTYD_PASS}" \
  --writable \
  -t titleFixed=NAS \
  --ping-interval 30 \
  ssh -tt -p "$SSH_PORT" -i /keys/id_ed25519 \
      -o UserKnownHostsFile="$KNOWN_HOSTS" \
      -o StrictHostKeyChecking=yes \
      "${SSH_USER}@${GATEWAY_IP}"
