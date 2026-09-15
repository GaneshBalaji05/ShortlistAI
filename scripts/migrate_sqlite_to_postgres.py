from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select, text

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

# These keys are intentionally stronger than simple row counts. They preserve the
# relationships that matter during cutover without logging the values themselves.
RECONCILIATION_KEYS = {
    "workspaces": ("id",),
    "users": ("id", "workspace_id"),
    "auth_sessions": ("token_hash", "user_id"),
    "password_reset_tokens": ("token_hash", "user_id"),
    "jobs": ("id", "workspace_id"),
    "candidates": ("id", "workspace_id", "job_id"),
    "candidate_identities": ("workspace_id", "candidate_id", "identity_type", "identity_value"),
    "notes": ("id", "workspace_id", "candidate_id"),
    "activity_log": ("id", "workspace_id", "candidate_id"),
    "interviews": ("id", "workspace_id", "candidate_id", "job_id"),
    "security_migrations": ("name",),
}


def source_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def source_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]


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
        raise RuntimeError(
            f"Target PostgreSQL schema is incomplete: {sorted(missing)}. Run 'alembic upgrade head' first."
        )

    with engine.connect() as connection:
        nonempty = {}
        for table in TABLE_ORDER:
            count = int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            if count:
                nonempty[table] = count
        if nonempty:
            raise RuntimeError(f"Target PostgreSQL database must be empty before migration: {nonempty}")


def validate_column_mapping(
    source: sqlite3.Connection,
    target_table: Table,
    table_name: str,
) -> list[str]:
    """Refuse a copy that would silently discard a SQLite source column."""
    source_cols = source_columns(source, table_name)
    target_cols = set(target_table.c.keys())
    unmapped = [column for column in source_cols if column not in target_cols]
    if unmapped:
        raise RuntimeError(
            f"Migration schema mismatch for {table_name}: source columns are missing from PostgreSQL: {unmapped}"
        )
    return source_cols


def _source_key_snapshot(
    source: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> set[tuple[Any, ...]]:
    available = set(source_columns(source, table_name))
    missing = [column for column in columns if column not in available]
    if missing:
        raise RuntimeError(f"Migration reconciliation key missing from SQLite {table_name}: {missing}")
    selected = ",".join(columns)
    return {tuple(row[column] for column in columns) for row in source.execute(f"SELECT {selected} FROM {table_name}")}


def _target_key_snapshot(target, table: Table, columns: tuple[str, ...]) -> set[tuple[Any, ...]]:
    missing = [column for column in columns if column not in table.c]
    if missing:
        raise RuntimeError(f"Migration reconciliation key missing from PostgreSQL {table.name}: {missing}")
    rows = target.execute(select(*(table.c[column] for column in columns))).all()
    return {tuple(row) for row in rows}


def reconcile_copy(
    source: sqlite3.Connection,
    target,
    metadata: MetaData,
    available_source_tables: set[str],
) -> dict[str, dict[str, int]]:
    """Verify counts and stable record identities inside the copy transaction.

    Any mismatch raises before the surrounding transaction commits, so a bad copy
    is rolled back rather than becoming a partially verified migration target.
    """
    expected_counts = source_counts(source)
    actual_counts: dict[str, int] = {}
    count_mismatches: list[str] = []
    identity_mismatches: list[str] = []

    for table_name in TABLE_ORDER:
        if table_name not in available_source_tables:
            continue
        table = Table(table_name, metadata, autoload_with=target, extend_existing=True)
        actual = int(target.execute(select(text("COUNT(*)")).select_from(table)).scalar_one())
        actual_counts[table_name] = actual
        if actual != expected_counts.get(table_name, 0):
            count_mismatches.append(table_name)

        key_columns = RECONCILIATION_KEYS.get(table_name)
        if key_columns:
            source_keys = _source_key_snapshot(source, table_name, key_columns)
            target_keys = _target_key_snapshot(target, table, key_columns)
            if source_keys != target_keys:
                identity_mismatches.append(table_name)

    if count_mismatches or identity_mismatches:
        details: list[str] = []
        if count_mismatches:
            details.append("row count mismatch: " + ", ".join(sorted(count_mismatches)))
        if identity_mismatches:
            details.append("record identity mismatch: " + ", ".join(sorted(identity_mismatches)))
        raise RuntimeError("PostgreSQL migration reconciliation failed: " + "; ".join(details))

    return {"source_counts": expected_counts, "target_counts": actual_counts}


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
                    target_table = Table(table_name, metadata, autoload_with=target, extend_existing=True)
                    source_cols = validate_column_mapping(source, target_table, table_name)
                    rows = source.execute(f"SELECT * FROM {table_name}").fetchall()
                    if not rows:
                        continue
                    payload = [{column: row[column] for column in source_cols} for row in rows]
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

                # This runs before transaction commit. A mismatch raises and rolls back
                # the entire copy rather than leaving an unverified target populated.
                reconcile_copy(source, target, metadata, available)
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
    mode = "migration complete and reconciled" if args.apply else "dry-run complete"
    print(f"SQLite -> PostgreSQL {mode}: {counts}")


if __name__ == "__main__":
    main()
