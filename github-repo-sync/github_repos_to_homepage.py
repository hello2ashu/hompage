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
        --token "$GITHUB_TOKEN" \\
        --show-total

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
import re
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
#
# NOTE: this is a static guess at what exists in the Dashboard Icons
# project. Names there do change (renames, removals, new additions), so
# every candidate pulled from this map (or from --icon-map) is verified
# against the live CDN before use - see verify_or_fallback() below. If
# verification fails for any reason, it falls back to the colored GitHub
# icon rather than risking a broken image on the dashboard.
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

# gethomepage.dev resolves a bare icon name against Dashboard Icons, and
# recognizes three prefixed icon libraries on top of that - see
# https://gethomepage.dev/configs/services/#icons. Each has its own CDN and
# its own naming convention, so each gets its own existence check below
# rather than being trusted blindly. A candidate that isn't in any of
# these forms (a full URL, or a local /icons/... path) can't be verified
# from here and is used as-is.
DASHBOARD_ICON_CDN_BASES = [
    "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons",  # current
    "https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons",  # legacy mirror, in case of a lookup lag
]
MDI_ICON_URL = "https://cdn.jsdelivr.net/npm/@mdi/svg@latest/svg/{name}.svg"
SIMPLE_ICONS_URL = "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{name}.svg"
SELFHST_ICON_CDN_BASE = "https://cdn.jsdelivr.net/gh/selfhst/icons"

ICON_CHECK_TIMEOUT = 5
DASHBOARD_ICON_EXTS = ("png", "svg", "webp")  # gethomepage.dev defaults to png when none is given
SELFHST_ICON_EXTS = ("png", "svg", "webp")  # selfh.st also defaults to png when none is given

# mdi-XX and si-XX accept a "-#hexcolor" color-override suffix; strip it
# before checking the icon name itself against its source library.
_COLOR_SUFFIX_RE = re.compile(r"-#[0-9a-fA-F]{3,8}$")

_icon_exists_cache = {}
_icon_session = requests.Session()


def _url_exists(url):
    try:
        resp = _icon_session.head(url, timeout=ICON_CHECK_TIMEOUT, allow_redirects=True)
        return resp.status_code == 200
    except requests.RequestException:
        return False  # network hiccup or CDN move - treat as "couldn't verify"


def _cached(cache_key, check_fn):
    if cache_key in _icon_exists_cache:
        return _icon_exists_cache[cache_key]
    result = check_fn()
    _icon_exists_cache[cache_key] = result
    return result


def _split_ext(name, valid_exts, default_ext):
    """Split a trailing '.ext' off `name` if it's one of `valid_exts`;
    otherwise return `name` unchanged along with `default_ext` (matching
    what the dashboard would actually fetch when no extension is given)."""
    lower = name.lower()
    for ext in valid_exts:
        suffix = "." + ext
        if lower.endswith(suffix):
            return name[: -len(suffix)], ext
    return name, default_ext


def dashboard_icon_exists(candidate):
    bare_name, ext = _split_ext(candidate, DASHBOARD_ICON_EXTS, "png")

    def check():
        for cdn_base in DASHBOARD_ICON_CDN_BASES:
            if _url_exists(f"{cdn_base}/{ext}/{bare_name}.{ext}"):
                return True
        return False

    return _cached(("dashboard", bare_name, ext), check)


def mdi_icon_exists(name):
    name = _COLOR_SUFFIX_RE.sub("", name)
    return _cached(("mdi", name), lambda: _url_exists(MDI_ICON_URL.format(name=name)))


def simple_icon_exists(name):
    name = _COLOR_SUFFIX_RE.sub("", name)
    return _cached(("si", name), lambda: _url_exists(SIMPLE_ICONS_URL.format(name=name)))


def selfhst_icon_exists(candidate):
    bare_name, ext = _split_ext(candidate, SELFHST_ICON_EXTS, "png")
    return _cached(("sh", bare_name, ext), lambda: _url_exists(f"{SELFHST_ICON_CDN_BASE}/{ext}/{bare_name}.{ext}"))


def github_fallback_icon(language):
    """The always-valid fallback: GitHub's own simple-icons logo, tinted by
    the repo's primary language so repos are still visually distinguishable
    even without an app-specific icon."""
    color = LANGUAGE_COLORS.get(language, "181717")  # 181717 = GitHub's own black
    return f"si-github-#{color}"


def verify_or_fallback(candidate, language):
    if candidate.startswith(("http://", "https://", "/icons/")):
        return candidate  # can't (or shouldn't) verify a URL or a local icon from here

    if candidate.startswith("mdi-"):
        verified = mdi_icon_exists(candidate[len("mdi-"):])
    elif candidate.startswith("si-"):
        verified = simple_icon_exists(candidate[len("si-"):])
    elif candidate.startswith("sh-"):
        verified = selfhst_icon_exists(candidate[len("sh-"):])
    else:
        verified = dashboard_icon_exists(candidate)

    return candidate if verified else github_fallback_icon(language)


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
    app icon (matched by repo name) > language-colored GitHub icon. Any
    candidate pulled from the first two is verified against the live
    Dashboard Icons CDN before use (see verify_or_fallback)."""
    name_lower = repo_name.lower()

    if icon_overrides and name_lower in icon_overrides:
        return verify_or_fallback(icon_overrides[name_lower], language)

    if name_lower in KNOWN_APP_ICONS:
        return verify_or_fallback(KNOWN_APP_ICONS[name_lower], language)

    return github_fallback_icon(language)


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


def build_total_entry(user, total_count, shown_count):
    """A non-clickable-in-spirit summary entry placed at the top of the
    group so the total repo count is visible on the dashboard at a glance."""
    if shown_count < total_count:
        label = f"\U0001F4E6 Showing {shown_count} of {total_count} Repos"
    else:
        label = f"\U0001F4E6 {total_count} Repos"

    attrs = CommentedMap()
    attrs["href"] = f"https://github.com/{user}"
    attrs["description"] = "Total repositories synced from GitHub"
    attrs["icon"] = "si-github-#181717"
    return {label: attrs}


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
    p.add_argument("--show-total", action="store_true",
                    help="Add a summary entry at the top of the group showing the total repo count "
                         "(and how many are shown, if --limit truncated the list)")
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

    total_count = len(repos)  # before --limit clips the visible list
    if args.limit:
        repos = repos[: args.limit]

    if not repos:
        print("No repositories found matching the given filters — leaving config untouched.", file=sys.stderr)
        sys.exit(1)

    entries = [build_entry(r, args.show_stars, icon_overrides) for r in repos]

    if args.show_total:
        entries.insert(0, build_total_entry(args.user, total_count, len(repos)))

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
    print(f"[{ts}] Wrote {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
          f"({total_count} repo(s) total) to group '{args.group}' in {args.config}")


if __name__ == "__main__":
    main()
