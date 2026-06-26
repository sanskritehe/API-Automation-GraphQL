"""
Jira Webhook Server
"""

import json
import os
import subprocess
import sys
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Jira Pipeline Webhook")

CONFLUENCE_SPACE    = os.getenv("CONFLUENCE_SPACE", "hpeteam2")
CONFLUENCE_PAGE     = os.getenv("CONFLUENCE_PAGE",  "API Development Guidelines")
BASE_BRANCH         = os.getenv("BASE_BRANCH",      "main")
COPILOT_ASSIGNEE    = os.getenv("COPILOT_ASSIGNEE", "").lower()

_SERVICE_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "service_groups.json")

# Deduplication set to lock active runs and prevent parallel race conditions
active_runs = set()


def load_service_groups() -> dict:
    with open(_SERVICE_GROUPS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_keyword(issue: dict) -> str | None:
    """
    Scan the ticket text for a keyword that matches a key in service_groups.json.
    Returns the first match, or None.
    """
    groups = load_service_groups()
    fields = issue.get("fields", {})
    text = " ".join([
        issue.get("key", ""),
        fields.get("summary", ""),
        fields.get("description", "") or "",
    ]).lower()
    for keyword in groups:
        if keyword in text:
            print(f"[webhook] Matched keyword '{keyword}'")
            return keyword
    return None


def run_pipeline(issue_key: str, keyword: str):
    if issue_key in active_runs:
        print(f"[webhook] Pipeline already active for {issue_key}. Skipping run.")
        return
    active_runs.add(issue_key)
    try:
        print(f"[webhook] Triggering pipeline for {issue_key} -> keyword='{keyword}'")
        result = subprocess.run(
            [
                sys.executable, "pipeline.py",
                "--ticket",           issue_key,
                "--confluence-space", CONFLUENCE_SPACE,
                "--confluence-page",  CONFLUENCE_PAGE,
                "--keyword",          keyword,
                "--base-branch",      BASE_BRANCH,
            ],
            cwd=os.path.dirname(__file__),
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"[webhook] Pipeline failed for {issue_key} (exit {result.returncode})")
        else:
            print(f"[webhook] Pipeline completed for {issue_key}")
    finally:
        active_runs.discard(issue_key)


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

    assignee = issue.get("fields", {}).get("assignee")
    if not assignee:
        return {"status": "ignored", "reason": "no assignee set"}

    if isinstance(assignee, dict):
        assignee_email = assignee.get("emailAddress", "").lower()
        assignee_name  = (assignee.get("displayName", "") or assignee.get("name", "")).lower()
    else:
        assignee_email = ""
        assignee_name  = str(assignee).lower()
    if COPILOT_ASSIGNEE and COPILOT_ASSIGNEE not in (assignee_email, assignee_name):
        return {"status": "ignored", "reason": f"assignee '{assignee_name}' is not the copilot agent"}

    # Allow the webhook payload to override keyword detection
    keyword = payload.get("keyword") or resolve_keyword(issue)
    if not keyword:
        groups = load_service_groups()
        return {
            "status": "ignored",
            "reason": "no matching service keyword found",
            "available_keywords": list(groups.keys()),
        }

    if issue_key in active_runs:
        print(f"[webhook] Received trigger for {issue_key} but a run is already active. Ignoring.")
        return {"status": "ignored", "reason": "pipeline run already in progress"}

    print(f"[webhook] Received: {issue_key} assigned to {assignee} -> keyword='{keyword}'")
    background_tasks.add_task(run_pipeline, issue_key, keyword)

    groups = load_service_groups()
    matched_repos = [e["repo"] for e in groups.get(keyword, [])]
    return {
        "status": "accepted",
        "ticket": issue_key,
        "keyword": keyword,
        "target_repos": matched_repos,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    print("[*] Starting Jira Webhook Server with automatic folder exclusions...")
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["app/*", "app/**/*", "**/app/*", "**/app/**/*", "resp*.txt", "judge*.txt"]
    )
