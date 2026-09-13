from __future__ import annotations

from fastapi import APIRouter, Query

from shortlistai.services.ats_read import (
    authenticated_context,
    get_candidate,
    get_job,
    list_candidates,
    list_jobs,
)

router = APIRouter(prefix="/api/v1", tags=["API v1"])


@router.get("/health")
def api_health():
    context = authenticated_context()
    return {
        "data": {
            "status": "ok",
            "api_version": "v1",
            **context,
        }
    }


@router.get("/me")
def api_me():
    return {"data": authenticated_context()}


@router.get("/candidates")
def api_candidates(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return list_candidates(limit=limit, offset=offset)


@router.get("/candidates/{candidate_id}")
def api_candidate(candidate_id: int):
    return get_candidate(candidate_id)


@router.get("/jobs")
def api_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return list_jobs(limit=limit, offset=offset)


@router.get("/jobs/{job_id}")
def api_job(job_id: int):
    return get_job(job_id)


def install_api_v1(app) -> None:
    expected_paths = {getattr(route, "path", "") for route in router.routes}
    if not expected_paths:
        raise RuntimeError("API v1 router contains no routes")

    existing_paths = {getattr(route, "path", "") for route in app.routes}
    if expected_paths <= existing_paths:
        app.state.shortlistai_api_v1 = True
        return

    # Do not trust only an app-state flag: import/re-entry during the legacy compatibility
    # phase can leave state behind. The route table itself is the source of truth.
    app.include_router(router)

    installed_paths = {getattr(route, "path", "") for route in app.routes}
    missing = expected_paths - installed_paths
    if missing:
        raise RuntimeError(f"API v1 route installation incomplete: {sorted(missing)}")
    app.state.shortlistai_api_v1 = True
