#!/bin/sh
#
# entrypoint.sh
#
# Runs github_repos_to_homepage.py once, then sleeps, forever - replacing
# the old Synology Task Scheduler cron job with a long-running container.
#
# Required env vars:
#   GITHUB_USER        GitHub username or org
#   HOMEPAGE_CONFIG    Path to services.yaml INSIDE the container
#                       (mount the real file to this path in docker-compose)
#   HOMEPAGE_GROUP     Group name to write repos under, e.g. "Repo List"
#
# Optional env vars:
#   GITHUB_TOKEN        GitHub PAT (recommended - 5000/hr vs 60/hr limit)
#   SYNC_INTERVAL_SECS  Seconds between runs (default: 3600 = 1 hour)
#   EXTRA_ARGS          Extra flags passed through as-is, e.g. "--show-stars --sort updated"

set -eu

GITHUB_USER="${GITHUB_USER:?GITHUB_USER env var is required}"
HOMEPAGE_CONFIG="${HOMEPAGE_CONFIG:?HOMEPAGE_CONFIG env var is required}"
HOMEPAGE_GROUP="${HOMEPAGE_GROUP:?HOMEPAGE_GROUP env var is required}"
SYNC_INTERVAL_SECS="${SYNC_INTERVAL_SECS:-3600}"
EXTRA_ARGS="${EXTRA_ARGS:---show-stars --sort updated}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S UTC')] $*"
}

log "github-repo-sync starting - user=${GITHUB_USER} group='${HOMEPAGE_GROUP}' interval=${SYNC_INTERVAL_SECS}s"

while true; do
    log "=== sync starting ==="
    # shellcheck disable=SC2086
    if python3 /app/github_repos_to_homepage.py \
        --user "${GITHUB_USER}" \
        --config "${HOMEPAGE_CONFIG}" \
        --group "${HOMEPAGE_GROUP}" \
        ${EXTRA_ARGS}; then
        log "=== sync finished OK ==="
    else
        status=$?
        log "=== sync FAILED (exit ${status}) - see error above ==="
    fi
    log "sleeping ${SYNC_INTERVAL_SECS}s until next sync"
    sleep "${SYNC_INTERVAL_SECS}"
done
