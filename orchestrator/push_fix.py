"""Push the corrected routes/appointments.py to the 4 KAN-23 feature branches."""
import os, requests
from dotenv import load_dotenv
load_dotenv()
from api_clients.github import commit_file

FILE_PATH = os.path.join(os.path.dirname(__file__), "app", "routes", "appointments.py")
with open(FILE_PATH, "r", encoding="utf-8") as f:
    content = f.read()

repos_and_branches = [
    ("sanskritehe/Appointment-Service", None),
    ("sanskritehe/Appointment-Database-Service", None),
    ("VirajShankar/rest-api-gateway", None),
    ("VirajShankar/graphql-datagraph", None),
]

token = os.environ["GITHUB_TOKEN"]
headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

for repo, _ in repos_and_branches:
    r = requests.get(f"https://api.github.com/repos/{repo}/pulls",
                     headers=headers, params={"state": "open", "per_page": 5})
    if r.status_code != 200:
        print(f"  [{repo}] Could not fetch PRs: {r.status_code}")
        continue
    prs = r.json()
    if not prs:
        print(f"  [{repo}] No open PRs found")
        continue
    branch = prs[0]["head"]["ref"]
    print(f"  [{repo}] Pushing fix to branch: {branch}")
    try:
        commit_file(
            repo=repo,
            path="app/routes/appointments.py",
            content=content,
            message="fix: correct doubled route path /appointments/appointments → /appointments/book",
            branch=branch,
        )
        print(f"  [{repo}] ✓ Fixed")
    except Exception as e:
        print(f"  [{repo}] Error: {e}")
