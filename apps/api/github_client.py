import os
import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

if not all([GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO]):
    raise RuntimeError("Missing one or more GitHub env vars")

_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

def get_issue(number: int) -> dict:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues/{number}"
    r = requests.get(url, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()

def list_issue_comments(number: int, limit: int = 10) -> list[dict]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues/{number}/comments"
    r = requests.get(url, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    comments = r.json()
    return comments[-limit:]
