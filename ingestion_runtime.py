from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable, Optional

import data_foundation as foundation

MIGRATION_NAME = "resumable_ingestion_v1"
TERMINAL_ITEM_STATUSES = {"Created", "Merged", "Failed", "Skipped"}
SUCCESS_ITEM_STATUSES = {"Created", "Merged", "Skipped"}


def _now() -> str:
    return datetime.utcnow().isoformat()


def ensure_ingestion_schema() -> None:
    """Apply the SQLite ingestion migration transactionally and idempotently."""
    import tenant_security

    tenant_security.ensure_schema()
    con = tenant_security._raw()
    try:
        already = con.execute(
            "SELECT 1 FROM security_migrations WHERE name=?", (MIGRATION_NAME,)
        ).fetchone()
        if already:
            return
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """CREATE TABLE IF NOT EXISTS ingestion_batches(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                batch_key TEXT NOT NULL,
                job_id INTEGER,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                total_count INTEGER NOT NULL,
                processed_count INTEGER NOT NULL DEFAULT 0,
                created_count INTEGER NOT NULL DEFAULT 0,
                merged_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id,batch_key),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS ingestion_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                source_filename TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                extracted_text TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                candidate_id INTEGER,
                error_code TEXT,
                error_message TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                UNIQUE(batch_id,ordinal),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(batch_id) REFERENCES ingestion_batches(id) ON DELETE CASCADE,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_batches_workspace_status ON ingestion_batches(workspace_id,status)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_items_batch_status ON ingestion_items(workspace_id,batch_id,status)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_items_candidate ON ingestion_items(workspace_id,candidate_id)"
        )
        con.execute(
            "INSERT INTO security_migrations(name,applied_at) VALUES(?,?)",
            (MIGRATION_NAME, _now()),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _batch_key(job_id: Optional[int], source: str, hashes: Iterable[str]) -> str:
    payload = {
        "job_id": int(job_id) if job_id is not None else None,
        "source": str(source or "").strip(),
        "content_hashes": list(hashes),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _error(exc: Exception) -> tuple[str, str]:
    code = type(exc).__name__
    status_code = getattr(exc, "status_code", None)
    if status_code:
        code = f"HTTP_{status_code}"
    detail = getattr(exc, "detail", None)
    message = str(detail if detail is not None else exc).strip() or code
    return code[:64], message[:1000]


async def stage_uploaded_profiles(
    con,
    legacy,
    profiles,
    *,
    job_id: Optional[int],
    source: str,
) -> tuple[int, bool]:
    """Persist an idempotent batch and processable extracted text before candidate writes."""
    wid = foundation._workspace_id(con)
    if job_id is not None and not con.execute(
        "SELECT id FROM jobs WHERE id=?", (job_id,)
    ).fetchone():
        raise ValueError("Job not found in this workspace")

    staged: list[dict[str, Any]] = []
    hashes: list[str] = []
    for ordinal, profile in enumerate(profiles, 1):
        filename = profile.filename or f"profile-{ordinal}"
        raw = await profile.read()
        digest = hashlib.sha256(raw).hexdigest()
        hashes.append(digest)
        item = {
            "ordinal": ordinal,
            "filename": filename,
            "content_hash": digest,
            "text": None,
            "status": "Pending",
            "error_code": None,
            "error_message": None,
        }
        try:
            text = legacy.extract_text(filename, raw)
            if len(text.strip()) < 80:
                raise ValueError("Very little readable text was extracted")
            item["text"] = text
        except Exception as exc:
            item["status"] = "Failed"
            item["error_code"], item["error_message"] = _error(exc)
        staged.append(item)

    key = _batch_key(job_id, source, hashes)
    existing = con.execute(
        "SELECT id FROM ingestion_batches WHERE workspace_id=? AND batch_key=?",
        (wid, key),
    ).fetchone()
    if existing:
        return int(existing["id"]), True

    now = _now()
    cur = con.execute(
        """INSERT INTO ingestion_batches(
            workspace_id,batch_key,job_id,source,status,total_count,
            processed_count,created_count,merged_count,skipped_count,failed_count,
            created_at,started_at,completed_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            wid,
            key,
            job_id,
            str(source or "Bulk profile upload").strip() or "Bulk profile upload",
            "Pending",
            len(staged),
            0,
            0,
            0,
            0,
            0,
            now,
            None,
            None,
            now,
        ),
    )
    batch_id = int(cur.lastrowid)
    for item in staged:
        processed_at = now if item["status"] == "Failed" else None
        con.execute(
            """INSERT INTO ingestion_items(
                workspace_id,batch_id,ordinal,source_filename,content_hash,extracted_text,
                status,candidate_id,error_code,error_message,attempts,created_at,processed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                wid,
                batch_id,
                item["ordinal"],
                item["filename"],
                item["content_hash"],
                item["text"],
                item["status"],
                None,
                item["error_code"],
                item["error_message"],
                1 if item["status"] == "Failed" else 0,
                now,
                processed_at,
            ),
        )
    _sync_batch(con, wid, batch_id)
    con.commit()  # durability boundary: all batch/items exist before candidate writes
    return batch_id, False


def _counts(con, wid: int, batch_id: int) -> dict[str, int]:
    counts = {"Pending": 0, "Created": 0, "Merged": 0, "Skipped": 0, "Failed": 0}
    for row in con.execute(
        """SELECT status,COUNT(*) AS n FROM ingestion_items
           WHERE workspace_id=? AND batch_id=? GROUP BY status""",
        (wid, batch_id),
    ).fetchall():
        counts[str(row["status"])] = int(row["n"])
    return counts


def _sync_batch(con, wid: int, batch_id: int) -> dict[str, int]:
    counts = _counts(con, wid, batch_id)
    total = sum(counts.values())
    pending = counts.get("Pending", 0)
    processed = total - pending
    failed = counts.get("Failed", 0)
    if pending:
        status = "Processing" if processed else "Pending"
        completed_at = None
    else:
        status = "CompletedWithErrors" if failed else "Completed"
        completed_at = _now()
    con.execute(
        """UPDATE ingestion_batches SET
            status=?,processed_count=?,created_count=?,merged_count=?,skipped_count=?,failed_count=?,
            completed_at=?,updated_at=?
           WHERE id=? AND workspace_id=?""",
        (
            status,
            processed,
            counts.get("Created", 0),
            counts.get("Merged", 0),
            counts.get("Skipped", 0),
            failed,
            completed_at,
            _now(),
            batch_id,
            wid,
        ),
    )
    counts["total"] = total
    counts["processed"] = processed
    counts["pending"] = pending
    return counts


def _incoming_from_text(legacy, text: str, filename: str, source: str, job_id: Optional[int]) -> dict[str, Any]:
    details = legacy.extract_profile_details(text, filename)
    return {
        "name": legacy.detect_name(text, filename),
        "email": legacy.detect_email(text),
        "phone": legacy.detect_phone(text),
        "experience": legacy.parse_candidate_years(text),
        "skills": ", ".join(legacy.find_skills(text)),
        "resume_text": text,
        "resume_filename": filename,
        "source": source,
        "notice_period": details.get("notice_period") or "",
        "current_ctc": details.get("current_ctc") or "",
        "expected_ctc": details.get("expected_ctc") or "",
        "profile_details": details,
        "talent_pools": legacy.classify_talent_pools(
            text,
            details.get("skills") or "",
            json.dumps(details, ensure_ascii=False),
        ),
        "job_id": job_id,
        "stage": "Sourced",
    }


def process_ingestion_batch(
    con,
    legacy,
    batch_id: int,
    *,
    max_items: Optional[int] = None,
    commit_every: int = 25,
) -> dict[str, int]:
    """Resume pending items; candidate and item terminal state commit atomically per chunk."""
    wid = foundation._workspace_id(con)
    batch = con.execute(
        "SELECT * FROM ingestion_batches WHERE id=? AND workspace_id=?",
        (int(batch_id), wid),
    ).fetchone()
    if not batch:
        raise ValueError("Ingestion batch not found in this workspace")

    pending_sql = (
        "SELECT * FROM ingestion_items WHERE workspace_id=? AND batch_id=? AND status='Pending' ORDER BY ordinal,id"
    )
    params: list[Any] = [wid, int(batch_id)]
    if max_items is not None:
        pending_sql += " LIMIT ?"
        params.append(max(0, int(max_items)))
    items = con.execute(pending_sql, params).fetchall()
    if not items:
        counts = _sync_batch(con, wid, int(batch_id))
        con.commit()
        return counts

    if not batch["started_at"]:
        con.execute(
            "UPDATE ingestion_batches SET status='Processing',started_at=?,updated_at=? WHERE id=? AND workspace_id=?",
            (_now(), _now(), int(batch_id), wid),
        )
        con.commit()

    processed_in_call = 0
    for item in items:
        item_id = int(item["id"])
        savepoint = f"ingestion_item_{item_id}"
        con.execute(f"SAVEPOINT {savepoint}")
        try:
            text = str(item["extracted_text"] or "")
            if len(text.strip()) < 80:
                raise ValueError("Persisted extracted text is missing or too short")
            incoming = _incoming_from_text(
                legacy,
                text,
                str(item["source_filename"]),
                str(batch["source"]),
                batch["job_id"],
            )
            result = foundation._upsert_candidate(con, legacy, incoming, "Resumable bulk profile upload")
            status = "Merged" if result["merged"] else "Created"
            con.execute(
                """UPDATE ingestion_items SET status=?,candidate_id=?,error_code=NULL,error_message=NULL,
                    attempts=attempts+1,processed_at=?,extracted_text=NULL
                   WHERE id=? AND workspace_id=? AND batch_id=?""",
                (status, int(result["id"]), _now(), item_id, wid, int(batch_id)),
            )
            con.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            con.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            con.execute(f"RELEASE SAVEPOINT {savepoint}")
            code, message = _error(exc)
            con.execute(
                """UPDATE ingestion_items SET status='Failed',candidate_id=NULL,error_code=?,error_message=?,
                    attempts=attempts+1,processed_at=?
                   WHERE id=? AND workspace_id=? AND batch_id=?""",
                (code, message, _now(), item_id, wid, int(batch_id)),
            )
        processed_in_call += 1
        if processed_in_call % max(1, int(commit_every)) == 0:
            _sync_batch(con, wid, int(batch_id))
            con.commit()

    counts = _sync_batch(con, wid, int(batch_id))
    con.commit()
    return counts


def batch_response(
    con,
    batch_id: int,
    *,
    before_counts: Optional[dict[str, int]] = None,
    resumed: bool = False,
) -> dict[str, Any]:
    wid = foundation._workspace_id(con)
    batch = con.execute(
        "SELECT * FROM ingestion_batches WHERE id=? AND workspace_id=?",
        (int(batch_id), wid),
    ).fetchone()
    if not batch:
        raise ValueError("Ingestion batch not found in this workspace")
    current = _counts(con, wid, int(batch_id))
    before = before_counts or {key: 0 for key in current}

    prior_success = sum(before.get(key, 0) for key in SUCCESS_ITEM_STATUSES)
    created_delta = max(0, current.get("Created", 0) - before.get("Created", 0))
    merged_delta = max(0, current.get("Merged", 0) - before.get("Merged", 0))
    failed = current.get("Failed", 0)
    pending = current.get("Pending", 0)
    processed = int(batch["total_count"]) - pending
    errors = [
        {"file": str(row["source_filename"]), "error": str(row["error_message"] or row["error_code"] or "Failed")}
        for row in con.execute(
            """SELECT source_filename,error_code,error_message FROM ingestion_items
               WHERE workspace_id=? AND batch_id=? AND status='Failed' ORDER BY ordinal LIMIT 50""",
            (wid, int(batch_id)),
        ).fetchall()
    ]
    total_candidates = int(con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
    return {
        "received": int(batch["total_count"]),
        "created": created_delta,
        "merged": merged_delta,
        "skipped": prior_success,
        "failed": failed,
        "processed": processed,
        "pending": pending,
        "total_candidates": total_candidates,
        "errors": errors,
        "error_count": failed,
        "batch_id": int(batch_id),
        "batch_status": str(batch["status"]),
        "resumed": bool(resumed),
    }


def current_counts(con, batch_id: int) -> dict[str, int]:
    wid = foundation._workspace_id(con)
    return _counts(con, wid, int(batch_id))
