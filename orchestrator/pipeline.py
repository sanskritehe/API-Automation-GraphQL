"""
HPE AI-Assisted Dev Pipeline — GraphQL 4-repo mode.

3-phase execution:
  Phase 1 (parallel)    — fetch existing code from each GitHub repo
  Phase 2 (sequential)  — LLM code generation per repo (avoids Groq TPM limits)
  Phase 3 (parallel)    — create branch, commit files, open PR on each repo
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(override=True)

from api_clients.jira import get_jira_issue, add_jira_comment
from api_clients.confluence import get_confluence_page
from api_clients.github import create_branch, commit_file, create_pr, get_file, fetch_repo_files
from orchestrator import run_orchestrator, parse_generated_files

_COMPANY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "company_config.json")
_SERVICE_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "service_groups.json")

_METHOD_KEYWORDS = {
    "POST":   ["post", "create", "add", "register", "insert", "graphql mutation", "mutation"],
    "PATCH":  ["patch", "status", "partial"],
    "PUT":    ["put", "update", "edit", "modify", "change"],
    "DELETE": ["delete", "remove", "deactivate"],
    "GET":    ["get", "fetch", "list", "read", "retrieve", "show", "graphql query", "query"],
}


def load_company_config() -> dict:
    with open(_COMPANY_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_service_groups(org: str) -> dict:
    with open(_SERVICE_GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = json.load(f)
    for entries in groups.values():
        for entry in entries:
            if "/" not in entry["repo"]:
                entry["repo"] = f"{org}/{entry['repo']}"
    return groups


def match_repos(groups: dict, keyword: str, method: str) -> list[dict]:
    entries = groups.get(keyword.lower(), [])
    return [e for e in entries if method in e.get("operations", [])]


def detect_http_method(ticket: dict) -> str:
    text = f"{ticket['summary']} {ticket['description']}".lower()
    # Multi-word GraphQL phrases take highest priority
    for method in ["PATCH", "DELETE", "PUT", "POST", "GET"]:
        if any(kw in text for kw in _METHOD_KEYWORDS.get(method, []) if " " in kw):
            return method
    # Literal HTTP method word
    for method in ["PATCH", "DELETE", "PUT", "POST", "GET"]:
        if method.lower() in text:
            return method
    # Single-word keywords — GET before POST to avoid "new" stealing GETs
    for method in ["PATCH", "DELETE", "PUT", "GET", "POST"]:
        if any(kw in text for kw in _METHOD_KEYWORDS.get(method, []) if " " not in kw):
            return method
    return "POST"


def detect_service_keyword(ticket: dict, groups: dict) -> str | None:
    text = f"{ticket['summary']} {ticket['description']}".lower()
    for keyword in groups:
        if keyword in text:
            return keyword
    return None


def fetch_prompt_template(method: str, prompts_repo: str, prompts_branch: str) -> str:
    path = f"prompts/{method}.md"
    print(f"  Fetching template: {prompts_repo}/{path}")
    try:
        return get_file(prompts_repo, path, prompts_branch)
    except Exception as e:
        print(f"  Warning: could not fetch {path} ({e}). Using fallback.")
        return f"# {method} Endpoint Implementation\n\nImplement the {method} endpoint as described below.\n"


def build_prompt(ticket: dict, spec: dict, template: str) -> str:
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


# ---------------------------------------------------------------------------
# Phase 1 helper — fetch one repo's code
# ---------------------------------------------------------------------------

async def fetch_code_for_repo(repo: str, branch: str, role: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        code = await loop.run_in_executor(None, lambda: fetch_repo_files(repo, branch, role))
        print(f"  [fetch] {repo} ({role}) — {len(code)} chars")
        return code
    except Exception as e:
        print(f"  [fetch] {repo} — warning: {e}")
        return ""


# ---------------------------------------------------------------------------
# Phase 3 helper — commit generated files and open PR for one repo
# ---------------------------------------------------------------------------

async def commit_and_pr(
    repo_cfg: dict,
    ticket: dict,
    spec: dict,
    feature_branch: str,
    prompt_content: str,
    generated_code: str,
    base_branch: str,
) -> dict:
    repo  = repo_cfg["repo"]
    role  = repo_cfg["role"]
    loop  = asyncio.get_event_loop()

    generated_files = parse_generated_files(generated_code)

    # Create branch
    await loop.run_in_executor(None, lambda: create_branch(repo, feature_branch, base_branch))

    # Commit prompt.md
    await loop.run_in_executor(None, lambda: commit_file(
        repo=repo, path="prompt.md", content=prompt_content,
        message=f"chore: add requirements prompt for {ticket['key']}",
        branch=feature_branch,
    ))

    # Commit generated_solution.md
    await loop.run_in_executor(None, lambda: commit_file(
        repo=repo, path="generated_solution.md", content=generated_code,
        message=f"feat: auto-generated solution for {ticket['key']}",
        branch=feature_branch,
    ))

    # Commit each generated file
    for file_path, content in generated_files.items():
        await loop.run_in_executor(None, lambda fp=file_path, fc=content: commit_file(
            repo=repo, path=fp, content=fc,
            message=f"feat: {fp} for {ticket['key']} [{role}]",
            branch=feature_branch,
        ))
        print(f"    [{role}] Committed {file_path}")

    if not generated_files:
        print(f"    [{role}] No code files (datagraph config unchanged).")

    # Open PR
    files_list = "\n".join(f"- `{fp}`" for fp in generated_files) or "_No code changes._"
    pr_url = await loop.run_in_executor(None, lambda: create_pr(
        repo=repo,
        title=f"[{ticket['key']}] {ticket['summary']} ({role})",
        body=(
            f"## Auto-generated GraphQL solution\n\n"
            f"**Role:** `{role}`\n"
            f"**Jira:** {ticket['url']}\n"
            f"**Confluence spec:** {spec['url']}\n\n"
            f"### Files changed\n{files_list}\n\n"
            f"Generated by the HPE AI-Assisted Dev Pipeline (GraphQL 4-repo mode)."
        ),
        head=feature_branch,
        base=base_branch,
    ))
    print(f"  [{role}] PR opened: {pr_url}")
    return {"repo": repo, "role": role, "pr_url": pr_url}


# ---------------------------------------------------------------------------
# Phase 4 — clone datagraph repo, run rover supergraph compose, commit result
# ---------------------------------------------------------------------------

async def compose_supergraph(
    datagraph_repo: str,
    feature_branch: str,
    base_branch: str,
    ticket_key: str,
) -> bool:
    """
    Clone the datagraph feature branch, run `rover supergraph compose`, and
    commit the regenerated supergraph.graphql back to the feature branch.

    Returns True on success, False if rover is missing or compose fails.
    The datagraph repo's supergraph.yaml must list the running subgraph URLs
    (rover introspects them live), so services need to be reachable.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    clone_url = f"https://x-access-token:{token}@github.com/{datagraph_repo}.git"
    tmp_dir = tempfile.mkdtemp(prefix="datagraph-compose-")

    try:
        # Clone feature branch; fall back to base branch if it doesn't exist yet
        clone_result = subprocess.run(
            ["git", "clone", "--branch", feature_branch, "--depth", "1", clone_url, tmp_dir],
            capture_output=True, text=True,
        )
        if clone_result.returncode != 0:
            print(f"  [datagraph] Feature branch '{feature_branch}' not found, cloning '{base_branch}'...")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir = tempfile.mkdtemp(prefix="datagraph-compose-")
            subprocess.run(
                ["git", "clone", "--branch", base_branch, "--depth", "1", clone_url, tmp_dir],
                capture_output=True, text=True, check=True,
            )

        # Check rover is available
        rover_check = subprocess.run(
            ["rover", "--version"], capture_output=True, text=True,
        )
        if rover_check.returncode != 0:
            print("  [datagraph] WARNING: 'rover' CLI not found — skipping supergraph compose.")
            print("             Install from https://www.apollographql.com/docs/rover/getting-started/")
            print(f"             Then run: cd <datagraph-repo> && bash compose.sh")
            return False

        supergraph_yaml = os.path.join(tmp_dir, "supergraph.yaml")
        if not os.path.exists(supergraph_yaml):
            print("  [datagraph] WARNING: supergraph.yaml not found in datagraph repo — skipping compose.")
            return False

        print(f"  [datagraph] Running: rover supergraph compose --config supergraph.yaml")
        compose_result = subprocess.run(
            ["rover", "supergraph", "compose", "--config", "supergraph.yaml"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )

        if compose_result.returncode != 0:
            print(f"  [datagraph] rover compose failed (subgraph services may not be running):")
            print(f"             {compose_result.stderr.strip()}")
            print(f"             compose.sh has been committed — run it manually once services are up.")
            return False

        supergraph_content = compose_result.stdout
        print(f"  [datagraph] Compose succeeded — {len(supergraph_content)} chars generated.")

        # Commit supergraph.graphql to the feature branch
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: commit_file(
            repo=datagraph_repo,
            path="supergraph.graphql",
            content=supergraph_content,
            message=f"feat: regenerate supergraph.graphql for {ticket_key}",
            branch=feature_branch,
        ))
        print(f"  [datagraph] supergraph.graphql committed to '{feature_branch}'.")
        return True

    except subprocess.CalledProcessError as e:
        print(f"  [datagraph] Compose step failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="HPE AI Pipeline — GraphQL 4-repo mode")
    parser.add_argument("--ticket",           required=True)
    parser.add_argument("--confluence-space", default=None)
    parser.add_argument("--confluence-page",  default=None)
    parser.add_argument("--keyword",          default=None)
    parser.add_argument("--base-branch",      default=None)
    args = parser.parse_args()

    cfg              = load_company_config()
    org              = cfg["github_org"]
    base_branch      = args.base_branch or cfg.get("base_branch", "main")
    prompts_repo     = f"{org}/{cfg['prompts_repo']}"
    prompts_branch   = cfg.get("prompts_branch", "main")
    confluence_space = args.confluence_space or cfg["confluence_space"]
    confluence_page  = args.confluence_page  or cfg["confluence_page"]

    print(f"[config] org={org}  base={base_branch}  confluence={confluence_space}/{confluence_page}")

    # ── Step 1: Jira ──────────────────────────────────────────────────────
    print(f"\n[1/5] Fetching Jira ticket {args.ticket}...")
    ticket = get_jira_issue(args.ticket)
    print(f"  Summary : {ticket['summary']}")
    print(f"  Status  : {ticket['status']}")

    # ── Step 2: Confluence ────────────────────────────────────────────────
    print(f"\n[2/5] Fetching Confluence page '{confluence_page}'...")
    spec = get_confluence_page(confluence_space, confluence_page)
    print(f"  Page : {spec['title']}")

    # ── Step 3: Resolve repos ─────────────────────────────────────────────
    print("\n[3/5] Resolving target repos...")
    groups  = load_service_groups(org)
    method  = detect_http_method(ticket)
    print(f"  Detected HTTP method: {method}")

    keyword = args.keyword or detect_service_keyword(ticket, groups)
    if not keyword:
        raise SystemExit(
            f"Could not auto-detect service keyword. "
            f"Pass --keyword explicitly. Available: {list(groups.keys())}"
        )
    print(f"  Service keyword: '{keyword}'")

    target_repos = match_repos(groups, keyword, method)
    if not target_repos:
        raise SystemExit(f"No repos match keyword='{keyword}' + method={method}.")
    print(f"  Target repos ({len(target_repos)}):")
    for r in target_repos:
        print(f"    - {r['repo']}  [{r['role']}]")

    # ── Step 4: Build shared prompt ───────────────────────────────────────
    print("\n[4/5] Building prompt.md...")
    template       = fetch_prompt_template(method, prompts_repo, prompts_branch)
    prompt_content = build_prompt(ticket, spec, template)
    with open("prompt.md", "w", encoding="utf-8") as f:
        f.write(prompt_content)

    run_id         = datetime.now().strftime("%Y%m%d%H%M%S")
    feature_branch = f"feature/{args.ticket.lower()}-{method.lower()}-{run_id}"

    # ── Step 5: Three-phase execution ─────────────────────────────────────
    print(f"\n[5/5] Running 3-phase pipeline across {len(target_repos)} repos...")

    # Phase 1 — fetch existing code from all repos in parallel (role-filtered)
    print("\n  [Phase 1] Fetching existing repo code (parallel)...")
    existing_codes = await asyncio.gather(*[
        fetch_code_for_repo(r["repo"], base_branch, r["role"])
        for r in target_repos
    ])

    # Phase 2 — generate code for each repo SEQUENTIALLY (one Groq call at a time)
    # 10s gap between repos lets Groq's TPM window partially reset.
    print("\n  [Phase 2] Generating code (sequential — avoids Groq TPM limits)...")
    generated_results = []
    for i, (repo_cfg, existing_code) in enumerate(zip(target_repos, existing_codes)):
        if i > 0:
            await asyncio.sleep(10)
        role = repo_cfg["role"]
        print(f"\n  [{role}] Generating for {repo_cfg['repo']}...")
        generated_code = await run_orchestrator(
            prompt_content,
            role=role,
            existing_code=existing_code,
        )
        generated_results.append(generated_code)

    # Phase 3 — commit files and open PRs in parallel
    print("\n  [Phase 3] Committing files and opening PRs (parallel)...")
    results = await asyncio.gather(*[
        commit_and_pr(
            repo_cfg=r,
            ticket=ticket,
            spec=spec,
            feature_branch=feature_branch,
            prompt_content=prompt_content,
            generated_code=gen,
            base_branch=base_branch,
        )
        for r, gen in zip(target_repos, generated_results)
    ])

    # Phase 4 — compose supergraph (only runs if a datagraph repo is in scope)
    datagraph_cfg = next((r for r in target_repos if r.get("role") == "datagraph"), None)
    compose_ok = False
    if datagraph_cfg:
        print("\n  [Phase 4] Composing supergraph.graphql from updated subgraphs...")
        compose_ok = await compose_supergraph(
            datagraph_repo=datagraph_cfg["repo"],
            feature_branch=feature_branch,
            base_branch=base_branch,
            ticket_key=args.ticket,
        )
    else:
        print("\n  [Phase 4] No datagraph repo in scope — skipping supergraph compose.")

    print("\n" + "=" * 50)
    print(f"[+] Pipeline complete! {len(results)} PR(s) opened:")
    for res in results:
        print(f"    [{res['role']}] {res['repo']} → {res['pr_url']}")
    if datagraph_cfg:
        status = "composed + committed" if compose_ok else "SKIPPED (run compose.sh manually)"
        print(f"    [datagraph] supergraph.graphql: {status}")
    print("=" * 50 + "\n")

    supergraph_note = ""
    if datagraph_cfg:
        supergraph_note = (
            "\n\nsupergraph.graphql: recomposed automatically ✓"
            if compose_ok
            else "\n\nsupergraph.graphql: compose skipped — run compose.sh manually once subgraph services are up."
        )
    pr_lines = "\n".join(f"[{r['role']}] {r['pr_url']}" for r in results)
    add_jira_comment(args.ticket, f"GraphQL pipeline complete.\n\n{pr_lines}{supergraph_note}")
    print(f"[+] Comment added to {args.ticket}.")


if __name__ == "__main__":
    asyncio.run(main())
