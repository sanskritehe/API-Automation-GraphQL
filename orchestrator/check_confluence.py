import os, requests, re
from dotenv import load_dotenv
load_dotenv()

domain = os.environ["CONFLUENCE_DOMAIN"]
email = os.environ["CONFLUENCE_EMAIL"]
token = os.environ["CONFLUENCE_API_TOKEN"]
auth = (email, token)

# Check all spaces' pages
for space_key in ["SD", "~71202046a5693ef7834f62afe3bad6ad83fef8", "~60cb5a41dae56700688ad58a"]:
    r = requests.get(f"{domain}/wiki/rest/api/content", auth=auth,
                     params={"spaceKey": space_key, "limit": 50, "type": "page",
                             "expand": "body.storage"})
    if r.status_code != 200:
        continue
    for p in r.json().get("results", []):
        content = p.get("body", {}).get("storage", {}).get("value", "")
        text = re.sub(r"<[^>]+>", " ", content)[:200].strip()
        print(f"[{space_key}] '{p['title']}': {text[:120]}")
