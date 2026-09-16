from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import text

from scripts.backup_sqlite import backup_sqlite
from scripts.migrate_sqlite_to_neon_rehearsal import migrate
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url


def build_current_source(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """CREATE TABLE workspaces(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        con.execute(
            """CREATE TABLE master_data_seed_log(
                workspace_id INTEGER NOT NULL,
                dataset_version TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                seeded_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id,dataset_version)
            )"""
        )
        con.execute(
            "INSERT INTO workspaces(id,name,created_at) VALUES(1,'Master Data QA','2026-09-14T00:00:00Z')"
        )
        con.execute(
            """INSERT INTO master_data_seed_log(
                workspace_id,dataset_version,payload_sha256,row_count,seeded_at
            ) VALUES(1,'sheet2-v1',?,308,'2026-09-14T00:00:00Z')""",
            ("b" * 64,),
        )
        con.commit()
    finally:
        con.close()


def main() -> None:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not is_postgres_url(database_url):
        print("SKIP: Neon rehearsal contract requires PostgreSQL DATABASE_URL")
        return

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "live-source.db"
        snapshot = Path(directory) / "verified-snapshot.db"
        build_current_source(source)

        manifest = backup_sqlite(source, snapshot)
        assert manifest["integrity"] == "ok"
        assert manifest["row_counts"]["workspaces"] == 1
        assert manifest["row_counts"]["master_data_seed_log"] == 1
        assert len(manifest["sha256"]) == 64

        dry_run = migrate(snapshot, database_url, apply=False)
        assert dry_run["workspaces"] == 1
        assert dry_run["master_data_seed_log"] == 1

        copied = migrate(snapshot, database_url, apply=True)
        assert copied == dry_run

        engine = create_database_engine(database_url)
        try:
            with engine.connect() as connection:
                workspace = connection.execute(
                    text("SELECT id,name FROM workspaces WHERE id=1")
                ).mappings().one()
                assert workspace["name"] == "Master Data QA"
                seed = connection.execute(
                    text(
                        "SELECT workspace_id,dataset_version,payload_sha256,row_count "
                        "FROM master_data_seed_log WHERE workspace_id=1"
                    )
                ).mappings().one()
                assert seed["dataset_version"] == "sheet2-v1"
                assert seed["payload_sha256"] == "b" * 64
                assert seed["row_count"] == 308
        finally:
            engine.dispose()

    print("Verified SQLite snapshot -> Neon rehearsal migration contract OK")


if __name__ == "__main__":
    main()
