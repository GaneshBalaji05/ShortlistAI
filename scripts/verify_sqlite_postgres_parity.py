from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, select

from boolean_search import matches_boolean
from scripts.migrate_sqlite_to_postgres import TABLE_ORDER, WORKSPACE_TABLES, source_counts, validate_source_isolation
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url

DEFAULT_QUERIES = (
    "Java",
    "Python",
    'Java AND ("Spring Boot" OR Spring)',
    "Python NOT Java",
)


def _decode_profile(value: Any) -> Any:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return {}


def _sqlite_candidates(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "candidates" not in tables:
        return []
    rows = connection.execute("SELECT * FROM candidates ORDER BY id").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["profile_details"] = _decode_profile(item.get("profile_details"))
        result.append(item)
    return result


def _postgres_counts(engine) -> dict[str, int]:
    metadata = MetaData()
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table_name in TABLE_ORDER:
            table = Table(table_name, metadata, autoload_with=connection)
            counts[table_name] = len(connection.execute(select(table)).all())
    return counts


def _postgres_candidates(engine) -> list[dict[str, Any]]:
    metadata = MetaData()
    with engine.connect() as connection:
        candidates = Table("candidates", metadata, autoload_with=connection)
        rows = connection.execute(select(candidates).order_by(candidates.c.id)).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        item["profile_details"] = _decode_profile(item.get("profile_details"))
        result.append(item)
    return result


def _search_results(candidates: list[dict[str, Any]], query: str) -> list[int]:
    return sorted(int(candidate["id"]) for candidate in candidates if matches_boolean(query, candidate))


def _workspace_nulls_sqlite(connection: sqlite3.Connection) -> dict[str, int]:
    available = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {}
    for table in WORKSPACE_TABLES:
        if table in available:
            result[table] = int(
                connection.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL").fetchone()[0]
            )
    return result


def _workspace_nulls_postgres(engine) -> dict[str, int]:
    metadata = MetaData()
    result = {}
    with engine.connect() as connection:
        for table_name in WORKSPACE_TABLES:
            table = Table(table_name, metadata, autoload_with=connection)
            result[table_name] = len(
                connection.execute(select(table).where(table.c.workspace_id.is_(None))).all()
            )
    return result


def verify(sqlite_path: Path, database_url: str, queries: list[str] | None = None) -> dict[str, Any]:
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)
    target_url = normalize_database_url(database_url)
    if not is_postgres_url(target_url):
        raise RuntimeError("Parity verification requires a PostgreSQL DATABASE_URL")

    source = sqlite3.connect(f"file:{sqlite_path.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    engine = create_database_engine(target_url)
    try:
        validate_source_isolation(source)
        sqlite_counts = source_counts(source)
        postgres_counts = _postgres_counts(engine)
        comparable_postgres = {key: postgres_counts[key] for key in sqlite_counts}
        if sqlite_counts != comparable_postgres:
            raise RuntimeError(
                f"Row-count mismatch: sqlite={sqlite_counts}, postgres={comparable_postgres}"
            )

        sqlite_nulls = _workspace_nulls_sqlite(source)
        postgres_nulls = _workspace_nulls_postgres(engine)
        if any(sqlite_nulls.values()) or any(postgres_nulls.values()):
            raise RuntimeError(
                f"Workspace isolation mismatch/null ownership: sqlite={sqlite_nulls}, postgres={postgres_nulls}"
            )

        sqlite_candidates = _sqlite_candidates(source)
        postgres_candidates = _postgres_candidates(engine)
        sqlite_ids = [int(item["id"]) for item in sqlite_candidates]
        postgres_ids = [int(item["id"]) for item in postgres_candidates]
        if sqlite_ids != postgres_ids:
            raise RuntimeError(
                f"Candidate primary-key mismatch: sqlite={sqlite_ids[:20]}, postgres={postgres_ids[:20]}"
            )

        search_checks = {}
        for query in queries or list(DEFAULT_QUERIES):
            source_results = _search_results(sqlite_candidates, query)
            target_results = _search_results(postgres_candidates, query)
            if source_results != target_results:
                raise RuntimeError(
                    f"Boolean search parity failed for {query!r}: sqlite={source_results}, postgres={target_results}"
                )
            search_checks[query] = source_results

        return {
            "ok": True,
            "row_counts": sqlite_counts,
            "workspace_nulls": sqlite_nulls,
            "candidate_ids": sqlite_ids,
            "search_results": search_checks,
        }
    finally:
        source.close()
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ShortlistAI SQLite source data with a migrated PostgreSQL target."
    )
    parser.add_argument("--sqlite-path", default=os.getenv("SQLITE_PATH", "shortlistai.db"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Representative Boolean query to compare. Repeat for multiple queries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = verify(Path(args.sqlite_path), args.database_url, args.queries)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
