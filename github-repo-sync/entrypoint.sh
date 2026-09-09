#!/bin/sh
set -eu

: "${GITHUB_USER:?GITHUB_USER env var is required}"
: "${HOMEPAGE_CONFIG:?HOMEPAGE_CONFIG env var is required}"
: "${HOMEPAGE_GROUP:?HOMEPAGE_GROUP env var is required}"

if [ -n "${PUID:-}" ] && [ -n "${PGID:-}" ] && command -v su-exec >/dev/null 2>&1; then
    echo "Running as PUID=${PUID} PGID=${PGID}"
    exec su-exec "${PUID}:${PGID}" python3 /app/webhook_server.py
else
    exec python3 /app/webhook_server.py
fi
