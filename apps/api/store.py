import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "runs.db"

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS triage_runs (
            issue_number INTEGER PRIMARY KEY,
            created_at INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            session_url TEXT,
            structured_output TEXT,
            raw_session_json TEXT
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS exec_runs (
            issue_number INTEGER PRIMARY KEY,
            created_at INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            session_url TEXT,
            structured_output TEXT,
            pull_request_url TEXT,
            raw_session_json TEXT
        )
        """)

def get_triage(issue_number: int) -> Optional[dict[str, Any]]:
    with _conn() as con:
        row = con.execute("SELECT * FROM triage_runs WHERE issue_number=?", (issue_number,)).fetchone()
        if not row:
            return None
        return {
            "issue_number": row["issue_number"],
            "created_at": row["created_at"],
            "session_id": row["session_id"],
            "session_url": row["session_url"],
            "structured_output": json.loads(row["structured_output"]) if row["structured_output"] else None,
            "session": json.loads(row["raw_session_json"]) if row["raw_session_json"] else None,
        }

def upsert_triage(issue_number: int, session_id: str, session_url: str | None, structured_output: dict | None, session: dict | None):
    with _conn() as con:
        con.execute("""
        INSERT INTO triage_runs(issue_number, created_at, session_id, session_url, structured_output, raw_session_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(issue_number) DO UPDATE SET
            created_at=excluded.created_at,
            session_id=excluded.session_id,
            session_url=excluded.session_url,
            structured_output=excluded.structured_output,
            raw_session_json=excluded.raw_session_json
        """, (
            issue_number,
            int(time.time()),
            session_id,
            session_url,
            json.dumps(structured_output) if structured_output else None,
            json.dumps(session) if session else None,
        ))

def get_exec(issue_number: int) -> Optional[dict[str, Any]]:
    with _conn() as con:
        row = con.execute("SELECT * FROM exec_runs WHERE issue_number=?", (issue_number,)).fetchone()
        if not row:
            return None
        return {
            "issue_number": row["issue_number"],
            "created_at": row["created_at"],
            "session_id": row["session_id"],
            "session_url": row["session_url"],
            "pull_request_url": row["pull_request_url"],
            "structured_output": json.loads(row["structured_output"]) if row["structured_output"] else None,
            "session": json.loads(row["raw_session_json"]) if row["raw_session_json"] else None,
        }

def upsert_exec(issue_number: int, session_id: str, session_url: str | None, structured_output: dict | None, pull_request_url: str | None, session: dict | None):
    with _conn() as con:
        con.execute("""
        INSERT INTO exec_runs(issue_number, created_at, session_id, session_url, structured_output, pull_request_url, raw_session_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(issue_number) DO UPDATE SET
            created_at=excluded.created_at,
            session_id=excluded.session_id,
            session_url=excluded.session_url,
            structured_output=excluded.structured_output,
            pull_request_url=excluded.pull_request_url,
            raw_session_json=excluded.raw_session_json
        """, (
            issue_number,
            int(time.time()),
            session_id,
            session_url,
            json.dumps(structured_output) if structured_output else None,
            pull_request_url,
            json.dumps(session) if session else None,
        ))
