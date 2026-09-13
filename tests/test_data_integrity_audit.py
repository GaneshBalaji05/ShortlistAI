from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from data_integrity_audit import audit_database


def create_schema(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE workspaces(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE users(
                id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, full_name TEXT NOT NULL,
                email TEXT NOT NULL, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
                role TEXT NOT NULL, created_at TEXT NOT NULL, last_login_at TEXT
            );
            CREATE TABLE auth_sessions(
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            CREATE TABLE jobs(
                id INTEGER PRIMARY KEY, workspace_id INTEGER, title TEXT NOT NULL, department TEXT,
                location TEXT, jd TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE candidates(
                id INTEGER PRIMARY KEY, workspace_id INTEGER, name TEXT NOT NULL, email TEXT, phone TEXT,
                experience REAL, skills TEXT, resume_text TEXT, source TEXT, notice_period TEXT,
                current_ctc TEXT, expected_ctc TEXT, job_id INTEGER, stage TEXT, ai_score REAL,
                rating TEXT, created_at TEXT, updated_at TEXT, ai_details TEXT, resume_filename TEXT,
                profile_details TEXT, talent_pools TEXT
            );
            CREATE TABLE notes(
                id INTEGER PRIMARY KEY, workspace_id INTEGER, candidate_id INTEGER NOT NULL,
                note TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE activity_log(
                id INTEGER PRIMARY KEY, workspace_id INTEGER, candidate_id INTEGER NOT NULL,
                action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE interviews(
                id INTEGER PRIMARY KEY, workspace_id INTEGER, candidate_id INTEGER NOT NULL, job_id INTEGER,
                round_name TEXT NOT NULL, interviewer_name TEXT, interviewer_email TEXT, scheduled_at TEXT NOT NULL,
                timezone TEXT, duration_minutes INTEGER, meeting_url TEXT, status TEXT, outcome TEXT,
                notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE candidate_identities(
                workspace_id INTEGER NOT NULL, candidate_id INTEGER NOT NULL,
                identity_type TEXT NOT NULL, identity_value TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, identity_type, identity_value)
            );
            """
        )
        con.commit()
    finally:
        con.close()


def insert_clean_data(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executemany(
            "INSERT INTO workspaces VALUES(?,?,?)",
            [(1, "One", "2026-09-14"), (2, "Two", "2026-09-14")],
        )
        con.executemany(
            "INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (1, 1, "One User", "one@example.test", "h", "s", "Admin", "2026-09-14", None),
                (2, 2, "Two User", "two@example.test", "h", "s", "Admin", "2026-09-14", None),
            ],
        )
        con.execute("INSERT INTO auth_sessions VALUES(?,?,?,?)", ("token", 1, "2026-09-14", "2026-10-14"))
        con.executemany(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (1, 1, "Java Engineer", "Eng", "Chennai", "Java role", "Open", "2026-09-14",),
                (2, 2, "Python Engineer", "Eng", "Chennai", "Python role", "Open", "2026-09-14",),
            ],
        )
        # SQLite requires exact column count; use explicit columns for readability.
        con.execute(
            """INSERT INTO candidates(
                id,workspace_id,name,email,phone,experience,skills,resume_text,source,job_id,stage,
                created_at,updated_at,profile_details
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (1, 1, "Alpha", "Alpha@Example.Test", "+91 90000 00001", 5, "Java", "Java Spring Boot", "Test", 1, "Applied", "2026-09-14", "2026-09-14", json.dumps({"linkedin_id": "https://www.linkedin.com/in/alpha-engineer/"})),
        )
        con.execute(
            """INSERT INTO candidates(
                id,workspace_id,name,email,phone,experience,skills,resume_text,source,job_id,stage,
                created_at,updated_at,profile_details
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (2, 2, "Alpha Two", "alpha@example.test", "+91 90000 00001", 4, "Python", "Python", "Test", 2, "Sourced", "2026-09-14", "2026-09-14", json.dumps({"linkedin_id": "https://linkedin.com/in/alpha-engineer"})),
        )
        con.executemany(
            "INSERT INTO candidate_identities VALUES(?,?,?,?,?)",
            [
                (1, 1, "email", "alpha@example.test", "2026-09-14"),
                (1, 1, "phone", "9000000001", "2026-09-14"),
                (1, 1, "linkedin", "alpha-engineer", "2026-09-14"),
                (2, 2, "email", "alpha@example.test", "2026-09-14"),
                (2, 2, "phone", "9000000001", "2026-09-14"),
                (2, 2, "linkedin", "alpha-engineer", "2026-09-14"),
            ],
        )
        con.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (1, 1, 1, "ok", "2026-09-14"))
        con.execute("INSERT INTO activity_log VALUES(?,?,?,?,?,?)", (1, 1, 1, "created", "", "2026-09-14"))
        con.execute(
            "INSERT INTO interviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, 1, 1, 1, "L1", "", "", "2026-09-15T10:00", "Asia/Kolkata", 45, "", "Scheduled", "Pending", "", "2026-09-14", "2026-09-14"),
        )
        con.commit()
    finally:
        con.close()


def snapshot(path: Path) -> dict[str, list[tuple]]:
    con = sqlite3.connect(path)
    try:
        out = {}
        for table in ("workspaces", "users", "auth_sessions", "jobs", "candidates", "notes", "activity_log", "interviews", "candidate_identities"):
            out[table] = con.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        return out
    finally:
        con.close()


def test_clean_cross_workspace_same_identity_is_allowed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clean.db"
        create_schema(path)
        insert_clean_data(path)
        before = snapshot(path)
        report = audit_database(path)
        after = snapshot(path)
        assert report["ok"], report
        assert not report["critical"], report
        assert report["checks"]["duplicate_candidate_identity_within_workspace"]["count"] == 0
        assert before == after, "read-only audit mutated database content"


def test_corruption_is_reported_without_exposing_contact_values() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.db"
        create_schema(path)
        insert_clean_data(path)
        con = sqlite3.connect(path)
        try:
            con.execute(
                """INSERT INTO candidates(
                    id,workspace_id,name,email,phone,experience,skills,resume_text,source,job_id,stage,
                    created_at,updated_at,profile_details
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (3, 1, "", " ALPHA@example.test ", "123", 2, "JS", "JavaScript", "Bad", 2, "Mystery", None, None, json.dumps({"linkedin_id": "not a linkedin url/value!!"})),
            )
            con.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (2, 1, 999, "orphan", "2026-09-14"))
            con.execute("INSERT INTO activity_log VALUES(?,?,?,?,?,?)", (2, 2, 1, "bad workspace", "", "2026-09-14"))
            con.execute(
                "INSERT INTO interviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (2, 1, 999, 999, "L1", "", "", "2026-09-15T10:00", "Asia/Kolkata", 45, "", "Scheduled", "Pending", "", "2026-09-14", "2026-09-14"),
            )
            con.execute(
                "INSERT INTO candidate_identities VALUES(?,?,?,?,?)",
                (1, 3, "linkedin", "wrong-owner", "2026-09-14"),
            )
            con.commit()
        finally:
            con.close()

        before = snapshot(path)
        report = audit_database(path)
        after = snapshot(path)
        assert not report["ok"]
        expected_critical = {
            "duplicate_candidate_identity_within_workspace",
            "candidate_job_cross_workspace",
            "orphan_notes",
            "activity_log_candidate_cross_workspace",
            "orphan_interviews",
            "interview_orphan_job",
        }
        assert expected_critical.issubset(set(report["critical"])), report
        assert report["checks"]["malformed_candidate_phone"]["count"] == 1
        assert report["checks"]["malformed_candidate_linkedin"]["count"] == 1
        assert report["checks"]["candidate_missing_name"]["count"] == 1
        assert report["checks"]["candidate_missing_timestamps"]["count"] == 1
        assert report["checks"]["invalid_pipeline_stage"]["count"] == 1
        rendered = json.dumps(report).lower()
        assert "alpha@example.test" not in rendered
        assert "not a linkedin" not in rendered
        assert before == after, "audit must never repair or delete questionable data automatically"


def run() -> None:
    test_clean_cross_workspace_same_identity_is_allowed()
    test_corruption_is_reported_without_exposing_contact_values()
    print("Data integrity audit regression passed")


if __name__ == "__main__":
    run()
