from dotenv import load_dotenv
load_dotenv()

import os
import requests
from fastapi import FastAPI, HTTPException

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

if not all([GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO]):
    raise RuntimeError("Missing one or more GitHub env vars")

app = FastAPI(title="Devin GitHub Sanity Check")

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/issues")
def list_issues():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues"
    r = requests.get(url, headers=HEADERS, params={"state": "open"})

    if r.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"GitHub API error: {r.status_code} {r.text}",
        )

    issues = []
    for i in r.json():
        if "pull_request" in i:
            continue  # skip PRs
        issues.append({
            "number": i["number"],
            "title": i["title"],
            "labels": [l["name"] for l in i["labels"]],
            "updated_at": i["updated_at"],
        })

    return issues
