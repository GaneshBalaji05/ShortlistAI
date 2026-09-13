from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, delete, select

from scripts.migrate_sqlite_to_postgres import migrate, reconcile_copy, source_tables
from shortlistai.db.models import Base
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url


def build_source(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    tables = Base.metadata.tables
    with engine.begin() as connection:
        connection.execute(
            tables["workspaces"].insert(),
            [
                {"id": 1, "name": "Migration One", "created_at": "2026-09-14T00:00:00Z"},
                {"id": 2, "name": "Migration Two", "created_at": "2026-09-14T00:00:00Z"},
            ],
        )
        connection.execute(
            tables["users"].insert(),
            [
                {
                    "id": 1,
                    "workspace_id": 1,
                    "full_name": "Migration Admin One",
                    "email": "migration-one@example.test",
                    "password_hash": "hash1",
                    "password_salt": "salt1",
                    "role": "Workspace Admin",
                    "created_at": "2026-09-14T00:00:00Z",
                },
                {
                    "id": 2,
                    "workspace_id": 2,
                    "full_name": "Migration Admin Two",
                    "email": "migration-two@example.test",
                    "password_hash": "hash2",
                    "password_salt": "salt2",
                    "role": "Workspace Admin",
                    "created_at": "2026-09-14T00:00:00Z",
                },
            ],
        )
        connection.execute(
            tables["auth_sessions"].insert(),
            [
                {"token_hash": "session-one", "user_id": 1, "created_at": "2026-09-14", "expires_at": "2026-10-14"},
                {"token_hash": "session-two", "user_id": 2, "created_at": "2026-09-14", "expires_at": "2026-10-14"},
            ],
        )
        connection.execute(
            tables["jobs"].insert(),
            [
                {"id": 1, "workspace_id": 1, "title": "Backend Engineer", "jd": "Python FastAPI", "status": "Open", "created_at": "2026-09-14T00:00:00Z"},
                {"id": 2, "workspace_id": 2, "title": "Java Engineer", "jd": "Java Spring Boot", "status": "Open", "created_at": "2026-09-14T00:00:00Z"},
            ],
        )
        connection.execute(
            tables["candidates"].insert(),
            [
                {
                    "id": 1,
                    "workspace_id": 1,
                    "name": "Migration Candidate One",
                    "email": "shared@example.test",
                    "job_id": 1,
                    "stage": "Sourced",
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
                {
                    "id": 2,
                    "workspace_id": 2,
                    "name": "Migration Candidate Two",
                    "email": "shared@example.test",
                    "job_id": 2,
                    "stage": "Applied",
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
            ],
        )
        connection.execute(
            tables["candidate_identities"].insert(),
            [
                {
                    "workspace_id": 1,
                    "identity_type": "email",
                    "identity_value": "shared@example.test",
                    "candidate_id": 1,
                    "created_at": "2026-09-14T00:00:00Z",
                },
                {
                    "workspace_id": 1,
                    "identity_type": "linkedin",
                    "identity_value": "shared-linkedin",
                    "candidate_id": 1,
                    "created_at": "2026-09-14T00:00:00Z",
                },
                {
                    "workspace_id": 2,
                    "identity_type": "email",
                    "identity_value": "shared@example.test",
                    "candidate_id": 2,
                    "created_at": "2026-09-14T00:00:00Z",
                },
                {
                    "workspace_id": 2,
                    "identity_type": "linkedin",
                    "identity_value": "shared-linkedin",
                    "candidate_id": 2,
                    "created_at": "2026-09-14T00:00:00Z",
                },
            ],
        )
        connection.execute(
            tables["notes"].insert(),
            [
                {"id": 1, "workspace_id": 1, "candidate_id": 1, "note": "Migration note one", "created_at": "2026-09-14T00:00:00Z"},
                {"id": 2, "workspace_id": 2, "candidate_id": 2, "note": "Migration note two", "created_at": "2026-09-14T00:00:00Z"},
            ],
        )
        connection.execute(
            tables["activity_log"].insert(),
            [
                {"id": 1, "workspace_id": 1, "candidate_id": 1, "action": "Created", "details": "fixture", "created_at": "2026-09-14T00:00:00Z"},
                {"id": 2, "workspace_id": 2, "candidate_id": 2, "action": "Created", "details": "fixture", "created_at": "2026-09-14T00:00:00Z"},
            ],
        )
        connection.execute(
            tables["interviews"].insert(),
            [
                {
                    "id": 1,
                    "workspace_id": 1,
                    "candidate_id": 1,
                    "job_id": 1,
                    "round_name": "L1",
                    "interviewer_name": "Interviewer One",
                    "interviewer_email": "interviewer-one@example.test",
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
                {
                    "id": 2,
                    "workspace_id": 2,
                    "candidate_id": 2,
                    "job_id": 2,
                    "round_name": "L1",
                    "interviewer_name": "Interviewer Two",
                    "interviewer_email": "interviewer-two@example.test",
                    "scheduled_at": "2026-09-15T11:00:00+05:30",
                    "timezone": "Asia/Kolkata",
                    "duration_minutes": 45,
                    "meeting_url": "",
                    "status": "Scheduled",
                    "outcome": "Pending",
                    "notes": "",
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
            ],
        )
    engine.dispose()


def verify_reconciliation_detects_target_drift(source_path: Path, database_url: str) -> None:
    source = sqlite3.connect(str(source_path))
    source.row_factory = sqlite3.Row
    target = create_database_engine(database_url)
    metadata = Base.metadata
    try:
        with target.connect() as connection:
            transaction = connection.begin()
            try:
                identities = Base.metadata.tables["candidate_identities"]
                connection.execute(
                    delete(identities).where(
                        (identities.c.workspace_id == 2)
                        & (identities.c.identity_type == "linkedin")
                    )
                )
                try:
                    reconcile_copy(source, connection, metadata, source_tables(source))
                except RuntimeError as exc:
                    message = str(exc)
                    assert "reconciliation failed" in message.lower()
                    assert "candidate_identities" in message
                else:
                    raise AssertionError("reconciliation accepted a target with a missing candidate identity")
            finally:
                transaction.rollback()
    finally:
        target.dispose()
        source.close()


def main() -> None:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not is_postgres_url(database_url):
        print("SKIP: SQLite to PostgreSQL migration copy requires DATABASE_URL")
        return

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "source.db"
        build_source(source_path)

        dry_run = migrate(source_path, database_url, apply=False)
        assert dry_run["workspaces"] == 2
        assert dry_run["jobs"] == 2
        assert dry_run["candidates"] == 2
        assert dry_run["candidate_identities"] == 4
        assert dry_run["interviews"] == 2

        copied = migrate(source_path, database_url, apply=True)
        assert copied == dry_run

        target = create_database_engine(database_url)
        tables = Base.metadata.tables
        with target.connect() as connection:
            assert len(connection.execute(select(tables["workspaces"])).all()) == 2
            assert len(connection.execute(select(tables["jobs"])).all()) == 2
            candidates = connection.execute(select(tables["candidates"])).mappings().all()
            assert {(row["id"], row["workspace_id"], row["job_id"]) for row in candidates} == {
                (1, 1, 1),
                (2, 2, 2),
            }
            identities = connection.execute(select(tables["candidate_identities"])).mappings().all()
            assert {
                (row["workspace_id"], row["candidate_id"], row["identity_type"], row["identity_value"])
                for row in identities
            } == {
                (1, 1, "email", "shared@example.test"),
                (1, 1, "linkedin", "shared-linkedin"),
                (2, 2, "email", "shared@example.test"),
                (2, 2, "linkedin", "shared-linkedin"),
            }
            assert len(connection.execute(select(tables["notes"])).all()) == 2
            assert len(connection.execute(select(tables["interviews"])).all()) == 2
        target.dispose()

        # Prove the reconciliation guard detects both count/key drift while keeping
        # the real target unchanged by rolling the test mutation back.
        verify_reconciliation_detects_target_drift(source_path, database_url)

    print("SQLite to PostgreSQL migration copy + reconciliation OK")


if __name__ == "__main__":
    main()
