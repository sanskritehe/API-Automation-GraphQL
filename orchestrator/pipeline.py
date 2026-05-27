"""
HPE AI-Assisted Dev Pipeline — Full end-to-end entry point.

Usage:
    python pipeline.py --ticket KAN-1 --confluence-space hpeteam2 --confluence-page "API Development Guidelines"

    # Optional: override the auto-detected service keyword
    python pipeline.py --ticket KAN-1 ... --keyword appointment

What it does:
    1. Fetch Jira ticket details
    2. Fetch Confluence API spec
    3. Detect HTTP method from ticket → fetch matching prompt template (GET/POST/PUT/DELETE)
    4. Auto-detect service keyword → load service_groups.json → filter repos by method
    5. Build prompt.md = template + ticket info + Confluence spec
    6. Run GitHub Copilot code generation + evaluation loop once (shared output)
    7. Fan out in parallel: for each matched repo, create branch + commit + open PR
"""

import argparse
import asyncio
import json
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from api_clients.jira import get_jira_issue, add_jira_comment
from api_clients.confluence import get_confluence_page
from api_clients.github import create_branch, commit_file, create_pr, get_file
from orchestrator import run_orchestrator

# Repo where the prompt templates live
PROMPTS_REPO   = os.getenv("PROMPTS_REPO", "sanskritehe/Appointment-Service")
PROMPTS_BRANCH = os.getenv("PROMPTS_BRANCH", "main")

_SERVICE_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "service_groups.json")

# Keywords used to detect HTTP method from ticket text
_METHOD_KEYWORDS = {
    "POST":   ["post", "create", "add", "register", "insert", "new"],
    "PATCH":  ["patch", "status", "partial"],
    "PUT":    ["put", "update", "edit", "modify", "change"],
    "DELETE": ["delete", "remove", "deactivate"],
    "GET":    ["get", "fetch", "list", "read", "retrieve", "show"],
}


def load_service_groups() -> dict:
    with open(_SERVICE_GROUPS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def match_repos(groups: dict, keyword: str, method: str) -> list[dict]:
    """
    Return repo entries from service_groups.json that match the keyword
    and allow the given HTTP method.
    Each entry: {"repo": "...", "role": "...", "operations": [...]}
    """
    entries = groups.get(keyword.lower(), [])
    return [e for e in entries if method in e.get("operations", [])]


def detect_http_method(ticket: dict) -> str:
    """Detect GET/POST/PUT/PATCH/DELETE from ticket text. Defaults to POST."""
    text = f"{ticket['summary']} {ticket['description']}".lower()
    # Literal method name is the most reliable signal — check first
    for method in ["PATCH", "DELETE", "PUT", "POST", "GET"]:
        if method.lower() in text:
            return method
    # Fall back to semantic keywords
    for method in ["PATCH", "DELETE", "PUT", "POST", "GET"]:
        if any(kw in text for kw in _METHOD_KEYWORDS.get(method, [])):
            return method
    return "POST"


def detect_service_keyword(ticket: dict, groups: dict) -> str | None:
    """
    Scan ticket summary + description for a keyword that matches a key
    in service_groups.json. Returns the first match, or None.
    """
    text = f"{ticket['summary']} {ticket['description']}".lower()
    for keyword in groups:
        if keyword in text:
            return keyword
    return None


def fetch_prompt_template(method: str) -> str:
    """Fetch the action-specific prompt template from GitHub."""
    path = f"prompts/{method}.md"
    print(f"  Fetching template: {PROMPTS_REPO}/{path}")
    try:
        return get_file(PROMPTS_REPO, path, PROMPTS_BRANCH)
    except Exception as e:
        print(f"  Warning: could not fetch {path} ({e}). Using fallback.")
        return f"# {method} Endpoint Implementation\n\nImplement the {method} endpoint as described below.\n"


def build_prompt(ticket: dict, spec: dict, template: str) -> str:
    """Combine the action-specific template with live Jira + Confluence data."""
    labels = ", ".join(ticket["labels"]) if ticket["labels"] else "none"
    return f"""{template}

---

## Live Context for This Ticket

### Jira Ticket: {ticket['key']}
**Summary:** {ticket['summary']}
**Status:** {ticket['status']}
**Priority:** {ticket['priority']}
**Labels:** {labels}
**URL:** {ticket['url']}

**Description:**
{ticket['description']}

---

### API Specification (from Confluence: {spec['title']})
**Source:** {spec['url']}

{spec['content']}
"""


async def deploy_to_repo(
    repo_cfg: dict,
    ticket: dict,
    spec: dict,
    feature_branch: str,
    prompt_content: str,
    final_code: str,
    base_branch: str,
    app_dir: str,
):
    """
    Create branch, commit all files, and open a PR in a single target repo.
    Runs in a thread pool so GitHub API calls don't block the event loop.
    """
    repo = repo_cfg["repo"]
    role = repo_cfg["role"]
    print(f"  [{role}] Deploying to {repo}...")

    loop = asyncio.get_event_loop()

    # Create feature branch
    await loop.run_in_executor(None, lambda: create_branch(repo, feature_branch, base_branch))

    # Commit prompt.md
    await loop.run_in_executor(None, lambda: commit_file(
        repo=repo,
        path="prompt.md",
        content=prompt_content,
        message=f"chore: add requirements prompt for {ticket['key']}",
        branch=feature_branch,
    ))

    # Commit generated_solution.md
    await loop.run_in_executor(None, lambda: commit_file(
        repo=repo,
        path="generated_solution.md",
        content=final_code,
        message=f"feat: auto-generated solution for {ticket['key']}",
        branch=feature_branch,
    ))

    # Commit all app/ source files
    for root, _, files in os.walk(app_dir):
        for filename in files:
            if filename.endswith(".pyc") or "__pycache__" in root:
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, os.path.dirname(app_dir)).replace("\\", "/")
            with open(abs_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            await loop.run_in_executor(None, lambda rp=rel_path, fc=file_content: commit_file(
                repo=repo,
                path=rp,
                content=fc,
                message=f"feat: add {rp} for {ticket['key']}",
                branch=feature_branch,
            ))
            print(f"    [{role}] Committed {rel_path}")

    # Open PR
    pr_url = await loop.run_in_executor(None, lambda: create_pr(
        repo=repo,
        title=f"[{ticket['key']}] {ticket['summary']} ({role})",
        body=(
            f"## Auto-generated solution\n\n"
            f"**Role:** `{role}`\n"
            f"**Jira:** {ticket['url']}\n"
            f"**Confluence spec:** {spec['url']}\n\n"
            f"Generated by the HPE AI-Assisted Dev Pipeline (GitHub Copilot for Generation & Evaluation)."
        ),
        head=feature_branch,
        base=base_branch,
    ))

    print(f"  [{role}] PR opened: {pr_url}")
    return {"repo": repo, "role": role, "pr_url": pr_url}


async def main():
    parser = argparse.ArgumentParser(description="HPE AI-Assisted Dev Pipeline")
    parser.add_argument("--ticket", required=True,
                        help="Jira issue key, e.g. KAN-1")
    parser.add_argument("--confluence-space", required=True,
                        help="Confluence space key, e.g. hpe-team2")
    parser.add_argument("--confluence-page", required=True,
                        help="Confluence page title (exact match)")
    parser.add_argument("--keyword",
                        help="Service group keyword (auto-detected from ticket if omitted)")
    parser.add_argument("--base-branch", default="main",
                        help="Base branch to branch off (default: main)")
    args = parser.parse_args()

    base_branch = args.base_branch

    # ------------------------------------------------------------------
    # Step 1: Fetch Jira ticket
    # ------------------------------------------------------------------
    print(f"\n[1/6] Fetching Jira ticket {args.ticket}...")
    ticket = get_jira_issue(args.ticket)
    print(f"  Summary : {ticket['summary']}")
    print(f"  Status  : {ticket['status']}")

    # ------------------------------------------------------------------
    # Step 2: Fetch Confluence spec
    # ------------------------------------------------------------------
    print(f"\n[2/6] Fetching Confluence page '{args.confluence_page}'...")
    spec = get_confluence_page(args.confluence_space, args.confluence_page)
    print(f"  Page : {spec['title']}")
    print(f"  URL  : {spec['url']}")

    # ------------------------------------------------------------------
    # Step 3: Detect method + resolve target repos from service_groups.json
    # ------------------------------------------------------------------
    print("\n[3/6] Resolving target repos...")
    groups = load_service_groups()
    method = detect_http_method(ticket)
    print(f"  Detected HTTP method: {method}")

    keyword = args.keyword or detect_service_keyword(ticket, groups)
    if not keyword:
        raise SystemExit(
            f"Could not auto-detect a service keyword from ticket text. "
            f"Pass --keyword explicitly. Available: {list(groups.keys())}"
        )
    print(f"  Service keyword: '{keyword}'")

    target_repos = match_repos(groups, keyword, method)
    if not target_repos:
        raise SystemExit(
            f"No repos in service_groups.json match keyword='{keyword}' + method={method}."
        )
    print(f"  Target repos ({len(target_repos)}):")
    for r in target_repos:
        print(f"    - {r['repo']}  [{r['role']}]")

    # ------------------------------------------------------------------
    # Step 4: Build prompt.md (once, shared across all repos)
    # ------------------------------------------------------------------
    print("\n[4/6] Building prompt.md...")
    template = fetch_prompt_template(method)
    prompt_content = build_prompt(ticket, spec, template)
    with open("prompt.md", "w", encoding="utf-8") as f:
        f.write(prompt_content)
    print(f"  Saved prompt.md (using {method}.md template)")

    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    feature_branch = f"feature/{args.ticket.lower()}-{method.lower()}-{run_id}"

    # ------------------------------------------------------------------
    # Step 5: Run Copilot generation + evaluation loop (once, shared)
    # ------------------------------------------------------------------
    print("\n[5/6] Running GitHub Copilot generation + Copilot evaluation loop...")
    app_dir = os.path.join(os.path.dirname(__file__), "app")
    final_code = await run_orchestrator(prompt_content, app_dir=app_dir)

    with open("generated_solution.md", "w", encoding="utf-8") as f:
        f.write(final_code)
    print("  Saved generated_solution.md locally")

    # ------------------------------------------------------------------
    # Step 6: Fan out — parallel branch + commit + PR across all target repos
    # ------------------------------------------------------------------
    print(f"\n[6/6] Opening PRs in parallel across {len(target_repos)} repo(s)...")
    results = await asyncio.gather(*[
        deploy_to_repo(
            repo_cfg=r,
            ticket=ticket,
            spec=spec,
            feature_branch=feature_branch,
            prompt_content=prompt_content,
            final_code=final_code,
            base_branch=base_branch,
            app_dir=app_dir,
        )
        for r in target_repos
    ])

    print("\n============================================")
    print(f"[+] Pipeline complete! {len(results)} PR(s) opened:")
    for res in results:
        print(f"    [{res['role']}] {res['repo']} → {res['pr_url']}")
    print("============================================\n")

    # Post a comment on the Jira ticket with all PR links
    pr_lines = "\n".join(f"[{r['role']}] {r['pr_url']}" for r in results)
    comment_body = (
        f"PR successfully completed.\n\n{pr_lines}"
    )
    print(f"[+] Adding comment to Jira ticket {args.ticket}...")
    add_jira_comment(args.ticket, comment_body)
    print(f"[+] Comment added to {args.ticket}.")


if __name__ == "__main__":
    asyncio.run(main())
