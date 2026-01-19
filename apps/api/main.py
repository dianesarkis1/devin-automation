from dotenv import load_dotenv
load_dotenv()

from typing import Any
from github_client import get_issue, list_issue_comments
from devin_client import create_session, DevinRateLimitError, get_session
from store import init_db, get_triage, upsert_triage, get_exec, upsert_exec, get_verify, upsert_verify, DB_PATH


import os
import requests
import sqlite3
from fastapi import FastAPI, HTTPException, Request, Query
import traceback
from fastapi.responses import JSONResponse, HTMLResponse


TRIAGE_RUNS = {}
EXEC_RUNS = {}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

if not all([GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO]):
    raise RuntimeError("Missing one or more GitHub env vars")

app = FastAPI(title="Devin GitHub Sanity Check")

init_db()

@app.delete("/issues/{number}/cache")
def clear_issue_cache(number: int):
    """
    Clear saved triage/execute/verify for a given issue so the demo can start fresh.
    Does NOT delete the GitHub issue or PRs; only clears our local/persisted cache.
    """
    cleared = {"triage": False, "execute": False, "verify": False}

    # 1) In-memory caches (if you use them)
    global TRIAGE_RUNS, EXEC_RUNS
    if isinstance(globals().get("TRIAGE_RUNS"), dict) and number in TRIAGE_RUNS:
        TRIAGE_RUNS.pop(number, None)
        cleared["triage"] = True

    if isinstance(globals().get("EXEC_RUNS"), dict) and number in EXEC_RUNS:
        EXEC_RUNS.pop(number, None)
        cleared["execute"] = True

    # 2) Persisted caches (if you implemented get_/upsert_ with a store)
    try:
        if "delete_triage" in globals():
            cleared["triage"] = delete_triage(number) or cleared["triage"]
        if "delete_exec" in globals():
            cleared["execute"] = delete_exec(number) or cleared["execute"]
        if "delete_verify" in globals():
            cleared["verify"] = delete_verify(number) or cleared["verify"]
    except Exception:
        # Don't fail hard if persistence isn't configured
        pass

    return {"ok": True, "issue_number": number, "cleared": cleared}

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "traceback_tail": traceback.format_exc().splitlines()[-25:],
        },
    )

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

@app.get("/issues/{number}/triage")
def get_triage_record(number: int):
    record = get_triage(number)
    return record  # Returns None if not found, which is fine

def delete_triage(number: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM triage_runs WHERE issue_number = ?", (number,))
        conn.commit()
        return cur.rowcount > 0

def delete_exec(number: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM exec_runs WHERE issue_number = ?", (number,))
        conn.commit()
        return cur.rowcount > 0

def delete_verify(number: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM verify_runs WHERE issue_number = ?", (number,))
        conn.commit()
        return cur.rowcount > 0

@app.get("/devin/sessions/{session_id}")
def proxy_devin_session(session_id: str):
    # Simple pass-through; no secrets returned (your server is calling Devin API)
    return get_session(session_id)

@app.post("/issues/{number}/sync-exec")
def sync_exec_with_session(number: int):
    """
    Syncs the execution record with the latest Devin session data.
    Called by frontend polling to update PR URL and structured output.
    """
    exec_record = get_exec(number)
    if not exec_record:
        raise HTTPException(status_code=404, detail="No execution record found")

    session_id = exec_record.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="No session_id in execution record")

    # Fetch latest session data from Devin
    session = get_session(session_id)

    # Extract PR URL from session
    pr_url = None
    pull_request = session.get("pull_request")
    if isinstance(pull_request, dict):
        pr_url = pull_request.get("url")

    # Extract structured output
    structured_output = session.get("structured_output") or {}

    # Also check structured output for PR URL
    if not pr_url:
        pr_url = structured_output.get("pull_request_url")

    # Update the database
    upsert_exec(
        issue_number=number,
        session_id=session_id,
        session_url=exec_record.get("session_url"),
        structured_output=structured_output,
        pull_request_url=pr_url,
        session=session,
    )

    return {"ok": True, "synced": True, **get_exec(number)}

@app.post("/issues/{number}/sync-triage")
def sync_triage_with_session(number: int):
    """
    Syncs the triage record with the latest Devin session data.
    Called by frontend polling to update structured output.
    """
    triage_record = get_triage(number)
    if not triage_record:
        raise HTTPException(status_code=404, detail="No triage record found")

    session_id = triage_record.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="No session_id in triage record")

    # Fetch latest session data from Devin
    session = get_session(session_id)

    # Extract structured output
    structured_output = session.get("structured_output") or {}

    # Update the database
    upsert_triage(
        issue_number=number,
        session_id=session_id,
        session_url=triage_record.get("session_url"),
        structured_output=structured_output,
        session=session,
    )

    return {"ok": True, "synced": True, **get_triage(number)}

@app.post("/issues/{number}/sync-verify")
def sync_verify_with_session(number: int):
    """
    Syncs the verify record with the latest Devin session data.
    Called by frontend polling to update test results.
    """
    verify_record = get_verify(number)
    if not verify_record:
        raise HTTPException(status_code=404, detail="No verify record found")

    session_id = verify_record.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="No session_id in verify record")

    # Fetch latest session data from Devin
    session = get_session(session_id)

    # Extract structured output
    structured_output = session.get("structured_output") or {}

    # Update the database
    upsert_verify(
        issue_number=number,
        session_id=session_id,
        session_url=verify_record.get("session_url"),
        structured_output=structured_output,
        session=session,
    )

    return {"ok": True, "synced": True, **get_verify(number)}

@app.get("/issues/{number}/execute")
def get_execute_record(number: int):
    record = get_exec(number)
    return record  # Returns None if not found, which is fine

@app.get("/issues/{number}/verify")
def get_verify_record(number: int):
    record = get_verify(number)
    return record  # Returns None if not found, which is fine

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/issues/{number}/triage")
def triage_issue(number: int, force: bool = Query(False)):
    existing = get_triage(number)
    if existing and not force and existing.get("structured_output"):
        return {"cached": True, **existing}

    issue = get_issue(number)
    comments = list_issue_comments(number, limit=10)

    issue_text = issue.get("body") or ""
    comments_text = "\n\n".join(
        f"- {c.get('user', {}).get('login','unknown')}: {c.get('body','')}"
        for c in comments
    )

    schema = r"""
{
  "issue_summary": "string",
  "acceptance_criteria": ["string"],
  "confidence_score": 0.0,
  "confidence_rationale": "string",
  "key_risks": ["string"],
  "proposed_plan": [
    {"step": 1, "action": "string", "files": ["string"], "tests": ["string"]}
  ],
  "recommended_next_action": "execute|needs_human|needs_info",
  "questions_for_reporter": ["string"]
}
""".strip()

    prompt = f"""
You are Devin acting as an enterprise IT engineer. Triage the GitHub issue below.

Goals:
1) Summarize the issue and infer clear acceptance criteria.
2) Propose a concrete implementation plan (step-by-step).
3) Assign a confidence score from 0.0 to 1.0 for completing this ticket automatically.
4) Identify risks and any questions needed before execution.

IMPORTANT:
- Maintain the following JSON schema as STRUCTURED OUTPUT.
- Update structured output immediately after you determine acceptance criteria, the plan, and the confidence score.

STRUCTURED OUTPUT JSON SCHEMA:
{schema}

REPO: https://github.com/{os.getenv("GITHUB_OWNER")}/{os.getenv("GITHUB_REPO")}
ISSUE #{number}: {issue.get("title")}

ISSUE BODY:
{issue_text}

RECENT COMMENTS:
{comments_text}
""".strip()

    try:
        resp = create_session(
            prompt=prompt,
            title=f"Triage GH-{number}: {issue.get('title','')[:80]}",
            tags=["github", f"issue:{number}", "triage"],
        )
    except DevinRateLimitError as e:
        raise HTTPException(status_code=429, detail={"error": str(e), "retry_after_s": e.retry_after_s})

    session_id = resp["session_id"]
    session_url = resp.get("url")

    # Save initial triage record with session info
    upsert_triage(
        issue_number=number,
        session_id=session_id,
        session_url=session_url,
        structured_output={},
        session={"status_enum": "working"},
    )

    # Return early so the UI can show the session URL immediately
    # The frontend polling will update the record with structured output
    saved = get_triage(number)
    return {"cached": False, **saved}


@app.post("/issues/{number}/execute")
def execute_issue(number: int, force: bool = Query(False)):
    existing_exec = get_exec(number)
    if existing_exec and not force:
        pr = existing_exec.get("pull_request_url") or (existing_exec.get("structured_output") or {}).get("pull_request_url")
        if pr:
            return {"cached": True, **existing_exec}

    issue = get_issue(number)

    triage_record = get_triage(number)
    triage = (triage_record or {}).get("structured_output")

    if not triage:
        # Optional: auto-run triage once to make the flow seamless
        triage_response = triage_issue(number, force=False)
        triage = triage_response.get("structured_output") or (triage_response.get("structured_output") if isinstance(triage_response, dict) else None)

    if not triage:
        raise HTTPException(status_code=400, detail="No triage found for this issue. Run POST /issues/{number}/triage first.")

    owner = os.getenv("GITHUB_OWNER")
    repo = os.getenv("GITHUB_REPO")
    gh_token = os.getenv("GITHUB_TOKEN")

    if not all([owner, repo, gh_token]):
        return {"error": "Missing GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN in env."}

    repo_url = f"https://github.com/{owner}/{repo}.git"

    # Structured output schema for execute (keeps dashboard easy later)
    schema = """
{
  "result_summary": "string",
  "files_changed": ["string"],
  "tests_run": ["string"],
  "test_results": "string",
  "pull_request_url": "string",
  "confidence_score": 0.0,
  "notes_for_reviewer": ["string"]
}
""".strip()

    prompt = f"""
You are Devin. Implement the GitHub issue below end-to-end and open a PR.

Repo: {repo_url}
Issue #{number}: {issue.get("title")}

Context / triage JSON (do not change it; use it as plan input):
{triage}

Requirements:
- Create a new branch.
- Implement the fix.
- Update/add tests as needed.
- Run tests locally (pytest).
- Push the branch to GitHub and open a pull request to main.
- Include the PR link in STRUCTURED OUTPUT.

Authentication:
- You have a session secret named GITHUB_TOKEN.
- Use it to authenticate git + GitHub API.

Suggested git setup (one approach):
1) git clone {repo_url}
2) cd {repo}
3) git checkout -b devin/fix-issue-{number}
4) After committing, set remote using token (do NOT print the token):
   git remote set-url origin https://x-access-token:${{GITHUB_TOKEN}}@github.com/{owner}/{repo}.git
5) git push -u origin devin/fix-issue-{number}

To create a PR (one approach) using GitHub REST API:
- POST https://api.github.com/repos/{owner}/{repo}/pulls
- headers: Authorization: Bearer $GITHUB_TOKEN, Accept: application/vnd.github+json
- JSON: {{ "title": "...", "head": "devin/fix-issue-{number}", "base": "main", "body": "..." }}

IMPORTANT:
- Maintain the following JSON schema as STRUCTURED OUTPUT and populate it once the PR is created.

STRUCTURED OUTPUT JSON SCHEMA:
{schema}
""".strip()

    # Pass GitHub token as a session-scoped secret
    resp = create_session(
        prompt=prompt,
        title=f"Execute GH-{number}: {issue.get('title','')[:80]}",
        tags=["github", f"issue:{number}", "execute"],
        session_secrets=[
            {"key": "GITHUB_TOKEN", "value": gh_token, "sensitive": True}
        ],
    )

    session_id = resp["session_id"]
    session_url = resp.get("url")

    upsert_exec(
        issue_number=number,
        session_id=session_id,
        session_url=session_url,
        structured_output={},          # empty for now
        pull_request_url="",           # unknown for now
        session={"status_enum": "working"},
    )

    # Return early so the UI can show the session URL immediately
    # The frontend polling will update the record with PR and structured output
    return {"cached": False, **get_exec(number)}


@app.post("/issues/{number}/verify")
def verify_pr(number: int, force: bool = Query(False)):
    """
    Verifies a PR by running tests on the PR head ref using Devin.
    This helps determine if the PR is ready to merge and the issue can be closed.
    """
    existing_verify = get_verify(number)
    if existing_verify and not force:
        return {"cached": True, **existing_verify}

    # Get the execution record to find the PR
    exec_record = get_exec(number)
    if not exec_record:
        raise HTTPException(status_code=400, detail="No execution record found. Run Execute first.")

    pr_url = exec_record.get("pull_request_url")
    if not pr_url:
        raise HTTPException(status_code=400, detail="No PR found. Complete execution first.")

    issue = get_issue(number)
    owner = os.getenv("GITHUB_OWNER")
    repo = os.getenv("GITHUB_REPO")
    gh_token = os.getenv("GITHUB_TOKEN")

    if not all([owner, repo, gh_token]):
        return {"error": "Missing GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN in env."}

    repo_url = f"https://github.com/{owner}/{repo}.git"

    # Extract PR number from URL
    # URL format: https://github.com/{owner}/{repo}/pull/{pr_number}
    pr_number = pr_url.rstrip('/').split('/')[-1]

    schema = """
{
  "tests_run": ["string"],
  "tests_passed": ["string"],
  "tests_failed": ["string"],
  "test_summary": "string",
  "all_tests_passed": true,
  "ready_to_merge": true,
  "issues_found": ["string"],
  "recommendation": "string"
}
""".strip()

    prompt = f"""
You are Devin. Verify the pull request for GitHub issue #{number} by running all tests on the PR head ref.

Repo: {repo_url}
Issue #{number}: {issue.get("title")}
PR: {pr_url}

Requirements:
1) Clone the repository
2) Fetch the PR: git fetch origin pull/{pr_number}/head:pr-{pr_number}
3) Checkout the PR branch: git checkout pr-{pr_number}
4) Install dependencies if needed
5) Run ALL tests (pytest, or whatever test framework is configured)
6) Analyze test results and provide a clear summary

Authentication:
- You have a session secret named GITHUB_TOKEN
- Use it for git operations

Git setup:
1) git clone {repo_url}
2) cd {repo}
3) git fetch origin pull/{pr_number}/head:pr-{pr_number}
4) git checkout pr-{pr_number}
5) Run tests (check for pytest, npm test, make test, etc.)

IMPORTANT:
- Populate the STRUCTURED OUTPUT with test results
- Set all_tests_passed to true ONLY if all tests pass
- Set ready_to_merge to true if tests pass and code looks good
- List any issues or concerns in issues_found

STRUCTURED OUTPUT JSON SCHEMA:
{schema}
""".strip()

    try:
        resp = create_session(
            prompt=prompt,
            title=f"Verify PR for GH-{number}: {issue.get('title','')[:80]}",
            tags=["github", f"issue:{number}", "verify", f"pr:{pr_number}"],
            session_secrets=[
                {"key": "GITHUB_TOKEN", "value": gh_token, "sensitive": True}
            ],
        )
    except DevinRateLimitError as e:
        raise HTTPException(status_code=429, detail={"error": str(e), "retry_after_s": e.retry_after_s})

    session_id = resp["session_id"]
    session_url = resp.get("url")

    # Save initial verify record with session info
    upsert_verify(
        issue_number=number,
        session_id=session_id,
        session_url=session_url,
        structured_output={},
        session={"status_enum": "working"},
    )

    # Return early so the UI can show the session URL immediately
    saved = get_verify(number)
    return {"cached": False, **saved}

