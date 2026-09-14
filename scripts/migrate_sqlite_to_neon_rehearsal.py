from __future__ import annotations

from pathlib import Path

import scripts.migrate_sqlite_to_postgres as base

# Phase 2 must preserve every current application-owned production table. The latest
# Sheet2 release introduced this seed metadata table after the original PostgreSQL
# migration foundation was written.
TABLE_ORDER = base.TABLE_ORDER + ("master_data_seed_log",)
WORKSPACE_TABLES = base.WORKSPACE_TABLES + ("master_data_seed_log",)
RECONCILIATION_KEYS = {
    **base.RECONCILIATION_KEYS,
    "master_data_seed_log": (
        "workspace_id",
        "dataset_version",
        "payload_sha256",
    ),
}


def _install_rehearsal_contract() -> None:
    """Extend the existing guarded migrator without changing live runtime behavior."""
    base.TABLE_ORDER = TABLE_ORDER
    base.WORKSPACE_TABLES = WORKSPACE_TABLES
    base.RECONCILIATION_KEYS = RECONCILIATION_KEYS


def source_counts(connection):
    _install_rehearsal_contract()
    return base.source_counts(connection)


def validate_source_isolation(connection) -> None:
    _install_rehearsal_contract()
    base.validate_source_isolation(connection)


def migrate(sqlite_path: Path, database_url: str, apply: bool = False) -> dict[str, int]:
    _install_rehearsal_contract()
    return base.migrate(sqlite_path, database_url, apply=apply)


def main() -> None:
    args = base.parse_args()
    counts = migrate(Path(args.sqlite_path), args.database_url, apply=args.apply)
    mode = "migration complete and reconciled" if args.apply else "dry-run complete"
    print(f"SQLite -> Neon PostgreSQL rehearsal {mode}: {counts}")


if __name__ == "__main__":
    main()
