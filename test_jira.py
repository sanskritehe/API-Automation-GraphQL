import os
import requests
from dotenv import load_dotenv

# Load env variables from orchestrator directory
orchestrator_dir = os.path.join(os.path.dirname(__file__), "orchestrator")
load_dotenv(os.path.join(orchestrator_dir, ".env"))

domain = os.getenv("JIRA_DOMAIN", "https://hpe-team2.atlassian.net")
email = os.getenv("JIRA_EMAIL")
token = os.getenv("JIRA_API_TOKEN")

if not email or not token:
    print("[-] Please configure JIRA_EMAIL and JIRA_API_TOKEN in your orchestrator/.env file!")
    exit(1)

url = f"{domain}/rest/api/3/issue/KAN-17"
print(f"[!] Fetching {url}...")

r = requests.get(
    url,
    auth=(email, token)
)

print(f"[+] Status Code: {r.status_code}")
print(r.text[:500])
