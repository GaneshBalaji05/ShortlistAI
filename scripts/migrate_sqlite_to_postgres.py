from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, Table, func, inspect, select, text

from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url

TABLE_ORDER = (
    "workspaces",
    "users",
    "auth_sessions",
    "password_reset_tokens",
    "jobs",
    "candidates",
    "candidate_identities",
    "ingestion_batches",
    "ingestion_items",
    "notes",
    "activity_log",
    "interviews",
    "security_migrations",
)
WORKSPACE_TABLES = (
    "jobs",
    "candidates",
    "candidate_identities",
    "ingestion_batches",
    "ingestion_items",
    "notes",
    "activity_log",
    "interviews",
)
SEQUENCE_TABLES = (
    "workspaces",
    "users",
    "jobs",
    "candidates",
    "ingestion_batches",
    "ingestion_items",
    "notes",
    "activity_log",
    "interviews",
)


def source_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def source_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]


def source_counts(connection: sqlite3.Connection) -> dict[str, int]:
    available = source_tables(connection)
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in TABLE_ORDER
        if table in available
    }


def validate_source_isolation(connection: sqlite3.Connection) -> None:
    available = source_tables(connection)
    errors: list[str] = []
    for table in WORKSPACE_TABLES:
        if table not in available:
            continue
        columns = source_columns(connection, table)
        if "workspace_id" not in columns:
            errors.append(f"{table}.workspace_id is missing")
            continue
        nulls = int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL").fetchone()[0])
        if nulls:
            errors.append(f"{table} contains {nulls} rows without workspace_id")
    if errors:
        raise RuntimeError("Source tenant isolation is not migration-safe: " + "; ".join(errors))


def validate_target(engine) -> None:
    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    required = set(TABLE_ORDER)
    missing = required - available
    if missing:
        raise RuntimeError(f"Target PostgreSQL schema is incomplete: {sorted(missing)}. Run 'alembic upgrade head' first.")

    with engine.connect() as connection:
        nonempty = {}
        for table in TABLE_ORDER:
            count = int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            if count:
                nonempty[table] = count
        if nonempty:
            raise RuntimeError(f"Target PostgreSQL database must be empty before migration: {nonempty}")


def migrate(sqlite_path: Path, database_url: str, apply: bool = False) -> dict[str, int]:
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)

    source = sqlite3.connect(str(sqlite_path))
    source.row_factory = sqlite3.Row
    try:
        validate_source_isolation(source)
        counts = source_counts(source)
        if not apply:
            return counts

        target_url = normalize_database_url(database_url)
        if not is_postgres_url(target_url):
            raise RuntimeError("Migration target must be PostgreSQL. Set DATABASE_URL to a PostgreSQL connection string.")
        engine = create_database_engine(target_url)
        try:
            validate_target(engine)
            metadata = MetaData()
            available = source_tables(source)
            with engine.begin() as target:
                for table_name in TABLE_ORDER:
                    if table_name not in available:
                        continue
                    target_table = Table(table_name, metadata, autoload_with=target)
                    target_columns = set(target_table.c.keys())
                    common_columns = [column for column in source_columns(source, table_name) if column in target_columns]
                    rows = source.execute(f"SELECT * FROM {table_name}").fetchall()
                    if not rows:
                        continue
                    payload = [{column: row[column] for column in common_columns} for row in rows]
                    target.execute(target_table.insert(), payload)

                for table_name in SEQUENCE_TABLES:
                    target.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1), "
                            "(SELECT COUNT(*) > 0 FROM " + table_name + "))"
                        ),
                        {"table_name": table_name},
                    )
            return counts
        finally:
            engine.dispose()
    finally:
        source.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely migrate ShortlistAI SQLite data into an empty PostgreSQL schema.")
    parser.add_argument("--sqlite-path", default=os.getenv("SQLITE_PATH", "shortlistai.db"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the copy. Without this flag the command only validates the source and prints row counts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = migrate(Path(args.sqlite_path), args.database_url, apply=args.apply)
    mode = "migration complete" if args.apply else "dry-run complete"
    print(f"SQLite -> PostgreSQL {mode}: {counts}")


if __name__ == "__main__":
    main()
