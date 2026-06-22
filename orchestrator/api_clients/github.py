import base64
import os
import requests

_GRAPHQL_URL = "https://api.github.com/graphql"

_DISCOVER_REPOS_QUERY = """
query DiscoverRepos($org: String!, $cursor: String) {
  organization(login: $org) {
    repositories(first: 50, after: $cursor, orderBy: {field: NAME, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isArchived
        defaultBranchRef { name }
        primaryLanguage { name }
      }
    }
  }
}
"""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_url(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}"


def graphql_query(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL (v4) query and return the data payload."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(_GRAPHQL_URL, json=payload, headers=_headers())
    resp.raise_for_status()
    result = resp.json()
    if "errors" in result:
        raise RuntimeError(f"GitHub GraphQL errors: {result['errors']}")
    return result.get("data", {})


def discover_org_repos(org: str) -> list[dict]:
    """
    Return all non-archived repos for a GitHub org or personal account via REST API.
    Each item: {"name": str, "default_branch": str, "language": str | None}
    Handles pagination automatically; works for both orgs and personal accounts.
    """
    repos = []
    page = 1
    while True:
        # Try org endpoint first; fall back to user endpoint for personal accounts
        resp = requests.get(
            f"https://api.github.com/orgs/{org}/repos",
            headers=_headers(),
            params={"per_page": 50, "page": page, "type": "all"},
        )
        if resp.status_code in (404, 403):
            resp = requests.get(
                f"https://api.github.com/users/{org}/repos",
                headers=_headers(),
                params={"per_page": 50, "page": page},
            )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for r in batch:
            if not r.get("archived"):
                repos.append({
                    "name": r["name"],
                    "default_branch": r.get("default_branch", "main"),
                    "language": r.get("language"),
                })
        page += 1
    return repos


def get_file(repo: str, path: str, branch: str = "main") -> str:
    """Return decoded file content from a GitHub repo."""
    url = f"{_repo_url(repo)}/contents/{path}"
    resp = requests.get(url, headers=_headers(), params={"ref": branch})
    resp.raise_for_status()
    encoded = resp.json().get("content", "")
    return base64.b64decode(encoded).decode("utf-8")


_TEXT_EXTENSIONS = {".py", ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh"}

# Per-role file path patterns — only files matching these are included in the context.
# Keeps token usage within Groq's 12K TPM free-tier limit.
_ROLE_FILE_PATTERNS: dict[str, list[str]] = {
    "api": [
        "graphql_schema.py",
        "app/routes/appointments.py",
        "app/services/booking_service.py",
        "app/models.py",
        "requirements.txt",
    ],
    "database": [
        "graphql_schema.py",
        "app/models.py",
        "app/database.py",
        "app/main.py",
        "requirements.txt",
    ],
    "gateway": [
        "app/routes/appointments.py",
        "app/graphql_client.py",
        "app/main.py",
        "requirements.txt",
    ],
    "datagraph": [
        "router.yaml",
        "supergraph.yaml",
        "docker-compose.yml",
        "compose.sh",
    ],
}


def fetch_repo_files(repo: str, branch: str = "main", role: str = "") -> str:
    """
    Fetch relevant text files from a GitHub repo, filtered by role to keep token usage low.
    Returns formatted ### FILE: blocks.
    If role is empty or unrecognised, fetches all text files (capped at 8K chars total).
    """
    allowed = _ROLE_FILE_PATTERNS.get(role, [])

    ref_resp = requests.get(f"{_repo_url(repo)}/git/ref/heads/{branch}", headers=_headers())
    ref_resp.raise_for_status()
    sha = ref_resp.json()["object"]["sha"]

    tree_resp = requests.get(
        f"{_repo_url(repo)}/git/trees/{sha}",
        headers=_headers(),
        params={"recursive": "1"},
    )
    tree_resp.raise_for_status()
    tree = tree_resp.json().get("tree", [])

    blocks = []
    total_chars = 0
    char_cap = 12_000  # ~3K tokens — leaves plenty of room for prompt + response

    for item in tree:
        if item["type"] != "blob":
            continue
        path = item["path"]
        if "__pycache__" in path or path.endswith(".pyc"):
            continue

        # Role-based filter: skip files not in the allowed list
        if allowed and path not in allowed:
            continue

        # Generic fallback: extension filter
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        if not allowed and ext not in _TEXT_EXTENSIONS:
            continue

        if total_chars >= char_cap:
            break
        try:
            content = get_file(repo, path, branch)
        except Exception:
            continue

        lang = "python" if ext == ".py" else "yaml" if ext in {".yaml", ".yml"} else ""
        block = f"### FILE: {path}\n```{lang}\n{content}\n```"
        blocks.append(block)
        total_chars += len(block)

    return "\n\n".join(blocks)


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
