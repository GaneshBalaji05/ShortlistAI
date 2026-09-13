from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from backend_preflight import audit_database


def build_database(path: Path, *, include_workspace_columns: bool = True) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE workspaces(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE users(id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, email TEXT NOT NULL);
            CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
            """
        )
        workspace = ", workspace_id INTEGER" if include_workspace_columns else ""
        con.execute(f"CREATE TABLE jobs(id INTEGER PRIMARY KEY{workspace})")
        con.execute(f"CREATE TABLE candidates(id INTEGER PRIMARY KEY, job_id INTEGER{workspace})")
        con.execute(f"CREATE TABLE notes(id INTEGER PRIMARY KEY, candidate_id INTEGER{workspace})")
        con.execute(f"CREATE TABLE activity_log(id INTEGER PRIMARY KEY, candidate_id INTEGER{workspace})")
        con.execute(f"CREATE TABLE interviews(id INTEGER PRIMARY KEY, candidate_id INTEGER{workspace})")

        if include_workspace_columns:
            con.executescript(
                """
                CREATE INDEX idx_jobs_workspace ON jobs(workspace_id);
                CREATE INDEX idx_candidates_workspace ON candidates(workspace_id);
                CREATE INDEX idx_candidates_workspace_job ON candidates(workspace_id, job_id);
                CREATE INDEX idx_notes_workspace ON notes(workspace_id);
                CREATE INDEX idx_activity_log_workspace ON activity_log(workspace_id);
                CREATE INDEX idx_interviews_workspace ON interviews(workspace_id);
                """
            )
        con.commit()
    finally:
        con.close()


def test_preflight_accepts_tenant_safe_schema() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ok.db"
        build_database(path)
        report = audit_database(path)
        assert report["ok"], report
        assert not report["errors"]


def test_preflight_rejects_missing_workspace_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.db"
        build_database(path, include_workspace_columns=False)
        report = audit_database(path)
        assert not report["ok"]
        assert any("tenant isolation column missing" in item for item in report["errors"])


def test_preflight_rejects_missing_database() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = audit_database(Path(tmp) / "missing.db")
        assert not report["ok"]
        assert "database file does not exist" in report["errors"]


if __name__ == "__main__":
    test_preflight_accepts_tenant_safe_schema()
    test_preflight_rejects_missing_workspace_isolation()
    test_preflight_rejects_missing_database()
    print("backend preflight regression OK")
