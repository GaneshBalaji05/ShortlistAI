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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
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


@app.on_event("startup")
def ensure_interview_storage():
    """Create interview scheduling storage without changing the legacy ATS schema."""
    con = legacy.db()
    con.execute(
        """CREATE TABLE IF NOT EXISTS interviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER,
            round_name TEXT NOT NULL,
            interviewer_name TEXT DEFAULT '',
            interviewer_email TEXT DEFAULT '',
            scheduled_at TEXT NOT NULL,
            timezone TEXT DEFAULT 'Asia/Kolkata',
            duration_minutes INTEGER DEFAULT 45,
            meeting_url TEXT DEFAULT '',
            status TEXT DEFAULT 'Scheduled',
            outcome TEXT DEFAULT 'Pending',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        )"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_interviews_candidate ON interviews(candidate_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_interviews_scheduled ON interviews(scheduled_at)")
    con.commit()
    con.close()


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


DASHBOARD_STAGE_ALIASES = {
    "Sourced": "Applied",
    "Screened": "Contacted",
    "Interview": "Interview Scheduled",
    "Offered": "Selected",
    "Joined": "Hired",
    "Rejected": "Dropped",
}
DASHBOARD_STAGES = {
    "Applied", "Contacted", "Interview Scheduled", "L1", "L2", "Selected", "Hired", "Dropped"
}


def _canonical_stage(stage: str | None) -> str:
    value = str(stage or "Applied").strip()
    return DASHBOARD_STAGE_ALIASES.get(value, value if value in DASHBOARD_STAGES else "Applied")


def _workflow_status(stage: str, details: dict) -> tuple[str, str]:
    """Return L1/L2 status, preferring recruiter-entered metadata with safe fallbacks."""
    l1 = str(details.get("l1_status") or "").strip()
    l2 = str(details.get("l2_status") or "").strip()
    stage = _canonical_stage(stage)

    if not l1:
        if stage == "Interview Scheduled":
            l1 = "Scheduled"
        elif stage in {"L1", "L2", "Selected", "Hired"}:
            l1 = "Cleared"
        elif stage == "Dropped":
            l1 = "Not Applicable"
        else:
            l1 = "Pending Scheduling"

    if not l2:
        if stage in {"L2", "Selected", "Hired"}:
            l2 = "Cleared"
        elif stage == "L1" and l1 == "Cleared":
            l2 = "Pending Scheduling"
        elif stage == "Dropped":
            l2 = "Not Applicable"
        else:
            l2 = "Not Started"
    return l1, l2


def _summary(candidates: list[dict]) -> dict:
    total = len(candidates)
    stages = [_canonical_stage(c.get("stage")) for c in candidates]
    hired = sum(stage == "Hired" for stage in stages)
    dropped = sum(stage == "Dropped" for stage in stages)
    return {
        "profiles_sourced": total,
        "in_pipeline": max(0, total - hired - dropped),
        "l1_cleared": sum(c["l1_status"] == "Cleared" for c in candidates),
        "l2_cleared": sum(c["l2_status"] == "Cleared" for c in candidates),
        "hired": hired,
        "dropped": dropped,
        "yet_to_schedule_l1": sum(
            c["l1_status"] == "Pending Scheduling" and _canonical_stage(c.get("stage")) not in {"Hired", "Dropped"}
            for c in candidates
        ),
        "yet_to_schedule_l2": sum(
            c["l1_status"] == "Cleared"
            and c["l2_status"] == "Pending Scheduling"
            and _canonical_stage(c.get("stage")) not in {"Hired", "Dropped"}
            for c in candidates
        ),
        "ai_distribution": {
            "Strong": sum(c["rating"] == "Strong" for c in candidates),
            "Average": sum(c["rating"] == "Average" for c in candidates),
            "Weak": sum(c["rating"] == "Weak" for c in candidates),
        },
        "stage_distribution": dict(Counter(stages)),
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
            "stage": _canonical_stage(row["stage"]),
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


@app.patch("/api/candidates/{candidate_id}/interview-status")
def update_interview_status(candidate_id: int, payload: dict):
    """Update L1/L2 workflow state without forcing the candidate's ATS stage."""
    allowed = {"Not Started", "Pending Scheduling", "Scheduled", "Cleared", "Rejected", "Not Applicable"}
    l1 = str(payload.get("l1_status") or "").strip()
    l2 = str(payload.get("l2_status") or "").strip()
    if l1 not in allowed or l2 not in allowed:
        raise HTTPException(status_code=400, detail="Invalid L1/L2 status")

    con = legacy.db()
    row = con.execute("SELECT stage,profile_details FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Candidate not found")

    details = _safe_json(row["profile_details"])
    details["l1_status"] = l1
    details["l2_status"] = l2
    if l2 == "Cleared":
        details["interview_level"] = "L2 Cleared"
    elif l1 == "Cleared":
        details["interview_level"] = "L1 Cleared"
    elif l1 in {"Pending Scheduling", "Scheduled"}:
        details["interview_level"] = "L1 Pending"
    else:
        details["interview_level"] = l1

    con.execute(
        "UPDATE candidates SET profile_details=?,updated_at=datetime('now') WHERE id=?",
        (json.dumps(details), candidate_id),
    )
    con.commit()
    con.close()
    return {"candidate_id": candidate_id, "l1_status": l1, "l2_status": l2}


def _interview_select() -> str:
    return """SELECT i.*,c.name AS candidate_name,c.email AS candidate_email,
                     j.title AS job_title
              FROM interviews i
              JOIN candidates c ON c.id=i.candidate_id
              LEFT JOIN jobs j ON j.id=i.job_id"""


def _interview_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "candidate_id": int(row["candidate_id"]),
        "candidate_name": row["candidate_name"],
        "candidate_email": row["candidate_email"] or "",
        "job_id": row["job_id"],
        "job_title": row["job_title"] or "Unassigned",
        "round_name": row["round_name"],
        "interviewer_name": row["interviewer_name"] or "",
        "interviewer_email": row["interviewer_email"] or "",
        "scheduled_at": row["scheduled_at"],
        "timezone": row["timezone"] or "Asia/Kolkata",
        "duration_minutes": int(row["duration_minutes"] or 45),
        "meeting_url": row["meeting_url"] or "",
        "status": row["status"] or "Scheduled",
        "outcome": row["outcome"] or "Pending",
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _sync_candidate_round(con, candidate_id: int, round_name: str, state: str) -> None:
    row = con.execute("SELECT profile_details FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        return
    details = _safe_json(row["profile_details"])
    round_key = str(round_name or "").strip().upper()
    if round_key.startswith("L1"):
        details["l1_status"] = state
        if state == "Cleared" and not details.get("l2_status"):
            details["l2_status"] = "Pending Scheduling"
        details["interview_level"] = "L1 Cleared" if state == "Cleared" else f"L1 {state}"
    elif round_key.startswith("L2"):
        details["l2_status"] = state
        details["interview_level"] = "L2 Cleared" if state == "Cleared" else f"L2 {state}"
    con.execute(
        "UPDATE candidates SET profile_details=?,updated_at=datetime('now') WHERE id=?",
        (json.dumps(details), candidate_id),
    )


@app.get("/api/interviews")
def list_interviews(candidate_id: int | None = None, job_id: int | None = None, status: str = ""):
    con = legacy.db()
    sql = _interview_select() + " WHERE 1=1"
    params: list = []
    if candidate_id is not None:
        sql += " AND i.candidate_id=?"
        params.append(candidate_id)
    if job_id is not None:
        sql += " AND i.job_id=?"
        params.append(job_id)
    if status.strip():
        sql += " AND i.status=?"
        params.append(status.strip())
    sql += " ORDER BY i.scheduled_at ASC,i.id DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [_interview_dict(row) for row in rows]


@app.post("/api/interviews")
def create_interview(payload: dict):
    try:
        candidate_id = int(payload.get("candidate_id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Candidate is required")
    round_name = str(payload.get("round_name") or "").strip()
    scheduled_at = str(payload.get("scheduled_at") or "").strip()
    if not round_name:
        raise HTTPException(status_code=400, detail="Interview round is required")
    if not scheduled_at:
        raise HTTPException(status_code=400, detail="Interview date and time are required")
    try:
        datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interview date/time")

    timezone_name = str(payload.get("timezone") or "Asia/Kolkata").strip()
    try:
        ZoneInfo(timezone_name)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    try:
        duration = int(payload.get("duration_minutes") or 45)
    except Exception:
        duration = 45
    if duration < 15 or duration > 240:
        raise HTTPException(status_code=400, detail="Duration must be between 15 and 240 minutes")

    con = legacy.db()
    candidate = con.execute("SELECT id,job_id FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        con.close()
        raise HTTPException(status_code=404, detail="Candidate not found")
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        """INSERT INTO interviews(
            candidate_id,job_id,round_name,interviewer_name,interviewer_email,
            scheduled_at,timezone,duration_minutes,meeting_url,status,outcome,notes,
            created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            candidate_id,candidate["job_id"],round_name,
            str(payload.get("interviewer_name") or "").strip(),
            str(payload.get("interviewer_email") or "").strip(),
            scheduled_at,timezone_name,duration,
            str(payload.get("meeting_url") or "").strip(),
            "Scheduled","Pending",str(payload.get("notes") or "").strip(),now,now,
        ),
    )
    _sync_candidate_round(con, candidate_id, round_name, "Scheduled")
    con.commit()
    row = con.execute(_interview_select() + " WHERE i.id=?", (cur.lastrowid,)).fetchone()
    con.close()
    return _interview_dict(row)


@app.patch("/api/interviews/{interview_id}")
def update_interview(interview_id: int, payload: dict):
    allowed_status = {"Scheduled", "Completed", "Cancelled"}
    allowed_outcome = {"Pending", "Cleared", "Rejected"}
    con = legacy.db()
    existing = con.execute("SELECT * FROM interviews WHERE id=?", (interview_id,)).fetchone()
    if not existing:
        con.close()
        raise HTTPException(status_code=404, detail="Interview not found")

    fields = {
        "round_name": existing["round_name"],
        "interviewer_name": existing["interviewer_name"],
        "interviewer_email": existing["interviewer_email"],
        "scheduled_at": existing["scheduled_at"],
        "timezone": existing["timezone"],
        "duration_minutes": existing["duration_minutes"],
        "meeting_url": existing["meeting_url"],
        "status": existing["status"],
        "outcome": existing["outcome"],
        "notes": existing["notes"],
    }
    for key in fields:
        if key in payload and payload[key] is not None:
            fields[key] = payload[key]

    fields["status"] = str(fields["status"] or "Scheduled").strip()
    fields["outcome"] = str(fields["outcome"] or "Pending").strip()
    if fields["status"] not in allowed_status:
        con.close()
        raise HTTPException(status_code=400, detail="Invalid interview status")
    if fields["outcome"] not in allowed_outcome:
        con.close()
        raise HTTPException(status_code=400, detail="Invalid interview outcome")
    try:
        datetime.fromisoformat(str(fields["scheduled_at"]).replace("Z", "+00:00"))
        ZoneInfo(str(fields["timezone"] or "Asia/Kolkata"))
        fields["duration_minutes"] = int(fields["duration_minutes"] or 45)
    except Exception:
        con.close()
        raise HTTPException(status_code=400, detail="Invalid schedule details")

    con.execute(
        """UPDATE interviews SET round_name=?,interviewer_name=?,interviewer_email=?,
           scheduled_at=?,timezone=?,duration_minutes=?,meeting_url=?,status=?,outcome=?,notes=?,
           updated_at=? WHERE id=?""",
        (
            str(fields["round_name"] or "").strip(),
            str(fields["interviewer_name"] or "").strip(),
            str(fields["interviewer_email"] or "").strip(),
            str(fields["scheduled_at"]).strip(),str(fields["timezone"]).strip(),
            fields["duration_minutes"],str(fields["meeting_url"] or "").strip(),
            fields["status"],fields["outcome"],str(fields["notes"] or "").strip(),
            datetime.now(timezone.utc).isoformat(),interview_id,
        ),
    )
    if fields["outcome"] in {"Cleared", "Rejected"}:
        _sync_candidate_round(con, int(existing["candidate_id"]), str(fields["round_name"]), fields["outcome"])
    elif fields["status"] == "Scheduled":
        _sync_candidate_round(con, int(existing["candidate_id"]), str(fields["round_name"]), "Scheduled")
    con.commit()
    row = con.execute(_interview_select() + " WHERE i.id=?", (interview_id,)).fetchone()
    con.close()
    return _interview_dict(row)


def _ics_escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


@app.get("/api/interviews/{interview_id}/calendar.ics")
def interview_calendar(interview_id: int):
    con = legacy.db()
    row = con.execute(_interview_select() + " WHERE i.id=?", (interview_id,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Interview not found")
    item = _interview_dict(row)
    try:
        start = datetime.fromisoformat(item["scheduled_at"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(item["timezone"]))
        start_utc = start.astimezone(timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Interview schedule is invalid")
    end_utc = start_utc + timedelta(minutes=item["duration_minutes"])
    description = f"Candidate: {item['candidate_name']}\nRound: {item['round_name']}\nInterviewer: {item['interviewer_name']}"
    if item["meeting_url"]:
        description += f"\nMeeting: {item['meeting_url']}"
    if item["notes"]:
        description += f"\nNotes: {item['notes']}"
    lines = [
        "BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ShortlistAI//Interview//EN","CALSCALE:GREGORIAN",
        "METHOD:PUBLISH","BEGIN:VEVENT",
        f"UID:shortlistai-interview-{item['id']}@shortlistai",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ics_escape(item['round_name'] + ' Interview - ' + item['candidate_name'])}",
        f"DESCRIPTION:{_ics_escape(description)}",
        f"LOCATION:{_ics_escape(item['meeting_url'])}",
        "END:VEVENT","END:VCALENDAR","",
    ]
    return Response(
        content="\r\n".join(lines),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ShortlistAI-Interview-{item["id"]}.ics"'},
    )


@app.get("/", response_class=HTMLResponse)
def login_page():
    return (BASE_DIR / "static" / "login.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def ats_workspace():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/static/theme-v2.css?v=2"/>\n'
        '<link rel="stylesheet" href="/static/dashboard-v2.css?v=1"/>\n'
        '<link rel="stylesheet" href="/static/interviews-v1.css?v=1"/>\n</head>'
    )
    html = html.replace(
        "</body>",
        '<script src="/static/theme-v2.js?v=2"></script>\n'
        '<script src="/static/dashboard-v2.js?v=1"></script>\n'
        '<script src="/static/interviews-v1.js?v=1"></script>\n</body>'
    )
    return html


@app.get("/sw.js")
def root_service_worker():
    return Response((BASE_DIR / "static" / "sw.js").read_text(), media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


# Security is installed synchronously only after all application routes exist, so
# there is no cold-start window where /app or an ATS API can be served publicly.
from auth_runtime import install_auth_routes

if not any(getattr(route, "path", "") == "/api/auth/register" for route in app.routes):
    install_auth_routes(app)
else:
    from tenant_security import install as install_tenant_security
    install_tenant_security(app)
