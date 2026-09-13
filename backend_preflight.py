from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

CRITICAL_TABLES = {
    "workspaces",
    "users",
    "auth_sessions",
    "jobs",
    "candidates",
    "notes",
    "activity_log",
    "interviews",
}

TENANT_TABLES = {"jobs", "candidates", "notes", "activity_log", "interviews"}
REQUIRED_INDEXES = {
    "idx_jobs_workspace",
    "idx_candidates_workspace",
    "idx_candidates_workspace_job",
    "idx_notes_workspace",
    "idx_activity_log_workspace",
    "idx_interviews_workspace",
}


def _table_names(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _index_names(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        if row[0]
    }


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def audit_database(db_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(db_path)
    report: dict[str, Any] = {
        "ok": False,
        "database": str(path),
        "errors": [],
        "warnings": [],
        "details": {},
    }

    if not path.exists():
        report["errors"].append("database file does not exist")
        return report

    try:
        con = sqlite3.connect(str(path), timeout=5)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        report["errors"].append(f"database connection failed: {exc}")
        return report

    try:
        tables = _table_names(con)
        indexes = _index_names(con)
        missing_tables = sorted(CRITICAL_TABLES - tables)
        if missing_tables:
            report["errors"].append(f"missing critical tables: {', '.join(missing_tables)}")

        missing_workspace_columns: list[str] = []
        for table in sorted(TENANT_TABLES & tables):
            if "workspace_id" not in _columns(con, table):
                missing_workspace_columns.append(table)
        if missing_workspace_columns:
            report["errors"].append(
                "tenant isolation column missing from: " + ", ".join(missing_workspace_columns)
            )

        missing_indexes = sorted(REQUIRED_INDEXES - indexes)
        if missing_indexes:
            report["warnings"].append(
                "recommended workspace indexes missing: " + ", ".join(missing_indexes)
            )

        foreign_keys = int(con.execute("PRAGMA foreign_keys").fetchone()[0])
        journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0])
        integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])

        if foreign_keys != 1:
            report["warnings"].append(
                "SQLite foreign key enforcement is disabled on this connection"
            )
        if integrity.lower() != "ok":
            report["errors"].append(f"SQLite integrity check failed: {integrity}")

        report["details"] = {
            "sqlite_version": sqlite3.sqlite_version,
            "journal_mode": journal_mode,
            "foreign_keys": bool(foreign_keys),
            "integrity_check": integrity,
            "tables": sorted(tables),
            "indexes": sorted(indexes),
            "tenant_tables": sorted(TENANT_TABLES & tables),
        }
        report["ok"] = not report["errors"]
        return report
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the ShortlistAI SQLite backend before deploy.")
    parser.add_argument(
        "--db",
        default=os.getenv("SQLITE_PATH", "shortlistai.db"),
        help="SQLite database path. Defaults to SQLITE_PATH or ./shortlistai.db",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    report = audit_database(args.db)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("ShortlistAI backend preflight:", "PASS" if report["ok"] else "FAIL")
        print("Database:", report["database"])
        for error in report["errors"]:
            print("ERROR:", error)
        for warning in report["warnings"]:
            print("WARN:", warning)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
