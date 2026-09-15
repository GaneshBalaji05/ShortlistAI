from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from shortlistai.db.runtime import create_database_engine
from shortlistai.services.ingestion import (
    MAX_BATCH_ITEMS,
    MAX_CHUNK_ITEMS,
    IngestionConflict,
    IngestionNotFound,
    IngestionStore,
)
from tenant_security import current_user, current_workspace


router = APIRouter(prefix="/ingestion", tags=["Resumable ingestion"])


class IngestionManifestItem(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_filename: str = Field(min_length=1, max_length=500)


class IngestionBatchCreate(BaseModel):
    job_id: int | None = None
    source: str = Field(default="Bulk profile upload", min_length=1, max_length=200)
    items: list[IngestionManifestItem]


def _store() -> IngestionStore:
    return IngestionStore(create_database_engine(), current_workspace())


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IngestionNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, IngestionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Ingestion operation failed")


def _legacy():
    import main

    return getattr(main, "legacy", main)


def _candidate_payload(legacy, text: str, filename: str, *, job_id: int | None, source: str) -> dict[str, Any]:
    details = legacy.extract_profile_details(text, filename)
    skills = ", ".join(legacy.find_skills(text))
    return {
        "name": legacy.detect_name(text, filename),
        "email": legacy.detect_email(text),
        "phone": legacy.detect_phone(text),
        "experience": legacy.parse_candidate_years(text),
        "skills": skills,
        "resume_text": text,
        "resume_filename": filename,
        "source": source,
        "notice_period": details.get("notice_period") or "",
        "current_ctc": details.get("current_ctc") or "",
        "expected_ctc": details.get("expected_ctc") or "",
        "profile_details": details,
        "talent_pools": legacy.classify_talent_pools(
            text,
            skills,
            json.dumps(details, ensure_ascii=False),
        ),
        "job_id": job_id,
        "stage": "Applied",
    }


def _save_candidate(legacy, incoming: dict[str, Any]) -> dict[str, Any]:
    # Reuse the currently hardened duplicate/identity merge boundary. The durable batch
    # state lives in the new API/service layer; candidate persistence remains one item per
    # transaction so a process restart cannot roll back an already successful profile.
    import data_foundation

    con = legacy.db()
    try:
        result = data_foundation._upsert_candidate(
            con,
            legacy,
            incoming,
            "Resumable profile ingestion",
        )
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@router.get("/capabilities")
def ingestion_capabilities():
    return {
        "data": {
            "max_batch_items": MAX_BATCH_ITEMS,
            "max_chunk_items": MAX_CHUNK_ITEMS,
            "manifest_persisted_before_processing": True,
            "idempotency_key_required": True,
            "content_hash_verified": True,
            "raw_file_bytes_persisted": False,
            "resume_model": "resubmit pending, processing, or failed items with the same idempotency key",
        }
    }


@router.post("/batches", status_code=201)
def create_ingestion_batch(payload: IngestionBatchCreate):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Add at least one item to the ingestion batch")
    if len(payload.items) > MAX_BATCH_ITEMS:
        raise HTTPException(status_code=400, detail=f"Ingestion batch limit is {MAX_BATCH_ITEMS} items")
    try:
        data = _store().create_batch(
            created_by=current_user(),
            job_id=payload.job_id,
            source=payload.source,
            items=[item.model_dump() for item in payload.items],
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"data": data}


@router.get("/batches/{batch_id}")
def get_ingestion_batch(batch_id: int):
    try:
        data = _store().get_batch(batch_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"data": data}


@router.post("/batches/{batch_id}/profiles")
async def upload_ingestion_chunk(
    batch_id: int,
    profiles: list[UploadFile] = File(...),
    item_keys: str = Form(...),
):
    if not profiles:
        raise HTTPException(status_code=400, detail="Upload at least one profile")
    if len(profiles) > MAX_CHUNK_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {MAX_CHUNK_ITEMS} profiles per resumable chunk",
        )
    try:
        keys = json.loads(item_keys)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="item_keys must be a JSON array") from exc
    if not isinstance(keys, list) or len(keys) != len(profiles):
        raise HTTPException(status_code=400, detail="item_keys must contain one key for every uploaded profile")
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        raise HTTPException(status_code=400, detail="Every uploaded profile requires a non-empty item key")

    store = _store()
    try:
        batch = store.get_batch(batch_id)
    except Exception as exc:
        raise _http_error(exc) from exc

    legacy = _legacy()
    outcomes: list[dict[str, Any]] = []
    for key, profile in zip(keys, profiles):
        key = key.strip()
        filename = profile.filename or batch.get("source_filename") or key
        raw = await profile.read()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            claim = store.claim_item(
                batch_id=batch_id,
                idempotency_key=key,
                source_filename=filename,
                content_hash=digest,
            )
            if claim.get("already_done"):
                outcomes.append(
                    {
                        "idempotency_key": key,
                        "status": claim.get("status"),
                        "candidate_id": claim.get("candidate_id"),
                        "idempotent_replay": True,
                    }
                )
                continue

            text = legacy.extract_text(filename, raw)
            if len(text.strip()) < 80:
                raise ValueError("Very little readable text was extracted")
            incoming = _candidate_payload(
                legacy,
                text,
                filename,
                job_id=batch.get("job_id"),
                source=str(batch.get("source") or "Bulk profile upload"),
            )
            saved = _save_candidate(legacy, incoming)
            store.complete_item(
                batch_id=batch_id,
                idempotency_key=key,
                candidate_id=int(saved["id"]),
                merged=bool(saved.get("merged")),
            )
            outcomes.append(
                {
                    "idempotency_key": key,
                    "status": "merged" if saved.get("merged") else "created",
                    "candidate_id": int(saved["id"]),
                    "idempotent_replay": False,
                }
            )
        except (IngestionNotFound, IngestionConflict) as exc:
            raise _http_error(exc) from exc
        except Exception as exc:
            try:
                store.fail_item(
                    batch_id=batch_id,
                    idempotency_key=key,
                    error_code="profile_processing_failed",
                    error_message=str(exc),
                )
            except Exception:
                pass
            outcomes.append(
                {
                    "idempotency_key": key,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return {
        "data": {
            "batch": store.get_batch(batch_id),
            "items": outcomes,
        }
    }
