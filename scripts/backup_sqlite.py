from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.migrate_sqlite_to_postgres import source_counts, validate_source_isolation


def _integrity(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "unknown")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite(source_path: Path, destination_path: Path, *, overwrite: bool = False) -> dict:
    source_path = source_path.resolve()
    destination_path = destination_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if destination_path.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {destination_path}")
    if source_path == destination_path:
        raise ValueError("Backup destination must be different from the source database")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        destination_path.unlink()

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        integrity_before = _integrity(source)
        if integrity_before.lower() != "ok":
            raise RuntimeError(f"Source SQLite integrity check failed: {integrity_before}")
        validate_source_isolation(source)
        counts_before = source_counts(source)

        destination = sqlite3.connect(str(destination_path))
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
    finally:
        source.close()

    verified = sqlite3.connect(f"file:{destination_path}?mode=ro", uri=True)
    verified.row_factory = sqlite3.Row
    try:
        integrity_after = _integrity(verified)
        counts_after = source_counts(verified)
    finally:
        verified.close()

    if integrity_after.lower() != "ok":
        destination_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup SQLite integrity check failed: {integrity_after}")
    if counts_before != counts_after:
        destination_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Backup row-count verification failed: source={counts_before}, backup={counts_after}"
        )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_path),
        "backup": str(destination_path),
        "sha256": _sha256(destination_path),
        "size_bytes": destination_path.stat().st_size,
        "integrity": integrity_after,
        "row_counts": counts_after,
    }
    manifest_path = destination_path.with_suffix(destination_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and verify a consistent SQLite backup before PostgreSQL migration."
    )
    parser.add_argument("--sqlite-path", default=os.getenv("SQLITE_PATH", "shortlistai.db"))
    parser.add_argument("--output", required=True, help="Destination .db path for the verified backup")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = backup_sqlite(Path(args.sqlite_path), Path(args.output), overwrite=args.overwrite)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
