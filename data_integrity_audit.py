from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from final_review import PIPELINE_STAGES, STAGE_ALIASES

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REQUIRED_TABLES = {
    "workspaces",
    "users",
    "auth_sessions",
    "jobs",
    "candidates",
    "notes",
    "activity_log",
    "interviews",
    "candidate_identities",
}
TENANT_TABLES = {"jobs", "candidates", "notes", "activity_log", "interviews", "candidate_identities"}
VALID_STORED_STAGES = set(PIPELINE_STAGES) | set(STAGE_ALIASES)


def _connect_read_only(path: str | os.PathLike[str]) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    uri = f"file:{quote(str(resolved))}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _table_names(con: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _safe_profile(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _normalize_linkedin(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\.", "", raw)
    raw = raw.split("?", 1)[0].split("#", 1)[0].strip("/")
    match = re.search(r"(?:^|/)linkedin\.com/in/([^/]+)$", raw)
    if match:
        return match.group(1).strip().lower()
    match = re.search(r"(?:^|/)in/([^/]+)$", raw)
    if match:
        return match.group(1).strip().lower()
    if "/" not in raw and re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", raw):
        return raw
    return ""


def _linkedin_from_profile(profile: dict[str, Any]) -> tuple[str, str]:
    for key in ("linkedin_id", "linkedin_url", "linkedin_profile", "linkedin", "profile_link"):
        raw = str(profile.get(key) or "").strip()
        if raw:
            return raw, _normalize_linkedin(raw)
    return "", ""


def _ids(rows: Iterable[sqlite3.Row], key: str = "id", limit: int = 50) -> tuple[list[int], int]:
    values = [int(row[key]) for row in rows]
    return values[:limit], len(values)


def _record(report: dict[str, Any], name: str, ids: list[int], total: int, severity: str) -> None:
    report["checks"][name] = {
        "severity": severity,
        "count": int(total),
        "ids": ids,
        "truncated": total > len(ids),
    }
    if total:
        report[severity].append(name)


def audit_database(db_path: str | os.PathLike[str], *, sample_limit: int = 50) -> dict[str, Any]:
    path = Path(db_path)
    report: dict[str, Any] = {
        "ok": False,
        "database": str(path),
        "critical": [],
        "warnings": [],
        "counts": {},
        "checks": {},
        "notes": [
            "Read-only audit: no candidate or schema data is modified.",
            "Reports expose row IDs/counts only; contact values are intentionally omitted.",
        ],
    }
    if not path.exists():
        report["critical"].append("database_missing")
        report["checks"]["database_missing"] = {"severity": "critical", "count": 1, "ids": [], "truncated": False}
        return report

    con = _connect_read_only(path)
    try:
        tables = _table_names(con)
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            report["critical"].append("missing_required_tables")
            report["checks"]["missing_required_tables"] = {
                "severity": "critical",
                "count": len(missing),
                "ids": [],
                "tables": missing,
                "truncated": False,
            }

        for table in sorted(REQUIRED_TABLES & tables):
            report["counts"][table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        for table in sorted(TENANT_TABLES & tables):
            if "workspace_id" not in _columns(con, table):
                report["critical"].append(f"{table}_workspace_column_missing")
                report["checks"][f"{table}_workspace_column_missing"] = {
                    "severity": "critical", "count": 1, "ids": [], "truncated": False
                }
                continue
            rows = con.execute(f"SELECT id FROM {table} WHERE workspace_id IS NULL").fetchall() if "id" in _columns(con, table) else []
            ids, total = _ids(rows, limit=sample_limit) if rows else ([], 0)
            _record(report, f"{table}_null_workspace", ids, total, "critical")

        if {"users", "workspaces"} <= tables:
            rows = con.execute(
                """SELECT u.id FROM users u LEFT JOIN workspaces w ON w.id=u.workspace_id
                   WHERE w.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "users_orphan_workspace", ids, total, "critical")

        if {"auth_sessions", "users"} <= tables:
            rows = con.execute(
                """SELECT s.user_id AS id FROM auth_sessions s LEFT JOIN users u ON u.id=s.user_id
                   WHERE u.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "orphan_auth_sessions", ids, total, "critical")

        candidate_rows: list[sqlite3.Row] = []
        if "candidates" in tables:
            candidate_rows = con.execute(
                "SELECT id,workspace_id,name,email,phone,job_id,stage,created_at,updated_at,profile_details FROM candidates"
            ).fetchall()

            malformed_email = []
            malformed_phone = []
            malformed_linkedin = []
            missing_name = []
            missing_timestamps = []
            invalid_stage = []
            identity_buckets: dict[tuple[int, str, str], set[int]] = defaultdict(set)

            for row in candidate_rows:
                cid = int(row["id"])
                wid = row["workspace_id"]
                if not str(row["name"] or "").strip():
                    missing_name.append(cid)
                if not row["created_at"] or not row["updated_at"]:
                    missing_timestamps.append(cid)
                stage = str(row["stage"] or "").strip()
                if stage not in VALID_STORED_STAGES:
                    invalid_stage.append(cid)

                email = _normalize_email(row["email"])
                if email:
                    if not EMAIL_RE.fullmatch(email):
                        malformed_email.append(cid)
                    elif wid is not None:
                        identity_buckets[(int(wid), "email", email)].add(cid)

                raw_phone = str(row["phone"] or "").strip()
                if raw_phone:
                    digits = re.sub(r"\D", "", raw_phone)
                    if not 10 <= len(digits) <= 15:
                        malformed_phone.append(cid)
                    elif wid is not None:
                        identity_buckets[(int(wid), "phone", _normalize_phone(raw_phone))].add(cid)

                profile = _safe_profile(row["profile_details"])
                raw_linkedin, linkedin = _linkedin_from_profile(profile)
                if raw_linkedin and not linkedin:
                    malformed_linkedin.append(cid)
                elif linkedin and wid is not None:
                    identity_buckets[(int(wid), "linkedin", linkedin)].add(cid)

            for name, values in (
                ("malformed_candidate_email", malformed_email),
                ("malformed_candidate_phone", malformed_phone),
                ("malformed_candidate_linkedin", malformed_linkedin),
                ("candidate_missing_name", missing_name),
                ("candidate_missing_timestamps", missing_timestamps),
                ("invalid_pipeline_stage", invalid_stage),
            ):
                _record(report, name, values[:sample_limit], len(values), "warnings")

            conflicting_ids: set[int] = set()
            conflict_groups = 0
            for candidate_ids in identity_buckets.values():
                if len(candidate_ids) > 1:
                    conflict_groups += 1
                    conflicting_ids.update(candidate_ids)
            _record(
                report,
                "duplicate_candidate_identity_within_workspace",
                sorted(conflicting_ids)[:sample_limit],
                conflict_groups,
                "critical",
            )

        if {"candidates", "jobs"} <= tables:
            rows = con.execute(
                """SELECT c.id FROM candidates c LEFT JOIN jobs j ON j.id=c.job_id
                   WHERE c.job_id IS NOT NULL AND j.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "candidate_orphan_job", ids, total, "critical")
            rows = con.execute(
                """SELECT c.id FROM candidates c JOIN jobs j ON j.id=c.job_id
                   WHERE c.workspace_id<>j.workspace_id"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "candidate_job_cross_workspace", ids, total, "critical")

        for table in ("notes", "activity_log", "interviews"):
            if table not in tables or "candidates" not in tables:
                continue
            rows = con.execute(
                f"""SELECT x.id FROM {table} x LEFT JOIN candidates c ON c.id=x.candidate_id
                    WHERE c.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, f"orphan_{table}", ids, total, "critical")
            rows = con.execute(
                f"""SELECT x.id FROM {table} x JOIN candidates c ON c.id=x.candidate_id
                    WHERE x.workspace_id<>c.workspace_id"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, f"{table}_candidate_cross_workspace", ids, total, "critical")

        if {"interviews", "jobs"} <= tables:
            rows = con.execute(
                """SELECT i.id FROM interviews i LEFT JOIN jobs j ON j.id=i.job_id
                   WHERE i.job_id IS NOT NULL AND j.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "interview_orphan_job", ids, total, "critical")
            rows = con.execute(
                """SELECT i.id FROM interviews i JOIN jobs j ON j.id=i.job_id
                   WHERE i.workspace_id<>j.workspace_id"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "interview_job_cross_workspace", ids, total, "critical")

        if {"candidate_identities", "candidates"} <= tables:
            rows = con.execute(
                """SELECT ci.rowid AS id FROM candidate_identities ci
                   LEFT JOIN candidates c ON c.id=ci.candidate_id
                   WHERE c.id IS NULL"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "orphan_candidate_identities", ids, total, "critical")
            rows = con.execute(
                """SELECT ci.rowid AS id FROM candidate_identities ci
                   JOIN candidates c ON c.id=ci.candidate_id
                   WHERE ci.workspace_id<>c.workspace_id"""
            ).fetchall()
            ids, total = _ids(rows, limit=sample_limit)
            _record(report, "identity_candidate_cross_workspace", ids, total, "critical")

            indexed: dict[tuple[int, str, str], int] = {}
            for row in con.execute(
                "SELECT workspace_id,candidate_id,identity_type,identity_value FROM candidate_identities"
            ):
                indexed[(int(row["workspace_id"]), str(row["identity_type"]), str(row["identity_value"]))] = int(row["candidate_id"])

            mismatched: set[int] = set()
            for row in candidate_rows:
                if row["workspace_id"] is None:
                    continue
                wid = int(row["workspace_id"])
                cid = int(row["id"])
                email = _normalize_email(row["email"])
                phone = _normalize_phone(row["phone"])
                _, linkedin = _linkedin_from_profile(_safe_profile(row["profile_details"]))
                for identity_type, identity_value in (("email", email), ("phone", phone), ("linkedin", linkedin)):
                    if not identity_value:
                        continue
                    owner = indexed.get((wid, identity_type, identity_value))
                    if owner is not None and owner != cid:
                        mismatched.add(cid)
            _record(
                report,
                "candidate_identity_owner_mismatch",
                sorted(mismatched)[:sample_limit],
                len(mismatched),
                "critical",
            )

        integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
        report["sqlite_integrity_check"] = integrity
        if integrity.lower() != "ok":
            report["critical"].append("sqlite_integrity_check_failed")
            report["checks"]["sqlite_integrity_check_failed"] = {
                "severity": "critical", "count": 1, "ids": [], "truncated": False
            }

        report["critical"] = sorted(set(report["critical"]))
        report["warnings"] = sorted(set(report["warnings"]))
        report["ok"] = not report["critical"]
        return report
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ShortlistAI data-integrity audit")
    parser.add_argument("--db", default=os.getenv("SQLITE_PATH", "shortlistai.db"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_database(args.db)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("ShortlistAI data-integrity audit:", "PASS" if report["ok"] else "FAIL")
        print("Critical:", ", ".join(report["critical"]) or "none")
        print("Warnings:", ", ".join(report["warnings"]) or "none")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
