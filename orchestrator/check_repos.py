import os, requests, base64
from dotenv import load_dotenv
load_dotenv()
token = os.environ["GITHUB_TOKEN"]
headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

# Check Appointment-GraphQL app structure
r = requests.get("https://api.github.com/repos/sanskritehe/Appointment-GraphQL/contents/app", headers=headers)
print("Appointment-GraphQL/app:", [f["name"] for f in r.json()] if r.status_code == 200 else r.status_code)

# Check Jira tickets with updated endpoint
jira_domain = os.environ.get("JIRA_DOMAIN", "")
jira_email = os.environ.get("JIRA_EMAIL", "")
jira_token = os.environ.get("JIRA_API_TOKEN", "")
r = requests.get(
    f"{jira_domain}/rest/api/3/search/jql",
    auth=(jira_email, jira_token),
    params={"jql": "project=KAN ORDER BY created DESC", "maxResults": 10, "fields": "summary,status,key"}
)
if r.status_code == 200:
    issues = r.json().get("issues", [])
    print(f"\nRecent Jira tickets ({len(issues)}):")
    for i in issues:
        print(f"  {i['key']}: {i['fields']['summary']} [{i['fields']['status']['name']}]")
else:
    print(f"\nJira: {r.status_code} {r.text[:300]}")
