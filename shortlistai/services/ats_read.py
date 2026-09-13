from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from shortlistai.db.repositories import WorkspaceRepository
from shortlistai.db.runtime import create_database_engine
from tenant_security import current_user, current_workspace


CANDIDATE_LIST_FIELDS = (
    "id",
    "name",
    "email",
    "phone",
    "experience",
    "skills",
    "source",
    "notice_period",
    "current_ctc",
    "expected_ctc",
    "job_id",
    "stage",
    "ai_score",
    "rating",
    "created_at",
    "updated_at",
    "resume_filename",
    "profile_details",
    "talent_pools",
)

JOB_FIELDS = (
    "id",
    "title",
    "department",
    "location",
    "status",
    "created_at",
)


def _repository() -> WorkspaceRepository:
    return WorkspaceRepository(create_database_engine(), current_workspace())


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        parsed = json.loads(str(value))
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _project(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields}


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    output = _project(row, CANDIDATE_LIST_FIELDS)
    output["profile_details"] = _json_value(output.get("profile_details"), {})
    output["talent_pools"] = _json_value(output.get("talent_pools"), [])
    return output


def authenticated_context() -> dict[str, int]:
    return {
        "user_id": current_user(),
        "workspace_id": current_workspace(),
    }


def list_candidates(*, limit: int, offset: int) -> dict[str, Any]:
    repo = _repository()
    rows = repo.list_rows("candidates", limit=limit, offset=offset)
    return {
        "data": [_candidate_summary(row) for row in rows],
        "meta": {
            "total": repo.count_rows("candidates"),
            "limit": limit,
            "offset": offset,
        },
    }


def get_candidate(candidate_id: int) -> dict[str, Any]:
    row = _repository().get_row("candidates", candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    output = _candidate_summary(row)
    output["resume_text"] = row.get("resume_text") or ""
    output["ai_details"] = _json_value(row.get("ai_details"), {})
    return {"data": output}


def list_jobs(*, limit: int, offset: int) -> dict[str, Any]:
    repo = _repository()
    rows = repo.list_rows("jobs", limit=limit, offset=offset)
    return {
        "data": [_project(row, JOB_FIELDS) for row in rows],
        "meta": {
            "total": repo.count_rows("jobs"),
            "limit": limit,
            "offset": offset,
        },
    }


def get_job(job_id: int) -> dict[str, Any]:
    row = _repository().get_row("jobs", job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    output = _project(row, JOB_FIELDS)
    output["jd"] = row.get("jd") or ""
    return {"data": output}
