"""ShortlistAI runtime entrypoint.

Render currently starts the service with ``uvicorn main:app``. This package intentionally
shadows the legacy ``main.py`` module, loads that application unchanged, and then adds the
new branded login/workspace routing around it. This lets the UI evolve without disturbing
the ATS API implementation.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

from fastapi.responses import HTMLResponse
from demo_database_seed import seed_demo_database

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_MAIN = PROJECT_ROOT / "main.py"

spec = importlib.util.spec_from_file_location("shortlistai_legacy_main", LEGACY_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load ShortlistAI application")
legacy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = legacy
spec.loader.exec_module(legacy)

app = legacy.app
BASE_DIR = legacy.BASE_DIR


def __getattr__(name: str):
    """Keep imports from the old single-file module working while the UI entrypoint evolves."""
    return getattr(legacy, name)


# Remove the legacy root page while preserving all APIs, static files and startup hooks.
app.router.routes = [
    route for route in app.router.routes
    if not (getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", set()) or set()))
]


@app.on_event("startup")
def seed_product_demo_data():
    """Populate the development build with idempotent fictional ATS data."""
    seed_demo_database(legacy.DB_PATH)


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _workflow_status(stage: str, details: dict) -> tuple[str, str]:
    """Return L1/L2 status, preferring recruiter-entered metadata with safe fallbacks."""
    l1 = str(details.get("l1_status") or "").strip()
    l2 = str(details.get("l2_status") or "").strip()
    stage = stage or "Sourced"

    if not l1:
        if stage in {"Interview", "Offered", "Joined"}:
            l1 = "Cleared"
        elif stage == "Rejected":
            l1 = "Not Applicable"
        else:
            l1 = "Pending Scheduling"

    if not l2:
        if stage in {"Offered", "Joined"}:
            l2 = "Cleared"
        elif stage == "Interview" and l1 == "Cleared":
            l2 = "Pending Scheduling"
        elif stage == "Rejected":
            l2 = "Not Applicable"
        else:
            l2 = "Not Started"
    return l1, l2


def _summary(candidates: list[dict]) -> dict:
    total = len(candidates)
    hired = sum(c["stage"] == "Joined" for c in candidates)
    dropped = sum(c["stage"] == "Rejected" for c in candidates)
    return {
        "profiles_sourced": total,
        "in_pipeline": max(0, total - hired - dropped),
        "l1_cleared": sum(c["l1_status"] == "Cleared" for c in candidates),
        "l2_cleared": sum(c["l2_status"] == "Cleared" for c in candidates),
        "hired": hired,
        "dropped": dropped,
        "yet_to_schedule_l1": sum(c["l1_status"] == "Pending Scheduling" and c["stage"] not in {"Joined", "Rejected"} for c in candidates),
        "yet_to_schedule_l2": sum(c["l1_status"] == "Cleared" and c["l2_status"] == "Pending Scheduling" and c["stage"] not in {"Joined", "Rejected"} for c in candidates),
        "ai_distribution": {
            "Strong": sum(c["rating"] == "Strong" for c in candidates),
            "Average": sum(c["rating"] == "Average" for c in candidates),
            "Weak": sum(c["rating"] == "Weak" for c in candidates),
        },
        "stage_distribution": dict(Counter(c["stage"] for c in candidates)),
        "source_distribution": dict(Counter(c["source"] or "Unknown" for c in candidates)),
    }


@app.get("/api/dashboard-v2")
def dashboard_v2():
    """Recruiter dashboard analytics with job-level drill-down data."""
    con = legacy.db()
    job_rows = con.execute(
        "SELECT id,title,department,location,status,created_at FROM jobs ORDER BY id DESC"
    ).fetchall()
    candidate_rows = con.execute(
        """SELECT c.id,c.name,c.email,c.job_id,c.stage,c.ai_score,c.rating,c.source,
                  c.profile_details,c.created_at,c.updated_at,j.title AS job_title
           FROM candidates c
           LEFT JOIN jobs j ON j.id=c.job_id
           ORDER BY c.updated_at DESC,c.id DESC"""
    ).fetchall()
    con.close()

    candidates: list[dict] = []
    for row in candidate_rows:
        details = _safe_json(row["profile_details"])
        l1, l2 = _workflow_status(row["stage"], details)
        candidates.append({
            "id": int(row["id"]),
            "name": row["name"],
            "email": row["email"] or "",
            "job_id": row["job_id"],
            "job_title": row["job_title"] or "Unassigned",
            "stage": row["stage"] or "Sourced",
            "ai_score": row["ai_score"],
            "rating": row["rating"] or "",
            "source": row["source"] or "Unknown",
            "l1_status": l1,
            "l2_status": l2,
            "updated_at": row["updated_at"] or row["created_at"] or "",
        })

    jobs = []
    for row in job_rows:
        scoped = [c for c in candidates if c["job_id"] == row["id"]]
        jobs.append({
            "id": int(row["id"]),
            "title": row["title"],
            "department": row["department"] or "",
            "location": row["location"] or "",
            "status": row["status"] or "Open",
            "metrics": _summary(scoped),
        })

    recent = [
        {
            "candidate_id": c["id"],
            "candidate": c["name"],
            "job_title": c["job_title"],
            "stage": c["stage"],
            "rating": c["rating"],
            "updated_at": c["updated_at"],
        }
        for c in candidates[:8]
    ]

    return {
        "summary": _summary(candidates),
        "jobs": jobs,
        "candidates": candidates,
        "recent_activity": recent,
    }


@app.get("/", response_class=HTMLResponse)
def login_page():
    return (BASE_DIR / "static" / "login.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def ats_workspace():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/static/theme-v2.css?v=2"/>\n'
        '<link rel="stylesheet" href="/static/dashboard-v2.css?v=1"/>\n</head>'
    )
    html = html.replace(
        "</body>",
        '<script src="/static/theme-v2.js?v=2"></script>\n'
        '<script src="/static/dashboard-v2.js?v=1"></script>\n</body>'
    )
    return html
