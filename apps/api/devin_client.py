import os
import time
import requests

DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")
DEVIN_BASE_URL = os.getenv("DEVIN_BASE_URL", "https://api.devin.ai/v1")

if not DEVIN_API_KEY:
    raise RuntimeError("Missing DEVIN_API_KEY")

_HEADERS = {
    "Authorization": f"Bearer {DEVIN_API_KEY}",
    "Content-Type": "application/json",
}

class DevinRateLimitError(Exception):
    def __init__(self, message: str, retry_after_s: int | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s

def create_session(prompt: str, title: str, tags: list[str] | None = None, session_secrets: list[dict] | None = None) -> dict:
    payload = {"prompt": prompt, "title": title, "tags": tags or []}
    if session_secrets:
        payload["session_secrets"] = session_secrets

    # Small retry loop with backoff for 429s
    for attempt in range(1, 4):
        r = requests.post(f"{DEVIN_BASE_URL}/sessions", headers=_HEADERS, json=payload, timeout=60)

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            retry_after_s = int(retry_after) if (retry_after and retry_after.isdigit()) else None
            # backoff: 2s, 4s, 8s (or respect Retry-After if present)
            sleep_s = retry_after_s if retry_after_s is not None else 2 ** attempt
            # If we're on the last attempt, raise a friendly error for the API layer
            if attempt == 3:
                raise DevinRateLimitError(
                    f"Devin rate limited (429). Retry after ~{sleep_s}s.",
                    retry_after_s=sleep_s,
                )
            time.sleep(sleep_s)
            continue

        if r.status_code >= 400:
            # Surface body for debugging
            raise RuntimeError(f"Devin API error {r.status_code}: {r.text}")

        return r.json()

    raise RuntimeError("Unexpected error creating Devin session")

def get_session(session_id: str) -> dict:
    """
    GET /v1/sessions/{session_id}
    Returns session details including status_enum and structured_output.
    """
    r = requests.get(f"{DEVIN_BASE_URL}/sessions/{session_id}", headers=_HEADERS, timeout=60)
    r.raise_for_status()
    return r.json() 

def poll_structured_output(session_id: str, timeout_s: int = 900, poll_every_s: int = 15) -> dict:
    """
    Poll session details until structured_output appears or timeout.
    Docs recommend 10–30s polling.
    """
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        last = get_session(session_id)
        so = last.get("structured_output")
        status_enum = last.get("status_enum")
        if so:
            return {"session": last, "structured_output": so}
        if status_enum in ("completed", "failed", "error", "cancelled"):
            return {"session": last, "structured_output": so}
        time.sleep(poll_every_s)
    return {"session": last, "structured_output": (last or {}).get("structured_output"), "timeout": True}

def poll_until_pr(session_id: str, timeout_s: int = 900, poll_every_s: int = 15) -> dict:
    """
    Poll until PR URL is available (preferred for execute),
    or session finishes / times out.
    """
    start = time.time()
    last = None

    while time.time() - start < timeout_s:
        last = get_session(session_id)
        so = last.get("structured_output") or {}

        # PR can appear in either place
        pr = last.get("pull_request")
        pr_url = None
        if isinstance(pr, dict):
            pr_url = pr.get("url")

        pr_url = pr_url or so.get("pull_request_url")
        if pr_url:
            return {"session": last, "structured_output": so, "pull_request_url": pr_url, "timeout": False}

        status_enum = last.get("status_enum")
        if status_enum in ("completed", "failed", "error", "cancelled", "finished"):
            return {"session": last, "structured_output": so, "pull_request_url": pr_url or "", "timeout": False}

        time.sleep(poll_every_s)

    return {
        "session": last,
        "structured_output": (last or {}).get("structured_output") or {},
        "pull_request_url": "",
        "timeout": True,
    }
