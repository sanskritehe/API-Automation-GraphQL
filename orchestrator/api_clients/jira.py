import os
import requests
from requests.auth import HTTPBasicAuth


def get_jira_issue(issue_key: str) -> dict:
    """Fetch a Jira issue and return key fields as plain text."""
    domain = os.environ["JIRA_DOMAIN"]
    email = os.environ["JIRA_EMAIL"]
    token = os.environ["JIRA_API_TOKEN"]

    url = f"{domain}/rest/api/3/issue/{issue_key}"
    resp = requests.get(url, auth=HTTPBasicAuth(email, token))
    resp.raise_for_status()
    data = resp.json()

    fields = data.get("fields", {})
    return {
        "key": data["key"],
        "summary": fields.get("summary", ""),
        "description": _parse_description(fields.get("description")),
        "status": fields.get("status", {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "labels": fields.get("labels", []),
        "url": f"{domain}/browse/{data['key']}",
    }


def add_jira_comment(issue_key: str, body: str) -> None:
    """Post a plain-text comment on a Jira issue using ADF format."""
    domain = os.environ["JIRA_DOMAIN"]
    email = os.environ["JIRA_EMAIL"]
    token = os.environ["JIRA_API_TOKEN"]

    url = f"{domain}/rest/api/3/issue/{issue_key}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}]
                }
            ]
        }
    }
    resp = requests.post(url, json=payload, auth=HTTPBasicAuth(email, token))
    resp.raise_for_status()


def _parse_description(desc) -> str:
    """Convert Atlassian Document Format (ADF) to plain text."""
    if not desc:
        return ""
    if isinstance(desc, str):
        return desc

    texts = []

    def extract(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                extract(child)
        elif isinstance(node, list):
            for item in node:
                extract(item)

    extract(desc)
    return " ".join(t for t in texts if t.strip())
