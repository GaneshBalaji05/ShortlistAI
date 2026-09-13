from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import HTTPException

from shortlistai.db.repositories import WorkspaceRepository
from shortlistai.db.runtime import create_database_engine
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
