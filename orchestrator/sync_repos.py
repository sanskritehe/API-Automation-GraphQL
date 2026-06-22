"""
sync_repos.py — Auto-discover GitHub org repos and rebuild service_groups.json.

Queries the GitHub GraphQL API, infers service groups from repo naming patterns
defined in company_config.json, and writes the result to service_groups.json.

Usage:
    python sync_repos.py                 # uses company_config.json
    python sync_repos.py --dry-run       # print output, no file changes
    python sync_repos.py --org acme      # override org from CLI
"""

import argparse
import json
import os

from dotenv import load_dotenv

load_dotenv()

from api_clients.github import discover_org_repos

_COMPANY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "company_config.json")
_SERVICE_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "service_groups.json")

_ALL_OPS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def load_company_config() -> dict:
    with open(_COMPANY_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _infer_role(repo_name: str, db_suffixes: list[str]) -> str:
    name = repo_name.lower()
    return "database" if any(s.lower() in name for s in db_suffixes) else "api"


def _extract_keyword(repo_name: str, db_suffixes: list[str], api_suffixes: list[str]) -> str:
    """Strip role suffixes from a repo name to derive its service keyword."""
    name = repo_name.lower()
    # Try longest suffix first to avoid partial matches
    for suffix in sorted(db_suffixes + api_suffixes, key=len, reverse=True):
        if name.endswith(suffix.lower()):
            name = name[: -len(suffix)]
            break
    return name.strip("-_")


def build_service_groups(repos: list[dict], discovery_cfg: dict) -> dict:
    """
    Infer service_groups.json content from a list of repo dicts.
    Groups repos by keyword; classifies each as api or database by name pattern.
    Repos that don't match any suffix pattern are skipped.
    """
    db_suffixes = discovery_cfg.get("db_suffix_patterns", ["-db", "-database-service", "-database"])
    api_suffixes = discovery_cfg.get("api_suffix_patterns", ["-service", "-api"])

    groups: dict[str, list] = {}
    skipped = []
    for repo in repos:
        keyword = _extract_keyword(repo["name"], db_suffixes, api_suffixes)
        if not keyword or keyword == repo["name"].lower():
            skipped.append(repo["name"])
            continue
        role = _infer_role(repo["name"], db_suffixes)
        entry = {"repo": repo["name"], "role": role, "operations": _ALL_OPS}
        groups.setdefault(keyword, []).append(entry)

    if skipped:
        print(f"[sync] Skipped (no suffix match): {skipped}")

    # Sort: api before database within each group; groups alphabetically
    for key in groups:
        groups[key].sort(key=lambda e: (0 if e["role"] == "api" else 1))
    return dict(sorted(groups.items()))


def main():
    parser = argparse.ArgumentParser(description="Sync service_groups.json from GitHub org repos")
    parser.add_argument("--org", help="GitHub org to scan (overrides company_config.json)")
    parser.add_argument("--dry-run", action="store_true", help="Print result without writing files")
    args = parser.parse_args()

    cfg = load_company_config()
    org = args.org or cfg["github_org"]
    discovery_cfg = cfg.get("repo_discovery", {})

    print(f"[sync] Discovering repos in org '{org}' via GitHub GraphQL...")
    repos = discover_org_repos(org)
    print(f"[sync] Found {len(repos)} active repo(s):")
    for r in repos:
        print(f"  - {r['name']}  [{r['language'] or 'unknown'}]  (default branch: {r['default_branch']})")

    groups = build_service_groups(repos, discovery_cfg)
    output = json.dumps(groups, indent=2)

    print(f"\n[sync] Inferred {len(groups)} service group(s):")
    print(output)

    if args.dry_run:
        print("\n[sync] Dry-run — no files written.")
    else:
        with open(_SERVICE_GROUPS_PATH, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"\n[sync] Written → {_SERVICE_GROUPS_PATH}")


if __name__ == "__main__":
    main()
