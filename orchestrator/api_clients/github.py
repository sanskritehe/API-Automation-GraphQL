import base64
import os
import requests


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_url(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}"


def get_file(repo: str, path: str, branch: str = "main") -> str:
    """Return decoded file content from a GitHub repo."""
    url = f"{_repo_url(repo)}/contents/{path}"
    resp = requests.get(url, headers=_headers(), params={"ref": branch})
    resp.raise_for_status()
    encoded = resp.json().get("content", "")
    return base64.b64decode(encoded).decode("utf-8")


def create_branch(repo: str, branch: str, base: str = "main"):
    """Create a new branch from base. Silently continues if branch already exists."""
    ref_url = f"{_repo_url(repo)}/git/ref/heads/{base}"
    resp = requests.get(ref_url, headers=_headers())
    resp.raise_for_status()
    sha = resp.json()["object"]["sha"]

    create_url = f"{_repo_url(repo)}/git/refs"
    payload = {"ref": f"refs/heads/{branch}", "sha": sha}
    resp = requests.post(create_url, json=payload, headers=_headers())
    if resp.status_code == 422:
        print(f"  Branch '{branch}' already exists, continuing...")
        return
    resp.raise_for_status()


def commit_file(repo: str, path: str, content: str, message: str, branch: str):
    """Create or update a file on a branch."""
    url = f"{_repo_url(repo)}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    existing_sha = None
    check = requests.get(url, headers=_headers(), params={"ref": branch})
    if check.status_code == 200:
        existing_sha = check.json().get("sha")

    payload = {"message": message, "content": encoded, "branch": branch}
    if existing_sha:
        payload["sha"] = existing_sha

    resp = requests.put(url, json=payload, headers=_headers())
    resp.raise_for_status()


def create_pr(repo: str, title: str, body: str, head: str, base: str = "main") -> str:
    """Open a pull request and return its HTML URL. Returns existing PR URL if one already exists."""
    url = f"{_repo_url(repo)}/pulls"
    payload = {"title": title, "body": body, "head": head, "base": base}
    resp = requests.post(url, json=payload, headers=_headers())

    if resp.status_code == 422:
        # PR already exists for this branch — fetch and return its URL
        existing = requests.get(url, headers=_headers(), params={"head": f"{repo.split('/')[0]}:{head}", "state": "open"})
        existing.raise_for_status()
        prs = existing.json()
        if prs:
            print(f"  PR already exists: {prs[0]['html_url']}")
            return prs[0]["html_url"]

    resp.raise_for_status()
    return resp.json().get("html_url", "")
