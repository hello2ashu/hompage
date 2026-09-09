#!/usr/bin/env python3
"""
webhook_server.py

Runs github_repos_to_homepage.py on a schedule (same as before), AND exposes
a POST /webhook endpoint that a GitHub App can call the instant a new repo
is created, triggering an immediate sync instead of waiting for the next
scheduled interval.

Required env vars:
  GITHUB_USER        GitHub username or org
  HOMEPAGE_CONFIG    Path to services.yaml inside the container
  HOMEPAGE_GROUP     Group name to write repos under, e.g. "Repo List"

Optional env vars:
  GITHUB_TOKEN            GitHub PAT for the sync script itself
  SYNC_INTERVAL_SECS      Seconds between scheduled runs (default 3600)
  EXTRA_ARGS              Extra CLI flags passed to the sync script
  WEBHOOK_PORT            Port to listen on for GitHub webhooks (default 8000)
  GITHUB_WEBHOOK_SECRET   Shared secret configured on the GitHub App's webhook.
                          Strongly recommended - without it, anyone who finds
                          the URL can trigger a sync (low risk, but still).
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GITHUB_USER = os.environ["GITHUB_USER"]
HOMEPAGE_CONFIG = os.environ["HOMEPAGE_CONFIG"]
HOMEPAGE_GROUP = os.environ["HOMEPAGE_GROUP"]
SYNC_INTERVAL_SECS = int(os.environ.get("SYNC_INTERVAL_SECS", "3600"))
EXTRA_ARGS = os.environ.get("EXTRA_ARGS", "--show-stars --sort updated").split()
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8000"))
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# Events that mean "the repo list changed and should be re-synced"
REPO_LIST_CHANGING_ACTIONS = {
    "created", "deleted", "renamed", "transferred", "archived", "unarchived",
    "privatized", "publicized",
}

wake_event = threading.Event()
sync_lock = threading.Lock()


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def run_sync():
    if not sync_lock.acquire(blocking=False):
        log("sync already in progress, skipping duplicate trigger")
        return
    try:
        log("=== sync starting ===")
        cmd = [
            sys.executable, "/app/github_repos_to_homepage.py",
            "--user", GITHUB_USER,
            "--config", HOMEPAGE_CONFIG,
            "--group", HOMEPAGE_GROUP,
            *EXTRA_ARGS,
        ]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            log("=== sync finished OK ===")
        else:
            log(f"=== sync FAILED (exit {result.returncode}) ===")
    finally:
        sync_lock.release()


def sync_loop():
    log(
        f"github-repo-sync starting - user={GITHUB_USER} group='{HOMEPAGE_GROUP}' "
        f"interval={SYNC_INTERVAL_SECS}s webhook_port={WEBHOOK_PORT}"
    )
    while True:
        run_sync()
        log(f"waiting up to {SYNC_INTERVAL_SECS}s (or an incoming webhook) for next sync")
        woken_early = wake_event.wait(timeout=SYNC_INTERVAL_SECS)
        wake_event.clear()
        if woken_early:
            log("woken early by webhook")


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log("http: " + (fmt % args))

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, b"ok")
        else:
            self._respond(404, b"not found")

    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, b"not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if WEBHOOK_SECRET:
            signature = self.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(
                WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                log("webhook: bad signature, rejecting request")
                self._respond(401, b"bad signature")
                return
        else:
            log("webhook: WARNING - GITHUB_WEBHOOK_SECRET not set, accepting unverified request")

        event = self.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if event == "ping":
            log("webhook: received GitHub ping - setup looks good")
            self._respond(200, b"pong")
            return

        action = payload.get("action")
        if event == "repository" and action in REPO_LIST_CHANGING_ACTIONS:
            repo_name = payload.get("repository", {}).get("full_name", "unknown")
            log(f"webhook: repository '{repo_name}' {action} - triggering immediate sync")
            threading.Thread(target=run_sync, daemon=True).start()
            wake_event.set()
            self._respond(200, b"sync triggered")
            return

        log(f"webhook: ignoring event='{event}' action='{action}'")
        self._respond(200, b"ignored")

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    threading.Thread(target=sync_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
    log(f"webhook listener up on :{WEBHOOK_PORT} (POST /webhook, GET /health)")
    server.serve_forever()


if __name__ == "__main__":
    main()
