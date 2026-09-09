#!/usr/bin/env python3
"""
github_repos_to_homepage.py

Fetches a GitHub user's (or org's) repositories and writes them into a
gethomepage.dev `services.yaml` file as a group of bookmarks, one entry
per repo. Designed to be run on a schedule (cron) so the dashboard stays
in sync with your GitHub account automatically.

It only touches the ONE group you point it at (--group). Every other
group in services.yaml is left completely untouched, formatting and
comments included (it uses ruamel.yaml round-trip mode).

USAGE
-----
    python3 github_repos_to_homepage.py \\
        --user hello2ashu \\
        --config /path/to/services.yaml \\
        --group "GitHub Repos" \\
        --token "$GITHUB_TOKEN"

    # dry run - print the YAML that WOULD be written, don't touch the file
    python3 github_repos_to_homepage.py --user hello2ashu --dry-run

FIRST TIME SETUP
----------------
    pip install requests ruamel.yaml

A GitHub token is optional for public repos but strongly recommended:
unauthenticated requests are capped at 60/hour per IP, which is easy to
hit if the script runs on a cron and you also browse the API elsewhere.
A token bumps that to 5,000/hour. A classic token with no scopes checked
(public read-only) is enough for public repos; add `repo` scope if you
want private repos included too (and pass --include-private).
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

API_ROOT = "https://api.github.com"

# Simple brand-color map for a few common languages so repo icons aren't
# all identical. Falls back to plain GitHub icon when language is unknown
# or not in this table. Extend as you like.
LANGUAGE_COLORS = {
    "Python": "3776AB",
    "JavaScript": "F7DF1E",
    "TypeScript": "3178C6",
    "Go": "00ADD8",
    "Rust": "000000",
    "Java": "007396",
    "C++": "00599C",
    "C": "A8B9CC",
    "C#": "239120",
    "Shell": "89E051",
    "HTML": "E34F26",
    "CSS": "1572B6",
    "PHP": "777BB4",
    "Ruby": "CC342D",
    "Swift": "F05138",
    "Kotlin": "7F52FF",
}

# Repo names that correspond to actual self-hosted apps get that app's own
# icon (matching homepage's bundled icon set / dashboard-icons naming, i.e.
# just "<name>.png") instead of a plain GitHub icon - much more useful at a
# glance since you likely already recognize these icons from elsewhere on
# your dashboard. Repo name matching is case-insensitive. Override or add
# to this via --icon-map for anything not covered here.
KNOWN_APP_ICONS = {
    "dawarich": "dawarich.png",
    "karakeep": "karakeep.png",
    "linkwarden": "linkwarden.png",
    "bookorbit": "bookorbit.png",
    "airtrail": "airtrail.png",
    "trek": "trek.png",
    "trillium": "trilium.png",
    "ntop": "ntopng.png",
    "ntopng": "ntopng.png",
    "qbit": "qbittorrent.png",
    "qbittorrent": "qbittorrent.png",
    "bentopdf": "bentopdf.png",
    "convertx": "convertx.png",
    "synology": "synology.png",
    "dockhand": "dockhand.png",
}


def fetch_all_repos(owner, token, is_org, include_forks, include_archived, include_private):
    """Paginate through the GitHub API and return the full repo list."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if is_org:
        base_url = f"{API_ROOT}/orgs/{owner}/repos"
        params = {"per_page": 100, "type": "all" if include_private else "public"}
    else:
        if token:
            # /user/repos is the authenticated user and can include private
            # repos if include_private is set; /users/{owner}/repos is
            # public-only regardless of token.
            base_url = f"{API_ROOT}/user/repos" if include_private else f"{API_ROOT}/users/{owner}/repos"
            params = {"per_page": 100, "affiliation": "owner"} if include_private else {"per_page": 100}
        else:
            base_url = f"{API_ROOT}/users/{owner}/repos"
            params = {"per_page": 100}

    repos = []
    page = 1
    while True:
        params["page"] = page
        resp = requests.get(base_url, headers=headers, params=params, timeout=30)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            print("GitHub API rate limit hit. Pass --token to raise the limit.", file=sys.stderr)
            sys.exit(1)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    if not include_forks:
        repos = [r for r in repos if not r.get("fork")]
    if not include_archived:
        repos = [r for r in repos if not r.get("archived")]
    if not include_private:
        repos = [r for r in repos if not r.get("private")]

    return repos


def sort_repos(repos, sort_by):
    if sort_by == "stars":
        repos.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
    elif sort_by == "name":
        repos.sort(key=lambda r: r["name"].lower())
    else:  # updated (default) - GitHub already returns most-recent-first for /repos,
        repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    return repos


def resolve_icon(repo_name, language, icon_overrides):
    """Icon resolution order: user's --icon-map override > known self-hosted
    app icon (matched by repo name) > language-colored GitHub icon."""
    name_lower = repo_name.lower()

    if icon_overrides and name_lower in icon_overrides:
        return icon_overrides[name_lower]

    if name_lower in KNOWN_APP_ICONS:
        return KNOWN_APP_ICONS[name_lower]

    color = LANGUAGE_COLORS.get(language, "181717")  # 181717 = GitHub's own black
    return f"si-github-#{color}"


def build_entry(repo, show_stars, icon_overrides=None):
    description = repo.get("description") or "No description"
    if show_stars:
        stars = repo.get("stargazers_count", 0)
        description = f"{description} · \u2605 {stars}"

    icon = resolve_icon(repo["name"], repo.get("language"), icon_overrides)

    attrs = CommentedMap()
    attrs["href"] = repo["html_url"]
    attrs["description"] = description
    attrs["icon"] = icon
    return {repo["name"]: attrs}


def load_or_create_config(path):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=2, offset=0)
    # Long URLs / API keys/tokens must never be soft-wrapped onto a second
    # line - a wrapped plain scalar gets a newline folded into a space by
    # the YAML spec, which silently corrupts the value. A very large width
    # disables wrapping in practice.
    yaml.width = 100000
    if os.path.exists(path):
        with open(path, "r") as f:
            data = yaml.load(f)
        if data is None:
            data = CommentedSeq()
    else:
        data = CommentedSeq()
    return yaml, data


def upsert_group(data, group_name, entries):
    """Replace the list under `group_name` if it exists, else append a new
    top-level group. `data` is the top-level CommentedSeq of {group: [...]}."""
    new_seq = CommentedSeq()
    new_seq.extend(entries)

    for item in data:
        if isinstance(item, dict) and group_name in item:
            item[group_name] = new_seq
            return data

    data.append({group_name: new_seq})
    return data


def load_icon_overrides(path):
    if not path:
        return {}
    if not os.path.exists(path):
        print(f"ERROR: --icon-map file not found: {path}", file=sys.stderr)
        sys.exit(1)

    yaml = YAML(typ="safe")
    with open(path) as f:
        raw = yaml.load(f) or {}

    if not isinstance(raw, dict):
        print(f"ERROR: --icon-map file must contain a flat mapping of repo_name: icon, got {type(raw).__name__}",
              file=sys.stderr)
        sys.exit(1)

    return {str(k).lower(): str(v) for k, v in raw.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", required=True, help="GitHub username or org name")
    p.add_argument("--org", action="store_true", help="Treat --user as an organization, not a personal account")
    p.add_argument("--config", default="services.yaml", help="Path to homepage's services.yaml (default: ./services.yaml)")
    p.add_argument("--group", default="GitHub Repos", help="Group/section name to write repos under (default: 'GitHub Repos')")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
                    help="GitHub personal access token (or set GITHUB_TOKEN / GH_TOKEN env var)")
    p.add_argument("--sort", choices=["updated", "stars", "name"], default="updated", help="Sort order (default: updated)")
    p.add_argument("--limit", type=int, default=0, help="Max number of repos to include (0 = no limit)")
    p.add_argument("--include-forks", action="store_true", help="Include forked repos (excluded by default)")
    p.add_argument("--include-archived", action="store_true", help="Include archived repos (excluded by default)")
    p.add_argument("--include-private", action="store_true", help="Include private repos (requires a token with 'repo' scope)")
    p.add_argument("--show-stars", action="store_true", help="Append star count to each repo's description")
    p.add_argument("--icon-map", default=None,
                    help="Path to a JSON or YAML file of {repo_name: icon} overrides, applied on top of the "
                         "built-in known-app icons. Repo name matching is case-insensitive.")
    p.add_argument("--dry-run", action="store_true", help="Print the resulting YAML instead of writing to --config")
    args = p.parse_args()

    if os.sep in args.group or args.group.lower().endswith((".yaml", ".yml")):
        print(
            f"ERROR: --group value '{args.group}' looks like a file path, not a display name.\n"
            f"This usually means --config's value got passed to --group by mistake "
            f"(or vice versa). Expected something like 'GitHub Repos' or 'Repo List'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.include_private and not args.token:
        print("Warning: --include-private has no effect without --token", file=sys.stderr)

    icon_overrides = load_icon_overrides(args.icon_map)

    repos = fetch_all_repos(
        owner=args.user,
        token=args.token,
        is_org=args.org,
        include_forks=args.include_forks,
        include_archived=args.include_archived,
        include_private=args.include_private,
    )
    repos = sort_repos(repos, args.sort)
    if args.limit:
        repos = repos[: args.limit]

    if not repos:
        print("No repositories found matching the given filters — leaving config untouched.", file=sys.stderr)
        sys.exit(1)

    entries = [build_entry(r, args.show_stars, icon_overrides) for r in repos]

    config_dir = os.path.dirname(os.path.abspath(args.config)) or "."
    if not os.path.isdir(config_dir):
        print(
            f"ERROR: the folder '{config_dir}' doesn't exist, so '{args.config}' can't be written.\n"
            f"Double-check --config points at the real path to your homepage services.yaml "
            f"(e.g. it might be /volume1/docker/homepage/services.yaml rather than a 'config' subfolder).",
            file=sys.stderr,
        )
        sys.exit(1)

    yaml, data = load_or_create_config(args.config)
    data = upsert_group(data, args.group, entries)

    if args.dry_run:
        yaml.dump(data, sys.stdout)
        return

    # Write atomically: build in a temp file, then replace, so a crashed
    # run never leaves services.yaml half-written.
    tmp_path = args.config + ".tmp"
    with open(tmp_path, "w") as f:
        yaml.dump(data, f)
    os.replace(tmp_path, args.config)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] Wrote {len(entries)} repo(s) to group '{args.group}' in {args.config}")


if __name__ == "__main__":
    main()
