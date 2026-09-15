from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine


MAX_BATCH_ITEMS = 800
MAX_CHUNK_ITEMS = 25
TERMINAL_SUCCESS = {"created", "merged"}
TERMINAL_ITEM_STATES = TERMINAL_SUCCESS | {"failed"}

metadata = MetaData()
# Reference-only table declarations let the ingestion tables carry real foreign keys
# without asking this module to own/create the existing application tables.
Table("workspaces", metadata, Column("id", Integer, primary_key=True))
Table("users", metadata, Column("id", Integer, primary_key=True))
Table("jobs", metadata, Column("id", Integer, primary_key=True))
Table("candidates", metadata, Column("id", Integer, primary_key=True))

ingestion_batches = Table(
    "ingestion_batches",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workspace_id", Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
    Column("source", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("total_count", Integer, nullable=False),
    Column("processed_count", Integer, nullable=False, default=0),
    Column("created_count", Integer, nullable=False, default=0),
    Column("merged_count", Integer, nullable=False, default=0),
    Column("failed_count", Integer, nullable=False, default=0),
    Column("created_at", Text, nullable=False),
    Column("started_at", Text, nullable=True),
    Column("completed_at", Text, nullable=True),
    Column("updated_at", Text, nullable=False),
    Index("idx_ingestion_batches_workspace", "workspace_id"),
    Index("idx_ingestion_batches_workspace_status", "workspace_id", "status"),
)

ingestion_items = Table(
    "ingestion_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workspace_id", Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("batch_id", Integer, ForeignKey("ingestion_batches.id", ondelete="CASCADE"), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("source_filename", Text, nullable=False),
    Column("content_hash", String(64), nullable=True),
    Column("status", String(32), nullable=False),
    Column("candidate_id", Integer, ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True),
    Column("error_code", String(64), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", Text, nullable=False),
    Column("processed_at", Text, nullable=True),
    UniqueConstraint(
        "workspace_id",
        "batch_id",
        "idempotency_key",
        name="uq_ingestion_items_workspace_batch_key",
    ),
    Index("idx_ingestion_items_workspace_batch", "workspace_id", "batch_id"),
    Index("idx_ingestion_items_workspace_status", "workspace_id", "status"),
)


class IngestionError(RuntimeError):
    pass


class IngestionNotFound(IngestionError):
    pass


class IngestionConflict(IngestionError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_ingestion_schema(engine: Engine) -> None:
    """Create only the two ingestion tables for the current runtime database.

    Production still boots on SQLite today, while the migration target is PostgreSQL.
    SQLAlchemy emits dialect-appropriate DDL here; Alembic remains the source of truth for
    managed PostgreSQL cutover.
    """

    ingestion_batches.create(engine, checkfirst=True)
    ingestion_items.create(engine, checkfirst=True)


def _clean_manifest(items: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        key = str(raw.get("idempotency_key") or "").strip()
        filename = str(raw.get("source_filename") or "").strip()
        if not key:
            raise ValueError("Every ingestion item requires an idempotency_key")
        if len(key) > 128:
            raise ValueError("idempotency_key must be 128 characters or fewer")
        if key in seen:
            raise ValueError(f"Duplicate idempotency_key in manifest: {key}")
        if not filename:
            raise ValueError(f"source_filename is required for item {key}")
        seen.add(key)
        clean.append({"idempotency_key": key, "source_filename": filename})
    if not clean:
        raise ValueError("Add at least one item to the ingestion batch")
    if len(clean) > MAX_BATCH_ITEMS:
        raise ValueError(f"Ingestion batch limit is {MAX_BATCH_ITEMS} items")
    return clean


@dataclass(frozen=True)
class IngestionStore:
    engine: Engine
    workspace_id: int

    def __post_init__(self) -> None:
        ensure_ingestion_schema(self.engine)

    def _batch_row(self, connection: Connection, batch_id: int) -> Mapping[str, Any]:
        row = connection.execute(
            select(ingestion_batches).where(
                and_(
                    ingestion_batches.c.id == int(batch_id),
                    ingestion_batches.c.workspace_id == int(self.workspace_id),
                )
            )
        ).mappings().first()
        if row is None:
            raise IngestionNotFound("Ingestion batch not found in this workspace")
        return row

    def create_batch(
        self,
        *,
        created_by: int,
        job_id: int | None,
        source: str,
        items: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        manifest = _clean_manifest(items)
        now = _utcnow()
        with self.engine.begin() as connection:
            if job_id is not None:
                owned_job = connection.execute(
                    select(metadata.tables["jobs"].c.id).where(
                        metadata.tables["jobs"].c.id == int(job_id)
                    )
                ).first()
                # The runtime jobs table has workspace_id; use an explicit textual check
                # because the reference-only declaration intentionally exposes only id.
                owned_job = connection.exec_driver_sql(
                    "SELECT id FROM jobs WHERE id=? AND workspace_id=?"
                    if self.engine.dialect.name == "sqlite"
                    else "SELECT id FROM jobs WHERE id=%s AND workspace_id=%s",
                    (int(job_id), int(self.workspace_id)),
                ).first()
                if owned_job is None:
                    raise IngestionNotFound("Job not found in this workspace")

            result = connection.execute(
                insert(ingestion_batches).values(
                    workspace_id=int(self.workspace_id),
                    created_by=int(created_by),
                    job_id=int(job_id) if job_id is not None else None,
                    source=(source or "Bulk profile upload").strip() or "Bulk profile upload",
                    status="pending",
                    total_count=len(manifest),
                    processed_count=0,
                    created_count=0,
                    merged_count=0,
                    failed_count=0,
                    created_at=now,
                    started_at=None,
                    completed_at=None,
                    updated_at=now,
                )
            )
            batch_id = int(result.inserted_primary_key[0])
            connection.execute(
                insert(ingestion_items),
                [
                    {
                        "workspace_id": int(self.workspace_id),
                        "batch_id": batch_id,
                        "idempotency_key": item["idempotency_key"],
                        "source_filename": item["source_filename"],
                        "content_hash": None,
                        "status": "pending",
                        "candidate_id": None,
                        "error_code": None,
                        "error_message": None,
                        "attempts": 0,
                        "created_at": now,
                        "processed_at": None,
                    }
                    for item in manifest
                ],
            )
        return self.get_batch(batch_id)

    def get_batch(self, batch_id: int) -> dict[str, Any]:
        with self.engine.connect() as connection:
            batch = dict(self._batch_row(connection, batch_id))
            status_rows = connection.execute(
                select(ingestion_items.c.status, func.count().label("count"))
                .where(
                    and_(
                        ingestion_items.c.workspace_id == int(self.workspace_id),
                        ingestion_items.c.batch_id == int(batch_id),
                    )
                )
                .group_by(ingestion_items.c.status)
            ).all()
        by_status = {str(status): int(count) for status, count in status_rows}
        created = by_status.get("created", 0)
        merged = by_status.get("merged", 0)
        failed = by_status.get("failed", 0)
        processing = by_status.get("processing", 0)
        processed = created + merged
        total = int(batch["total_count"])
        pending = max(0, total - processed - failed)
        batch.update(
            {
                "processed_count": processed,
                "created_count": created,
                "merged_count": merged,
                "failed_count": failed,
                "pending_count": pending,
                "processing_count": processing,
                "registered_count": sum(by_status.values()),
                "item_status_counts": by_status,
            }
        )
        return batch

    def get_item(self, batch_id: int, idempotency_key: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ingestion_items).where(
                    and_(
                        ingestion_items.c.workspace_id == int(self.workspace_id),
                        ingestion_items.c.batch_id == int(batch_id),
                        ingestion_items.c.idempotency_key == str(idempotency_key),
                    )
                )
            ).mappings().first()
            return dict(row) if row else None

    def claim_item(
        self,
        *,
        batch_id: int,
        idempotency_key: str,
        source_filename: str,
        content_hash: str,
    ) -> dict[str, Any]:
        now = _utcnow()
        with self.engine.begin() as connection:
            batch = self._batch_row(connection, batch_id)
            row = connection.execute(
                select(ingestion_items).where(
                    and_(
                        ingestion_items.c.workspace_id == int(self.workspace_id),
                        ingestion_items.c.batch_id == int(batch_id),
                        ingestion_items.c.idempotency_key == str(idempotency_key),
                    )
                )
            ).mappings().first()
            if row is None:
                raise IngestionNotFound("Ingestion item not found in this batch")
            previous_hash = str(row.get("content_hash") or "")
            if previous_hash and previous_hash != content_hash:
                raise IngestionConflict("Idempotency key was reused with different file content")
            if str(row["status"]) in TERMINAL_SUCCESS:
                return {**dict(row), "already_done": True}

            connection.execute(
                update(ingestion_items)
                .where(ingestion_items.c.id == int(row["id"]))
                .values(
                    source_filename=(source_filename or row["source_filename"]),
                    content_hash=content_hash,
                    status="processing",
                    error_code=None,
                    error_message=None,
                    attempts=int(row["attempts"] or 0) + 1,
                    processed_at=None,
                )
            )
            connection.execute(
                update(ingestion_batches)
                .where(ingestion_batches.c.id == int(batch_id))
                .values(
                    status="processing",
                    started_at=batch["started_at"] or now,
                    completed_at=None,
                    updated_at=now,
                )
            )
            refreshed = connection.execute(
                select(ingestion_items).where(ingestion_items.c.id == int(row["id"]))
            ).mappings().one()
            return {**dict(refreshed), "already_done": False}

    def complete_item(
        self,
        *,
        batch_id: int,
        idempotency_key: str,
        candidate_id: int,
        merged: bool,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            self._batch_row(connection, batch_id)
            result = connection.execute(
                update(ingestion_items)
                .where(
                    and_(
                        ingestion_items.c.workspace_id == int(self.workspace_id),
                        ingestion_items.c.batch_id == int(batch_id),
                        ingestion_items.c.idempotency_key == str(idempotency_key),
                    )
                )
                .values(
                    status="merged" if merged else "created",
                    candidate_id=int(candidate_id),
                    error_code=None,
                    error_message=None,
                    processed_at=_utcnow(),
                )
            )
            if result.rowcount == 0:
                raise IngestionNotFound("Ingestion item not found in this batch")
            self._refresh_batch(connection, batch_id)
        return self.get_batch(batch_id)

    def fail_item(
        self,
        *,
        batch_id: int,
        idempotency_key: str,
        error_code: str,
        error_message: str,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            self._batch_row(connection, batch_id)
            result = connection.execute(
                update(ingestion_items)
                .where(
                    and_(
                        ingestion_items.c.workspace_id == int(self.workspace_id),
                        ingestion_items.c.batch_id == int(batch_id),
                        ingestion_items.c.idempotency_key == str(idempotency_key),
                    )
                )
                .values(
                    status="failed",
                    candidate_id=None,
                    error_code=(error_code or "processing_error")[:64],
                    error_message=(error_message or "Unknown ingestion error")[:2000],
                    processed_at=_utcnow(),
                )
            )
            if result.rowcount == 0:
                raise IngestionNotFound("Ingestion item not found in this batch")
            self._refresh_batch(connection, batch_id)
        return self.get_batch(batch_id)

    def _refresh_batch(self, connection: Connection, batch_id: int) -> None:
        batch = self._batch_row(connection, batch_id)
        rows = connection.execute(
            select(ingestion_items.c.status).where(
                and_(
                    ingestion_items.c.workspace_id == int(self.workspace_id),
                    ingestion_items.c.batch_id == int(batch_id),
                )
            )
        ).scalars().all()
        created = sum(status == "created" for status in rows)
        merged = sum(status == "merged" for status in rows)
        failed = sum(status == "failed" for status in rows)
        processed = created + merged
        total = int(batch["total_count"])
        terminal = processed + failed == total
        status = "completed" if terminal and failed == 0 else "completed_with_errors" if terminal else "processing"
        now = _utcnow()
        connection.execute(
            update(ingestion_batches)
            .where(ingestion_batches.c.id == int(batch_id))
            .values(
                status=status,
                processed_count=processed,
                created_count=created,
                merged_count=merged,
                failed_count=failed,
                completed_at=now if terminal else None,
                updated_at=now,
            )
        )
