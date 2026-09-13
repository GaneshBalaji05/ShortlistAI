from __future__ import annotations

import json
import sqlite3
from datetime import datetime

SOURCE_NAME = "Test Data - ShortlistAI_results.xlsx"
RESUME_NAME = "Ganesh_S_Resume (2)"


def _workspace_column(con: sqlite3.Connection) -> bool:
    return "workspace_id" in {row[1] for row in con.execute("PRAGMA table_info(candidates)")}


def _demo_workspace_id(con: sqlite3.Connection) -> int:
    from auth_runtime import _ensure_auth_schema, _ensure_demo_account

    _ensure_auth_schema()
    _, workspace_id = _ensure_demo_account(con)
    con.commit()
    return workspace_id


def seed_test_candidate(db_path: str) -> None:
    """Keep the uploaded ShortlistAI_results.xlsx row available as safe demo test data.

    The row is stored in the normal candidates table and mapped to the Sheet2
    master tracker structure through profile_details. Missing Sheet2 fields are
    deliberately left blank rather than guessed. When workspace isolation is
    present, this seed is confined to the dedicated ShortlistAI Demo workspace.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    scoped = _workspace_column(con)
    workspace_id = _demo_workspace_id(con) if scoped else None
    if scoped:
        existing = con.execute(
            "SELECT id FROM candidates WHERE source=? AND resume_filename=? AND workspace_id=? LIMIT 1",
            (SOURCE_NAME, RESUME_NAME, workspace_id),
        ).fetchone()
    else:
        existing = con.execute(
            "SELECT id FROM candidates WHERE source=? AND resume_filename=? LIMIT 1",
            (SOURCE_NAME, RESUME_NAME),
        ).fetchone()
    if existing:
        con.close()
        return

    now = datetime.utcnow().isoformat()
    ai_details = {
        "score": 30.2,
        "rating": "Weak",
        "candidate_years": None,
        "required_years": 2,
        "semantic_similarity": 18.2,
        "skill_coverage": 50.0,
        "recent_evidence": 0.0,
        "matched_skills": [],
        "missing_skills": [],
        "recent_skills": [],
        "risks": [
            "Total years of experience could not be reliably extracted; verify manually."
        ],
        "screening_questions": [
            "Walk me through the project in your current or most recent role that is most relevant to this position. What did you personally own?"
        ],
        "test_source": "ShortlistAI_results.xlsx",
    }

    profile_details = {
        "candidate_full_name": RESUME_NAME,
        "contact_no": "",
        "email_id": "",
        "total_experience": None,
        "relevant_experience": "",
        "current_organization": "",
        "current_designation": "",
        "current_company_experience": "",
        "current_ctc": "",
        "expected_ctc": "",
        "holding_offers": "",
        "last_appraisal": "",
        "notice_period": "",
        "native_location": "",
        "current_location": "",
        "preferred_location": "",
        "ug": "",
        "highest_qualification": "",
        "linkedin_id": "",
        "screening_status": "Test Data",
        "interview_level": "",
        "offer": "",
        "tentative_doj": "",
        "client": "",
        "role_name": "",
        "recruiter_name": "",
        "remarks": "Imported for testing from ShortlistAI_results.xlsx. Required Years: 2; Semantic Similarity: 18.2%; Recent Evidence: 0%. Missing Sheet2 fields intentionally left blank.",
    }

    columns = """name,email,phone,experience,skills,resume_text,resume_filename,source,
            notice_period,current_ctc,expected_ctc,job_id,stage,ai_score,rating,
            ai_details,profile_details,created_at,updated_at"""
    values = (
        RESUME_NAME,
        "",
        "",
        None,
        "",
        "",
        RESUME_NAME,
        SOURCE_NAME,
        "",
        "",
        "",
        None,
        "Sourced",
        30.2,
        "Weak",
        json.dumps(ai_details),
        json.dumps(profile_details),
        now,
        now,
    )
    if scoped:
        con.execute(
            f"INSERT INTO candidates(workspace_id,{columns}) VALUES({','.join(['?'] * 20)})",
            (workspace_id, *values),
        )
    else:
        con.execute(
            f"INSERT INTO candidates({columns}) VALUES({','.join(['?'] * 19)})",
            values,
        )
    con.commit()
    con.close()
