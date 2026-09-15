from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from shortlistai.api.ingestion import router as ingestion_router
from shortlistai.services.ats_read import (
    authenticated_context,
    get_candidate,
    get_job,
    list_candidates,
    list_jobs,
)
from shortlistai.services.ats_write import create_job, update_job

router = APIRouter(prefix="/api/v1", tags=["API v1"])
router.include_router(ingestion_router)


class JobCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    jd: str = Field(min_length=10, max_length=100_000)
    status: str = Field(default="Open", min_length=1, max_length=40)


class JobUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    jd: str | None = Field(default=None, min_length=10, max_length=100_000)
    status: str | None = Field(default=None, min_length=1, max_length=40)


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


@router.post("/jobs", status_code=201)
def api_create_job(payload: JobCreateIn):
    return create_job(payload.model_dump())


@router.get("/jobs/{job_id}")
def api_job(job_id: int):
    return get_job(job_id)


@router.patch("/jobs/{job_id}")
def api_update_job(job_id: int, payload: JobUpdateIn):
    return update_job(job_id, payload.model_dump(exclude_unset=True))


def resolved_route_paths(routes) -> set[str]:
    """Return final route paths across old and new FastAPI router representations.

    FastAPI 0.137+ preserves included routers as a route tree instead of flattening every
    APIRoute into app.routes. Use iter_route_contexts when available and retain a fallback
    for older supported FastAPI releases.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return {getattr(route, "path", "") for route in routes if getattr(route, "path", "")}

    return {
        context.path
        for context in iter_route_contexts(routes)
        if getattr(context, "path", "")
    }


def install_api_v1(app) -> None:
    expected_paths = resolved_route_paths(router.routes)
    if not expected_paths:
        raise RuntimeError("API v1 router contains no routes")

    existing_paths = resolved_route_paths(app.routes)
    if expected_paths <= existing_paths:
        app.state.shortlistai_api_v1 = True
        return

    # FastAPI 0.137+ keeps included routers as nested route objects. The router API itself
    # remains supported; verification must resolve the route tree instead of assuming that
    # app.routes is flat.
    app.include_router(router)

    installed_paths = resolved_route_paths(app.routes)
    missing = expected_paths - installed_paths
    if missing:
        raise RuntimeError(f"API v1 route installation incomplete: {sorted(missing)}")
    app.state.shortlistai_api_v1 = True
