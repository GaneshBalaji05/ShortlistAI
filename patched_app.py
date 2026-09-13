from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

import main
from boolean_search import BooleanSearchError, matches_boolean


_original_list_candidates = main.list_candidates

main.app.router.routes = [
    route
    for route in main.app.router.routes
    if not (
        getattr(route, "path", None) == "/api/candidates"
        and "GET" in (getattr(route, "methods", set()) or set())
    )
]


@main.app.get("/api/candidates")
def list_candidates(
    job_id: Optional[int] = None,
    stage: Optional[str] = None,
    q: Optional[str] = None,
    talent_pool: Optional[str] = None,
    min_experience: Optional[float] = None,
    max_experience: Optional[float] = None,
    location: Optional[str] = None,
    notice_period: Optional[str] = None,
):
    rows = _original_list_candidates(
        job_id=job_id,
        stage=stage,
        q=None,
        talent_pool=talent_pool,
        min_experience=min_experience,
        max_experience=max_experience,
        location=location,
        notice_period=notice_period,
    )
    if not q or not q.strip():
        return rows
    try:
        return [row for row in rows if matches_boolean(q, row)]
    except BooleanSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


app = main.app
