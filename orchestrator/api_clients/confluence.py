import os
import re
import requests
from requests.auth import HTTPBasicAuth


def get_confluence_page(space_key: str, title: str) -> dict:
    """Fetch a Confluence page by space + title and return plain text content."""
    domain = os.environ["CONFLUENCE_DOMAIN"]
    email = os.environ["CONFLUENCE_EMAIL"]
    token = os.environ["CONFLUENCE_API_TOKEN"]

    url = f"{domain}/wiki/rest/api/content"
    params = {
        "spaceKey": space_key,
        "title": title,
        "expand": "body.storage",
    }
    resp = requests.get(url, params=params, auth=HTTPBasicAuth(email, token))
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        raise ValueError(f"No Confluence page found: '{title}' in space '{space_key}'")

    page = results[0]
    html = page.get("body", {}).get("storage", {}).get("value", "")
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", plain).strip()

    return {
        "title": page.get("title", ""),
        "spaceKey": space_key,
        "content": plain,
        "url": f"{domain}/wiki{page.get('_links', {}).get('webui', '')}",
    }
