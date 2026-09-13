from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select

from scripts.backup_sqlite import backup_sqlite
from scripts.migrate_sqlite_to_postgres import migrate
from scripts.verify_sqlite_postgres_parity import verify
from shortlistai.db.models import Base
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url


def build_source(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    tables = Base.metadata.tables
    with engine.begin() as connection:
        connection.execute(tables["workspaces"].insert(), {"id": 1, "name": "Migration Test", "created_at": "2026-09-14T00:00:00Z"})
        connection.execute(
            tables["users"].insert(),
            {
                "id": 1,
                "workspace_id": 1,
                "full_name": "Migration Admin",
                "email": "migration@example.test",
                "password_hash": "hash",
                "password_salt": "salt",
                "role": "Workspace Admin",
                "created_at": "2026-09-14T00:00:00Z",
            },
        )
        connection.execute(
            tables["jobs"].insert(),
            {"id": 1, "workspace_id": 1, "title": "Backend Engineer", "jd": "Python FastAPI", "status": "Open", "created_at": "2026-09-14T00:00:00Z"},
        )
        connection.execute(
            tables["candidates"].insert(),
            {
                "id": 1,
                "workspace_id": 1,
                "name": "Migration Candidate",
                "email": "candidate@example.test",
                "skills": "Python, FastAPI, Pandas",
                "resume_text": "Python backend engineer with FastAPI and Pandas experience.",
                "job_id": 1,
                "stage": "Sourced",
                "created_at": "2026-09-14T00:00:00Z",
                "updated_at": "2026-09-14T00:00:00Z",
            },
        )
        connection.execute(
            tables["candidate_identities"].insert(),
            {
                "workspace_id": 1,
                "identity_type": "email",
                "identity_value": "candidate@example.test",
                "candidate_id": 1,
                "created_at": "2026-09-14T00:00:00Z",
            },
        )
        connection.execute(
            tables["notes"].insert(),
            {"id": 1, "workspace_id": 1, "candidate_id": 1, "note": "Migration note", "created_at": "2026-09-14T00:00:00Z"},
        )
        connection.execute(
            tables["activity_log"].insert(),
            {"id": 1, "workspace_id": 1, "candidate_id": 1, "action": "Created", "details": "fixture", "created_at": "2026-09-14T00:00:00Z"},
        )
        connection.execute(
            tables["interviews"].insert(),
            {
                "id": 1,
                "workspace_id": 1,
                "candidate_id": 1,
                "job_id": 1,
                "round_name": "L1",
                "interviewer_name": "Interviewer",
                "interviewer_email": "interviewer@example.test",
                "scheduled_at": "2026-09-15T10:00:00+05:30",
                "timezone": "Asia/Kolkata",
                "duration_minutes": 45,
                "meeting_url": "",
                "status": "Scheduled",
                "outcome": "Pending",
                "notes": "",
                "created_at": "2026-09-14T00:00:00Z",
                "updated_at": "2026-09-14T00:00:00Z",
            },
        )
    engine.dispose()


def main() -> None:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not is_postgres_url(database_url):
        print("SKIP: SQLite to PostgreSQL migration copy requires DATABASE_URL")
        return

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "source.db"
        backup_path = Path(directory) / "source.backup.db"
        build_source(source_path)

        backup_manifest = backup_sqlite(source_path, backup_path)
        assert backup_manifest["integrity"] == "ok"
        assert backup_manifest["row_counts"]["candidates"] == 1
        assert backup_manifest["sha256"]
        assert Path(backup_manifest["manifest"]).exists()

        dry_run = migrate(source_path, database_url, apply=False)
        assert dry_run["workspaces"] == 1
        assert dry_run["users"] == 1
        assert dry_run["candidates"] == 1
        assert dry_run["candidate_identities"] == 1

        copied = migrate(source_path, database_url, apply=True)
        assert copied["interviews"] == 1
        assert copied["candidate_identities"] == 1

        parity = verify(source_path, database_url, ["Python", "Java", "Python NOT Java"])
        assert parity["ok"] is True
        assert parity["row_counts"]["workspaces"] == 1
        assert parity["row_counts"]["users"] == 1
        assert parity["search_results"]["Python"] == [1]
        assert parity["search_results"]["Java"] == []
        assert parity["search_results"]["Python NOT Java"] == [1]

    target = create_database_engine(database_url)
    tables = Base.metadata.tables
    with target.connect() as connection:
        candidate = connection.execute(select(tables["candidates"])).mappings().one()
        assert candidate["name"] == "Migration Candidate"
        assert candidate["workspace_id"] == 1
        assert candidate["job_id"] == 1
        identity = connection.execute(select(tables["candidate_identities"])).mappings().one()
        assert identity["candidate_id"] == 1
        assert identity["identity_type"] == "email"
        assert identity["identity_value"] == "candidate@example.test"
        assert connection.execute(select(tables["notes"])).mappings().one()["candidate_id"] == 1
        assert connection.execute(select(tables["interviews"])).mappings().one()["workspace_id"] == 1
    target.dispose()
    print("SQLite to PostgreSQL backup, migration copy, and parity verification OK")


if __name__ == "__main__":
    main()
