from __future__ import annotations

import base64
import bz2
import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Iterable

SOURCE = "Sheet2 Master Data"
DEFAULT_WORKSPACE = "Master Data QA"
DEFAULT_EMAIL = "masterdata.qa@shortlist.ai"
ROW_WIDTH = 15


def _enabled() -> bool:
    return os.getenv("SHORTLISTAI_MASTER_DATA_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _years(value: Any) -> float | None:
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return number if 0 <= number <= 60 else None


def _decode_env_rows() -> tuple[list[list[Any]], str, str]:
    try:
        count = int(os.getenv("SHORTLISTAI_MASTER_DATA_CHUNK_COUNT", "0"))
    except ValueError as exc:
        raise RuntimeError("SHORTLISTAI_MASTER_DATA_CHUNK_COUNT must be an integer") from exc
    if count <= 0 or count > 100:
        raise RuntimeError("No private Sheet2 master-data chunks configured")

    encoded_parts: list[str] = []
    for index in range(1, count + 1):
        key = f"SHORTLISTAI_MASTER_DATA_{index:03d}"
        value = os.getenv(key, "")
        if not value:
            raise RuntimeError(f"Missing private Sheet2 seed chunk {index}/{count}")
        encoded_parts.append(value.strip())

    try:
        raw = bz2.decompress(base64.b64decode("".join(encoded_parts), validate=True))
        rows = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Private Sheet2 master-data payload could not be decoded") from exc

    if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != ROW_WIDTH for row in rows):
        raise RuntimeError("Private Sheet2 master-data payload has an invalid row shape")

    actual_sha = hashlib.sha256(raw).hexdigest()
    expected_sha = os.getenv("SHORTLISTAI_MASTER_DATA_SHA256", "").strip().lower()
    if expected_sha and not hmac.compare_digest(actual_sha, expected_sha):
        raise RuntimeError("Private Sheet2 master-data checksum mismatch")

    expected_count = os.getenv("SHORTLISTAI_MASTER_DATA_EXPECTED_COUNT", "").strip()
    if expected_count:
        try:
            wanted = int(expected_count)
        except ValueError as exc:
            raise RuntimeError("SHORTLISTAI_MASTER_DATA_EXPECTED_COUNT must be an integer") from exc
        if len(rows) != wanted:
            raise RuntimeError(f"Private Sheet2 master-data count mismatch: expected {wanted}, got {len(rows)}")

    version = os.getenv("SHORTLISTAI_MASTER_DATA_VERSION", actual_sha[:16]).strip() or actual_sha[:16]
    return rows, version, actual_sha


def _ensure_workspace_user(con: sqlite3.Connection) -> tuple[int, int, str]:
    import auth_runtime

    auth_runtime._ensure_auth_schema()
    email = os.getenv("SHORTLISTAI_MASTER_QA_EMAIL", DEFAULT_EMAIL).strip().lower()
    password = os.getenv("SHORTLISTAI_MASTER_QA_PASSWORD", "")
    workspace_name = os.getenv("SHORTLISTAI_MASTER_QA_WORKSPACE", DEFAULT_WORKSPACE).strip() or DEFAULT_WORKSPACE
    if not email or "@" not in email:
        raise RuntimeError("Master-data QA email is invalid")
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise RuntimeError("Master-data QA password must be at least 8 characters and include letters and numbers")

    user = con.execute("SELECT id,workspace_id FROM users WHERE lower(email)=?", (email,)).fetchone()
    pw_hash, pw_salt = auth_runtime._hash_password(password)
    now = datetime.utcnow().isoformat()
    if user:
        user_id = int(user["id"])
        workspace_id = int(user["workspace_id"])
        con.execute("UPDATE workspaces SET name=? WHERE id=?", (workspace_name, workspace_id))
        con.execute(
            "UPDATE users SET full_name=?,password_hash=?,password_salt=?,role=? WHERE id=?",
            ("Master Data QA", pw_hash, pw_salt, "Workspace Admin", user_id),
        )
        return user_id, workspace_id, email

    workspace = con.execute("SELECT id FROM workspaces WHERE name=? ORDER BY id LIMIT 1", (workspace_name,)).fetchone()
    if workspace:
        workspace_id = int(workspace["id"])
    else:
        cur = con.execute("INSERT INTO workspaces(name,created_at) VALUES(?,?)", (workspace_name, now))
        workspace_id = int(cur.lastrowid)
    cur = con.execute(
        """INSERT INTO users(workspace_id,full_name,email,password_hash,password_salt,role,created_at,last_login_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (workspace_id, "Master Data QA", email, pw_hash, pw_salt, "Workspace Admin", now, None),
    )
    return int(cur.lastrowid), workspace_id, email


def _ensure_seed_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS master_data_seed_log(
            workspace_id INTEGER NOT NULL,
            dataset_version TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            seeded_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id,dataset_version)
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS candidate_identities(
            workspace_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            identity_type TEXT NOT NULL,
            identity_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id,identity_type,identity_value),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        )"""
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_identities_candidate ON candidate_identities(workspace_id,candidate_id)"
    )


def _identity_values(email: str, phone: str, resume_text: str) -> Iterable[tuple[str, str]]:
    email_value = email.strip().lower()
    if email_value:
        yield "email", email_value
    phone_value = re.sub(r"\D", "", phone)
    if len(phone_value) >= 10:
        yield "phone", phone_value[-10:]
    normalized_resume = re.sub(r"\s+", " ", resume_text.strip().lower())
    if len(normalized_resume) >= 80:
        yield "resume", hashlib.sha256(normalized_resume.encode("utf-8")).hexdigest()


def _profile(row: list[Any], stage: str = "Applied") -> tuple[dict[str, Any], dict[str, Any]]:
    (
        sno, rhid, name, phone, email, skill, total_exp, relevant_exp, current_company,
        current_ctc, expected_ctc, current_location, preferred_location, notice_period, lwd,
    ) = [_clean(value) for value in row]

    sheet2 = {
        "S No": sno,
        "Date": "",
        "Client": "",
        "Position Worked": skill,
        "Tech Stack": skill,
        "Recruter": "",
        "Resource Name": name,
        "Number": phone,
        "Mail-id": email,
        "Current Company": current_company,
        "Current Designation": "",
        "Tot Exp (In Years)": total_exp,
        "Rel Exp (In Years)": relevant_exp,
        "Current company Exp (In Years)": "",
        "CTC (In LPA)": current_ctc,
        "ECTC (In LPA)": expected_ctc,
        "Offer In hand (if any)": "",
        "Last Appraisal & Month": "",
        "Notice Period": notice_period,
        "Native Location": "",
        "Current Location": current_location,
        "Preferred Location": preferred_location,
        "UG": "",
        "Highest Qualification": "",
        "LinkedIn ID": "",
        "Profile Submission Date": "",
        "Screening Status": "",
        "Interview Level": "",
        "Status": stage,
        "Offer": "",
        "D.O.J": "",
        "Remarks": "Imported from the supplied Sheet2 master-data source for ShortlistAI search and QA validation.",
    }
    profile = {
        "candidate_full_name": name,
        "contact_no": phone,
        "email_id": email,
        "total_experience": _years(total_exp),
        "relevant_experience": relevant_exp,
        "current_organization": current_company,
        "current_designation": "",
        "current_company_experience": "",
        "current_ctc": current_ctc,
        "expected_ctc": expected_ctc,
        "holding_offers": "",
        "last_appraisal": "",
        "notice_period": notice_period,
        "native_location": "",
        "current_location": current_location,
        "preferred_location": preferred_location,
        "ug": "",
        "highest_qualification": "",
        "linkedin_id": "",
        "profile_submission_date": "",
        "screening_status": "",
        "interview_level": "",
        "offer": "",
        "tentative_doj": "",
        "client": "",
        "role_name": skill,
        "recruiter_name": "",
        "remarks": sheet2["Remarks"],
        "rhid": rhid,
        "lwd": lwd,
        "sheet2": sheet2,
        "data_basis": "Sheet2 master data only; no full resume was provided in this source record.",
    }
    master = {
        "sno": sno, "rhid": rhid, "name": name, "phone": phone, "email": email,
        "skill": skill, "total_exp": total_exp, "relevant_exp": relevant_exp,
        "current_company": current_company, "current_ctc": current_ctc,
        "expected_ctc": expected_ctc, "current_location": current_location,
        "preferred_location": preferred_location, "notice_period": notice_period, "lwd": lwd,
    }
    return profile, master


def _resume_text(master: dict[str, Any]) -> str:
    parts = [
        f"Candidate: {master['name']}",
        "Structured Sheet2 master-data profile; this is not a full resume.",
        f"Primary skill / position: {master['skill']}",
        f"Total experience: {master['total_exp']}",
        f"Relevant experience: {master['relevant_exp']}",
        f"Current company: {master['current_company']}",
        f"Current location: {master['current_location']}",
        f"Preferred location: {master['preferred_location']}",
        f"Notice period: {master['notice_period']}",
        f"LWD: {master['lwd']}",
    ]
    return "\n".join(part for part in parts if not part.endswith(": "))


def seed_master_data_rows(db_path: str, rows: list[list[Any]], dataset_version: str, payload_sha256: str) -> dict[str, Any]:
    import main
    import tenant_security

    legacy = getattr(main, "legacy", main)
    tenant_security.ensure_schema(force=True)
    con = tenant_security._raw()
    try:
        con.row_factory = sqlite3.Row
        _, workspace_id, email = _ensure_workspace_user(con)
        _ensure_seed_schema(con)

        previous = con.execute(
            "SELECT row_count,payload_sha256 FROM master_data_seed_log WHERE workspace_id=? AND dataset_version=?",
            (workspace_id, dataset_version),
        ).fetchone()
        existing_count = int(con.execute(
            "SELECT COUNT(*) FROM candidates WHERE workspace_id=? AND source=?",
            (workspace_id, SOURCE),
        ).fetchone()[0])
        if previous and previous["payload_sha256"] == payload_sha256 and int(previous["row_count"]) == len(rows) and existing_count == len(rows):
            return {"seeded": False, "workspace_id": workspace_id, "email": email, "count": existing_count, "version": dataset_version}

        candidate_ids = [int(row[0]) for row in con.execute(
            "SELECT id FROM candidates WHERE workspace_id=? AND source=?", (workspace_id, SOURCE)
        ).fetchall()]
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            con.execute(
                f"DELETE FROM candidate_identities WHERE workspace_id=? AND candidate_id IN ({placeholders})",
                (workspace_id, *candidate_ids),
            )
            con.execute(
                f"DELETE FROM candidates WHERE workspace_id=? AND id IN ({placeholders})",
                (workspace_id, *candidate_ids),
            )
        con.execute("DELETE FROM master_data_seed_log WHERE workspace_id=?", (workspace_id,))

        now = datetime.utcnow().isoformat()
        created = 0
        blank_rhid = 0
        for index, row in enumerate(rows, 1):
            profile, master = _profile(row)
            if not master["name"]:
                continue
            if not master["rhid"]:
                blank_rhid += 1
            resume_text = _resume_text(master)
            skills = master["skill"]
            talent_pools = legacy.classify_talent_pools(resume_text, skills, json.dumps(profile, ensure_ascii=False))
            stable_key = hashlib.sha256(
                (master["email"].lower() + "|" + re.sub(r"\D", "", master["phone"])[-10:] + "|" + master["name"].lower()).encode("utf-8")
            ).hexdigest()[:20]
            filename = f"sheet2-master-{stable_key}.txt"
            cur = con.execute(
                """INSERT INTO candidates(
                    workspace_id,name,email,phone,experience,skills,resume_text,resume_filename,source,
                    notice_period,current_ctc,expected_ctc,job_id,stage,ai_score,rating,ai_details,
                    profile_details,talent_pools,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    workspace_id, master["name"], master["email"], master["phone"], _years(master["total_exp"]),
                    skills, resume_text, filename, SOURCE, master["notice_period"], master["current_ctc"],
                    master["expected_ctc"], None, "Applied", None, None, None,
                    json.dumps(profile, ensure_ascii=False), legacy.encode_talent_pools(talent_pools), now, now,
                ),
            )
            candidate_id = int(cur.lastrowid)
            for identity_type, identity_value in _identity_values(master["email"], master["phone"], resume_text):
                con.execute(
                    """INSERT OR IGNORE INTO candidate_identities(
                        workspace_id,candidate_id,identity_type,identity_value,created_at
                    ) VALUES(?,?,?,?,?)""",
                    (workspace_id, candidate_id, identity_type, identity_value, now),
                )
            created += 1
            if index % 50 == 0:
                con.commit()

        con.execute(
            "INSERT INTO master_data_seed_log(workspace_id,dataset_version,payload_sha256,row_count,seeded_at) VALUES(?,?,?,?,?)",
            (workspace_id, dataset_version, payload_sha256, created, now),
        )
        con.commit()

        from boolean_search import matches_boolean

        candidates = [legacy._candidate_dict(row) for row in con.execute(
            "SELECT * FROM candidates WHERE workspace_id=? AND source=? ORDER BY id", (workspace_id, SOURCE)
        ).fetchall()]
        checks = {
            query: sum(1 for candidate in candidates if matches_boolean(query, candidate))
            for query in ("Java", "Python", "React", "Devops")
        }
        print(
            "ShortlistAI master-data seed OK: "
            f"workspace={workspace_id} count={len(candidates)} blank_rhid={blank_rhid} "
            f"search_counts={json.dumps(checks, sort_keys=True)} version={dataset_version}"
        )
        return {
            "seeded": True,
            "workspace_id": workspace_id,
            "email": email,
            "count": len(candidates),
            "blank_rhid": blank_rhid,
            "version": dataset_version,
            "search_counts": checks,
        }
    finally:
        con.close()


def seed_master_data_from_env(db_path: str) -> dict[str, Any] | None:
    if not _enabled():
        return None
    rows, version, payload_sha256 = _decode_env_rows()
    return seed_master_data_rows(db_path, rows, version, payload_sha256)
