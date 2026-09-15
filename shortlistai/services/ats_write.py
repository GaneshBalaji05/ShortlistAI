from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import HTTPException

from final_review import PIPELINE_STAGES, STAGE_ALIASES
from shortlistai.db.candidate_repository import (
    CandidateIdentityConflict,
    CandidatePersistenceRepository,
    CandidateReferenceError,
)
from shortlistai.db.repositories import WorkspaceRepository
from shortlistai.db.runtime import create_database_engine
from shortlistai_talent import classify_talent_pools
from tenant_security import current_workspace


JOB_WRITE_FIELDS = ("title", "department", "location", "jd", "status")
JOB_RESPONSE_FIELDS = (
    "id",
    "title",
    "department",
    "location",
    "jd",
    "status",
    "created_at",
)


def _repository() -> WorkspaceRepository:
    return WorkspaceRepository(create_database_engine(), current_workspace())


def _candidate_repository() -> CandidatePersistenceRepository:
    workspace_id = current_workspace()
    return CandidatePersistenceRepository(create_database_engine(), workspace_id)


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_job_values(values: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
    supplied = dict(values)
    payload: dict[str, Any] = {}

    for field in JOB_WRITE_FIELDS:
        if field not in supplied:
            continue
        if field in {"department", "location"}:
            payload[field] = _clean_optional(supplied[field])
        else:
            payload[field] = str(supplied[field]).strip() if supplied[field] is not None else ""

    if creating:
        payload.setdefault("status", "Open")

    for required in ("title", "jd"):
        if creating or required in payload:
            if not payload.get(required):
                raise HTTPException(status_code=422, detail=f"{required} cannot be empty")

    if "status" in payload and not payload["status"]:
        raise HTTPException(status_code=422, detail="status cannot be empty")

    if not creating and not payload:
        raise HTTPException(status_code=400, detail="Provide at least one job field to update")

    return payload


def _job_response(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in JOB_RESPONSE_FIELDS}


def create_job(values: Mapping[str, Any]) -> dict[str, Any]:
    payload = _normalize_job_values(values, creating=True)
    payload["created_at"] = datetime.now(timezone.utc).isoformat()

    repo = _repository()
    job_id = repo.create_row("jobs", payload)
    row = repo.get_row("jobs", job_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Job was created but could not be read back")
    return {"data": _job_response(row)}


def update_job(job_id: int, values: Mapping[str, Any]) -> dict[str, Any]:
    repo = _repository()
    if repo.get_row("jobs", job_id) is None:
        # Deliberately use 404 for both missing and other-workspace records so callers cannot
        # enumerate tenant data.
        raise HTTPException(status_code=404, detail="Job not found")

    payload = _normalize_job_values(values, creating=False)
    updated = repo.update_row("jobs", job_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")

    row = repo.get_row("jobs", job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"data": _job_response(row)}


def create_candidate(values: Mapping[str, Any]) -> dict[str, Any]:
    """Create or identity-merge one candidate inside the authenticated workspace.

    This is the first candidate write slice on the canonical API. The service injects the
    authenticated workspace rather than accepting tenant identity from the request body,
    then delegates all duplicate/identity/job validation and the atomic write to the
    SQLAlchemy candidate repository.
    """

    workspace_id = current_workspace()
    payload = dict(values)
    payload["workspace_id"] = workspace_id

    raw_stage = str(payload.get("stage") or "Sourced").strip()
    if raw_stage not in PIPELINE_STAGES and raw_stage not in STAGE_ALIASES:
        # Preserve the legacy create-route contract: unknown stages are rejected rather than
        # silently canonicalized to Applied.
        raise HTTPException(status_code=400, detail="Invalid stage")

    if payload.get("talent_pools") is None:
        payload["talent_pools"] = classify_talent_pools(
            str(payload.get("resume_text") or ""),
            str(payload.get("skills") or ""),
            json.dumps(payload.get("profile_details") or {}, ensure_ascii=False),
        )

    try:
        result = _candidate_repository().upsert(payload, reason="API v1 candidate create")
    except CandidateIdentityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CandidateReferenceError as exc:
        # Missing and foreign-workspace job references intentionally share one 404 contract.
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "data": {
            "id": int(result["id"]),
            "merged": bool(result["merged"]),
            "changed": list(result.get("changed") or []),
            "talent_pools": list(result.get("talent_pools") or []),
        }
    }
