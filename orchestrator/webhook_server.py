"""
Jira Webhook Server — GraphQL 4-repo pipeline trigger.
"""

import json
import os
import subprocess
import sys
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from dotenv import load_dotenv
from api_clients.jira import _parse_description

load_dotenv()

app = FastAPI(title="Jira Pipeline Webhook")

_COMPANY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "company_config.json")
_SERVICE_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "service_groups.json")


def load_company_config() -> dict:
    with open(_COMPANY_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_service_groups(org: str) -> dict:
    """Load service_groups.json and inject the org prefix into all repo names."""
    with open(_SERVICE_GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = json.load(f)
    for entries in groups.values():
        for entry in entries:
            if "/" not in entry["repo"]:
                entry["repo"] = f"{org}/{entry['repo']}"
    return groups


def resolve_keyword(issue: dict, groups: dict) -> str | None:
    fields = issue.get("fields", {})
    description = _parse_description(fields.get("description"))
    text = " ".join([
        issue.get("key", ""),
        fields.get("summary", ""),
        description,
    ]).lower()
    for keyword in groups:
        if keyword in text:
            print(f"[webhook] Matched keyword '{keyword}'")
            return keyword
    return None


def run_pipeline(issue_key: str, keyword: str, cfg: dict):
    print(f"[webhook] Triggering pipeline for {issue_key} → keyword='{keyword}'")
    result = subprocess.run(
        [
            sys.executable, "pipeline.py",
            "--ticket",  issue_key,
            "--keyword", keyword,
        ],
        cwd=os.path.dirname(__file__),
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"[webhook] Pipeline failed for {issue_key} (exit {result.returncode})")
    else:
        print(f"[webhook] Pipeline completed for {issue_key}")


def run_sync():
    print("[webhook] Running sync_repos.py...")
    result = subprocess.run(
        [sys.executable, "sync_repos.py"],
        cwd=os.path.dirname(__file__),
        capture_output=False,
    )
    if result.returncode != 0:
        print("[webhook] sync_repos failed")
    else:
        print("[webhook] sync_repos completed")


@app.post("/webhook")
async def jira_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.body()
        print(f"[webhook] Raw body: {body}")
        payload = await request.json()
    except Exception as e:
        print(f"[webhook] Parse error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    issue = payload.get("issue", {})
    issue_key = issue.get("key")

    if not issue_key:
        raise HTTPException(status_code=400, detail="No issue key found in payload")

    cfg = load_company_config()
    copilot_assignee = cfg.get("copilot_assignee", "").lower()

    assignee = issue.get("fields", {}).get("assignee")
    if not assignee:
        return {"status": "ignored", "reason": "no assignee set"}

    if isinstance(assignee, dict):
        assignee_email = assignee.get("emailAddress", "").lower()
        assignee_name  = (assignee.get("displayName", "") or assignee.get("name", "")).lower()
    else:
        assignee_email = ""
        assignee_name  = str(assignee).lower()
    if copilot_assignee and copilot_assignee not in (assignee_email, assignee_name):
        return {"status": "ignored", "reason": f"assignee '{assignee_name}' is not the copilot agent"}

    groups = load_service_groups(cfg["github_org"])
    keyword = payload.get("keyword") or resolve_keyword(issue, groups)
    if not keyword:
        return {
            "status": "ignored",
            "reason": "no matching service keyword found",
            "available_keywords": list(groups.keys()),
        }

    print(f"[webhook] Received: {issue_key} assigned to {assignee} → keyword='{keyword}'")
    background_tasks.add_task(run_pipeline, issue_key, keyword, cfg)

    matched_repos = [e["repo"] for e in groups.get(keyword, [])]
    return {
        "status": "accepted",
        "ticket": issue_key,
        "keyword": keyword,
        "target_repos": matched_repos,
    }


@app.post("/sync-repos")
async def sync_repos(background_tasks: BackgroundTasks):
    """Trigger a GitHub GraphQL repo discovery and rebuild service_groups.json."""
    background_tasks.add_task(run_sync)
    return {"status": "accepted", "message": "sync_repos started in background"}


@app.get("/health")
def health():
    cfg = load_company_config()
    groups = load_service_groups(cfg["github_org"])
    return {
        "status": "ok",
        "org": cfg["github_org"],
        "service_groups": {k: len(v) for k, v in groups.items()},
    }
