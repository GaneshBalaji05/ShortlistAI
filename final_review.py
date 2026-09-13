from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import File, Form, HTTPException, UploadFile
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from boolean_search import matches_boolean

PIPELINE_STAGES = [
    "Applied",
    "Contacted",
    "Interview Scheduled",
    "L1",
    "L2",
    "Selected",
    "Hired",
    "Dropped",
]

STAGE_ALIASES = {
    "Sourced": "Applied",
    "Screened": "Contacted",
    "Interview": "Interview Scheduled",
    "Offered": "Selected",
    "Joined": "Hired",
    "Rejected": "Dropped",
}

STAGE_RANK = {name: index for index, name in enumerate(PIPELINE_STAGES)}
BULK_UI_LIMIT = 800
BULK_REQUEST_LIMIT = 50
SCORING_VERSION = "stable-v2"
SCORING_WEIGHTS = {
    "semantic_fit": 20,
    "skill_coverage": 45,
    "experience_fit": 20,
    "recent_evidence": 15,
}


def canonical_stage(value: str | None) -> str:
    value = str(value or "Applied").strip()
    return STAGE_ALIASES.get(value, value if value in PIPELINE_STAGES else "Applied")


def _safe_json(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _normalized_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if digits else ""


def _linkedin(profile: dict) -> str:
    return str(profile.get("linkedin_id") or profile.get("profile_link") or "").strip().lower().rstrip("/")


def _merge_profile(existing: dict, incoming: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _merge_skills(*values: str) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in re.split(r"[,;|\n]+", value or ""):
            item = re.sub(r"\s+", " ", item).strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                out.append(item)
    return ", ".join(out)


def effective_pipeline_stage(candidate: dict, scheduled_rounds: Optional[Iterable[str]] = None) -> str:
    details = candidate.get("profile_details") or {}
    stored = canonical_stage(candidate.get("stage"))
    if stored in {"Hired", "Dropped", "Selected"}:
        return stored

    l1 = str(details.get("l1_status") or "").strip()
    l2 = str(details.get("l2_status") or "").strip()
    if l2 == "Cleared":
        return "L2"
    if l1 == "Cleared":
        return "L1"
    if l1 == "Scheduled" or l2 == "Scheduled":
        return "Interview Scheduled"
    if scheduled_rounds:
        return "Interview Scheduled"
    return stored


def _stable_semantic_scores_factory(legacy):
    def stable_semantic_scores(jd: str, resumes: List[str]) -> List[float]:
        jd_norm = legacy.normalize(jd)
        scores: list[float] = []
        for resume in resumes:
            try:
                mat = TfidfVectorizer(
                    stop_words="english",
                    ngram_range=(1, 2),
                    max_features=12000,
                ).fit_transform([jd_norm, legacy.normalize(resume)])
                scores.append(float(cosine_similarity(mat[0:1], mat[1:2])[0][0]))
            except Exception:
                scores.append(0.0)
        return scores
    return stable_semantic_scores


def _score_wrapper_factory(legacy, original_score_resume):
    def score_resume(jd: str, resume: str, sim: float) -> Dict[str, Any]:
        result = original_score_resume(jd, resume, sim)
        contributions = {
            key: round(float(result.get(key, 0.0)) * weight / 100.0, 2)
            for key, weight in SCORING_WEIGHTS.items()
        }
        total = round(sum(contributions.values()), 1)
        result["score"] = total
        result["rating"] = legacy.rating(total)
        result["methodology_version"] = SCORING_VERSION
        result["weights"] = dict(SCORING_WEIGHTS)
        result["weighted_components"] = contributions
        result["calculation"] = " + ".join(
            f"{SCORING_WEIGHTS[key]}% × {result.get(key, 0)}%"
            for key in SCORING_WEIGHTS
        ) + f" = {total}"
        result.setdefault("evidence", []).append(
            "Stable scoring: semantic similarity is calculated per candidate against the JD, so the score does not change when other resumes are added or removed from the batch."
        )
        return result
    return score_resume


def _find_duplicate(legacy, con: sqlite3.Connection, email: str, phone: str, profile: dict):
    row = legacy._candidate_duplicate(con, email, phone)
    if row:
        return row
    wanted_linkedin = _linkedin(profile)
    if not wanted_linkedin:
        return None
    for candidate in con.execute("SELECT id,name,email,phone,profile_details FROM candidates"):
        if _linkedin(_safe_json(candidate["profile_details"])) == wanted_linkedin:
            return candidate
    return None


def _later_stage(existing: str | None, incoming: str | None, same_job: bool) -> str:
    old = canonical_stage(existing)
    new = canonical_stage(incoming)
    if not same_job:
        return new
    if old in {"Hired", "Dropped"}:
        return old
    return old if STAGE_RANK.get(old, 0) >= STAGE_RANK.get(new, 0) else new


def _upsert_candidate(legacy, con: sqlite3.Connection, incoming: dict, ai_result: dict | None = None) -> tuple[int, bool]:
    profile = incoming.get("profile_details") or {}
    if not isinstance(profile, dict):
        profile = _safe_json(profile)
    email = str(incoming.get("email") or "").strip()
    phone = str(incoming.get("phone") or "").strip()
    duplicate = _find_duplicate(legacy, con, email, phone, profile)
    now = datetime.utcnow().isoformat()

    if duplicate:
        row = con.execute("SELECT * FROM candidates WHERE id=?", (int(duplicate["id"]),)).fetchone()
        current = dict(row)
        current_profile = _safe_json(current.get("profile_details"))
        merged_profile = _merge_profile(current_profile, profile)
        if incoming.get("source") and incoming.get("source") != current.get("source"):
            history = list(merged_profile.get("source_history") or [])
            for value in (current.get("source"), incoming.get("source")):
                if value and value not in history:
                    history.append(value)
            merged_profile["source_history"] = history

        incoming_job = incoming.get("job_id")
        same_job = incoming_job in (None, current.get("job_id"))
        job_id = incoming_job if incoming_job is not None else current.get("job_id")
        stage = _later_stage(current.get("stage"), incoming.get("stage"), same_job)
        resume_text = str(incoming.get("resume_text") or current.get("resume_text") or "")
        resume_filename = str(incoming.get("resume_filename") or current.get("resume_filename") or "")
        skills = _merge_skills(str(current.get("skills") or ""), str(incoming.get("skills") or ""))
        pools = legacy.classify_talent_pools(resume_text, skills, json.dumps(merged_profile, ensure_ascii=False))

        values = {
            "name": incoming.get("name") or current.get("name") or "Candidate",
            "email": email or current.get("email") or "",
            "phone": phone or current.get("phone") or "",
            "experience": incoming.get("experience") if incoming.get("experience") is not None else current.get("experience"),
            "skills": skills,
            "resume_text": resume_text,
            "resume_filename": resume_filename,
            "source": current.get("source") or incoming.get("source") or "",
            "notice_period": incoming.get("notice_period") or current.get("notice_period") or "",
            "current_ctc": incoming.get("current_ctc") or current.get("current_ctc") or "",
            "expected_ctc": incoming.get("expected_ctc") or current.get("expected_ctc") or "",
            "profile_details": json.dumps(merged_profile, ensure_ascii=False),
            "talent_pools": legacy.encode_talent_pools(pools),
            "job_id": job_id,
            "stage": stage,
            "updated_at": now,
        }
        if ai_result is not None:
            values.update({
                "ai_score": ai_result.get("score"),
                "rating": ai_result.get("rating"),
                "ai_details": json.dumps(ai_result, ensure_ascii=False),
            })
        set_sql = ",".join(f"{key}=?" for key in values)
        con.execute(
            f"UPDATE candidates SET {set_sql} WHERE id=?",
            list(values.values()) + [int(duplicate["id"])],
        )
        legacy._log_activity(
            con,
            int(duplicate["id"]),
            "Duplicate merged",
            f"Merged incoming profile using strong identity match ({'email' if email else 'phone/LinkedIn'}).",
        )
        return int(duplicate["id"]), True

    name = str(incoming.get("name") or "Candidate").strip() or "Candidate"
    skills = str(incoming.get("skills") or "")
    resume_text = str(incoming.get("resume_text") or "")
    pools = incoming.get("talent_pools")
    if pools is None:
        pools = legacy.classify_talent_pools(resume_text, skills, json.dumps(profile, ensure_ascii=False))
    ai_score = ai_result.get("score") if ai_result else incoming.get("ai_score")
    rating = ai_result.get("rating") if ai_result else incoming.get("rating")
    ai_details = json.dumps(ai_result, ensure_ascii=False) if ai_result else incoming.get("ai_details")
    if isinstance(ai_details, dict):
        ai_details = json.dumps(ai_details, ensure_ascii=False)
    cur = con.execute(
        """INSERT INTO candidates(
            name,email,phone,experience,skills,resume_text,resume_filename,source,notice_period,current_ctc,
            expected_ctc,profile_details,talent_pools,job_id,stage,ai_score,rating,ai_details,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,email,phone,incoming.get("experience"),skills,resume_text,
            str(incoming.get("resume_filename") or ""),str(incoming.get("source") or ""),
            str(incoming.get("notice_period") or ""),str(incoming.get("current_ctc") or ""),
            str(incoming.get("expected_ctc") or ""),json.dumps(profile, ensure_ascii=False),
            legacy.encode_talent_pools(pools),incoming.get("job_id"),canonical_stage(incoming.get("stage")),
            ai_score,rating,ai_details,now,now,
        ),
    )
    legacy._log_activity(con, int(cur.lastrowid), "Candidate created", f"Stage: {canonical_stage(incoming.get('stage'))}")
    return int(cur.lastrowid), False


def _remove_route(app, path: str, method: str) -> None:
    app.router.routes = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


def _install_routes(legacy) -> None:
    app = legacy.app
    legacy.STAGES = list(PIPELINE_STAGES)
    original_score_resume = legacy.score_resume
    legacy.semantic_scores = _stable_semantic_scores_factory(legacy)
    legacy.score_resume = _score_wrapper_factory(legacy, original_score_resume)

    _remove_route(app, "/api/stats", "GET")
    _remove_route(app, "/api/candidates", "POST")
    _remove_route(app, "/analyze", "POST")

    @app.get("/api/stats")
    def final_stats():
        con = legacy.db()
        jobs = con.execute("SELECT COUNT(*) FROM jobs WHERE status='Open'").fetchone()[0]
        rows = con.execute("SELECT stage,profile_details FROM candidates").fetchall()
        candidate_total = len(rows)
        effective = [
            effective_pipeline_stage({"stage": row["stage"], "profile_details": _safe_json(row["profile_details"])})
            for row in rows
        ]
        scheduled_interviews = 0
        try:
            scheduled_interviews = con.execute("SELECT COUNT(*) FROM interviews WHERE status='Scheduled'").fetchone()[0]
        except sqlite3.OperationalError:
            pass
        con.close()
        return {
            "jobs": jobs,
            "candidates": candidate_total,
            "candidate_total": candidate_total,
            "interviews": max(scheduled_interviews, sum(stage == "Interview Scheduled" for stage in effective)),
            "offers": sum(stage == "Selected" for stage in effective),
            "joined": sum(stage == "Hired" for stage in effective),
        }

    @app.post("/api/candidates")
    def final_create_candidate(payload: dict):
        if not str(payload.get("name") or "").strip():
            raise HTTPException(status_code=400, detail="Candidate name is required")
        stage = canonical_stage(payload.get("stage"))
        if stage not in PIPELINE_STAGES:
            raise HTTPException(status_code=400, detail="Invalid stage")
        payload = dict(payload)
        payload["stage"] = stage
        con = legacy.db()
        try:
            candidate_id, merged = _upsert_candidate(legacy, con, payload)
            con.commit()
        finally:
            con.close()
        return {"id": candidate_id, "merged": merged}

    @app.post("/analyze")
    async def final_analyze(
        jd: str = Form(...),
        resumes: List[UploadFile] = File(...),
        job_id: Optional[int] = Form(None),
        save_to_ats: bool = Form(False),
    ):
        if len(jd.strip()) < 50:
            raise HTTPException(status_code=400, detail="Please paste a more complete job description.")
        if not resumes:
            raise HTTPException(status_code=400, detail="Upload at least one resume.")
        if len(resumes) > BULK_REQUEST_LIMIT:
            raise HTTPException(
                status_code=400,
                detail=f"Process up to {BULK_REQUEST_LIMIT} resumes per request. The ShortlistAI UI automatically batches up to {BULK_UI_LIMIT} profiles.",
            )

        texts: list[str] = []
        names: list[str] = []
        errors: list[str] = []
        for file in resumes:
            data = await file.read()
            filename = file.filename or "resume"
            try:
                text = legacy.extract_text(filename, data)
                if len(text.strip()) < 80:
                    raise ValueError("Very little readable text was extracted")
                texts.append(text)
                names.append(filename)
            except Exception as exc:
                errors.append(f"{filename}: {exc}")
        if not texts:
            raise HTTPException(status_code=400, detail="No resumes could be read. " + "; ".join(errors))

        similarities = legacy.semantic_scores(jd, texts)
        results: list[dict] = []
        duplicates_merged: list[dict] = []
        con = legacy.db() if save_to_ats else None
        try:
            for text, filename, similarity in zip(texts, names, similarities):
                result = legacy.score_resume(jd, text, similarity)
                candidate_name = legacy.detect_name(text, filename)
                result.update({"candidate": candidate_name, "file": filename})
                results.append(result)
                if con is not None:
                    profile = legacy.extract_profile_details(text, filename)
                    incoming = {
                        "name": candidate_name,
                        "email": legacy.detect_email(text),
                        "phone": legacy.detect_phone(text),
                        "experience": result.get("candidate_years"),
                        "skills": ", ".join(legacy.find_skills(text)),
                        "resume_text": text,
                        "resume_filename": filename,
                        "source": "Resume upload",
                        "profile_details": profile,
                        "job_id": job_id,
                        "stage": "Applied",
                    }
                    candidate_id, merged = _upsert_candidate(legacy, con, incoming, ai_result=result)
                    if merged:
                        duplicates_merged.append({"candidate": candidate_name, "existing_id": candidate_id})
            if con is not None:
                con.commit()
        finally:
            if con is not None:
                con.close()

        results.sort(key=lambda item: item.get("score", 0), reverse=True)
        return {
            "summary": {
                "candidates": len(results),
                "required_skills": legacy.find_skills(jd),
                "required_years": legacy.parse_required_years(jd),
                "strong": sum(item.get("rating") == "Strong" for item in results),
                "average": sum(item.get("rating") == "Average" for item in results),
                "weak": sum(item.get("rating") == "Weak" for item in results),
                "duplicates_merged": len(duplicates_merged),
            },
            "results": results,
            "errors": errors,
            "duplicates_merged": duplicates_merged,
            "duplicates_skipped": [],
            "methodology": "Stable explainable scoring v2: 20% calibrated semantic fit + 45% JD skill coverage + 20% experience fit + 15% recent experience evidence. Semantic similarity is computed independently for each JD/resume pair, so adding other resumes cannot change a candidate's score.",
        }

    @app.get("/api/pipeline-v3")
    def pipeline_v3(job_id: Optional[int] = None):
        con = legacy.db()
        jobs = [dict(row) for row in con.execute("SELECT id,title,status FROM jobs ORDER BY id DESC")]
        if job_id is None and jobs:
            job_id = int(jobs[0]["id"])
        params: list[Any] = []
        sql = """SELECT c.*,j.title AS job_title FROM candidates c
                 LEFT JOIN jobs j ON j.id=c.job_id WHERE 1=1"""
        if job_id is not None:
            sql += " AND c.job_id=?"
            params.append(job_id)
        rows = [legacy._candidate_dict(row) for row in con.execute(sql, params)]
        scheduled_by_candidate: dict[int, list[str]] = {}
        try:
            interview_rows = con.execute(
                "SELECT candidate_id,round_name FROM interviews WHERE status='Scheduled'" + (" AND job_id=?" if job_id is not None else ""),
                ([job_id] if job_id is not None else []),
            ).fetchall()
            for row in interview_rows:
                scheduled_by_candidate.setdefault(int(row["candidate_id"]), []).append(str(row["round_name"] or ""))
        except sqlite3.OperationalError:
            pass
        con.close()

        output: list[dict] = []
        counts = {stage: 0 for stage in PIPELINE_STAGES}
        for candidate in rows:
            stage = effective_pipeline_stage(candidate, scheduled_by_candidate.get(int(candidate["id"])))
            counts[stage] += 1
            output.append({
                "id": candidate["id"],
                "name": candidate.get("name") or "Candidate",
                "email": candidate.get("email") or "",
                "job_id": candidate.get("job_id"),
                "job_title": candidate.get("job_title") or "Unassigned",
                "stage": stage,
                "stored_stage": candidate.get("stage") or "",
                "ai_score": candidate.get("ai_score"),
                "rating": candidate.get("rating") or "",
            })
        return {
            "job_id": job_id,
            "jobs": [{"id": int(job["id"]), "title": job["title"], "status": job.get("status") or "Open"} for job in jobs],
            "stages": list(PIPELINE_STAGES),
            "counts": counts,
            "total": len(output),
            "candidates": output,
        }

    @app.get("/api/final-review/status")
    def final_review_status():
        probe = getattr(app.state, "final_review_probe", {})
        con = legacy.db()
        total = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        con.close()
        return {
            "release": os.getenv("RENDER_GIT_COMMIT", ""),
            "scoring_version": SCORING_VERSION,
            "weights": SCORING_WEIGHTS,
            "pipeline_stages": PIPELINE_STAGES,
            "bulk_ui_limit": BULK_UI_LIMIT,
            "bulk_request_limit": BULK_REQUEST_LIMIT,
            "duplicate_policy": "merge",
            "candidate_total": total,
            "view_switcher": True,
            "probe": probe,
        }

    @app.on_event("startup")
    def final_review_regression_probe():
        source = "__shortlistai_final_review_probe__"
        status: dict[str, Any] = {
            "passed": False,
            "bulk_count": 0,
            "bulk_searchable": False,
            "scoring_stable": False,
            "duplicate_merge": False,
            "boolean_metadata_isolation": False,
        }
        con = legacy.db()
        try:
            con.execute("DELETE FROM candidates WHERE source=?", (source,))
            con.commit()
            now = datetime.utcnow().isoformat()
            for index in range(600):
                skills = "Java, Spring Boot" if index == 599 else "Python, Django, React, JavaScript"
                resume = (
                    f"Bulk Probe {index}\nSkills: {skills}\n"
                    + ("Hands-on Java and Spring Boot delivery." if index == 599 else "Hands-on Python and Django delivery with React and JavaScript.")
                )
                talent = ["Java"] if index % 50 == 0 else ["Python"]
                con.execute(
                    """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,source,
                       profile_details,talent_pools,stage,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"Bulk Probe {index}",f"bulk-probe-{index}@example.test","",4.0,skills,resume,
                        f"bulk_probe_{index}.txt",source,json.dumps({"profile_summary": resume}),
                        legacy.encode_talent_pools(talent),"Applied",now,now,
                    ),
                )
            con.commit()
            con.close()

            verify = legacy.db()
            probe_rows = [legacy._candidate_dict(row) for row in verify.execute("SELECT * FROM candidates WHERE source=? ORDER BY id", (source,))]
            status["bulk_count"] = len(probe_rows)
            status["bulk_searchable"] = any(matches_boolean('Java AND ("Spring Boot" OR Spring)', row) for row in probe_rows)
            metadata_only = next(row for row in probe_rows if row["name"] == "Bulk Probe 0")
            status["boolean_metadata_isolation"] = not matches_boolean("Java", metadata_only)

            jd = "We need a Java engineer with Spring Boot and 4+ years of experience."
            target_resume = "5 years of experience building Java services with Spring Boot. Recent Java Spring Boot delivery."
            score_a = legacy.score_resume(jd, target_resume, legacy.semantic_scores(jd, [target_resume])[0])["score"]
            score_b = legacy.score_resume(jd, target_resume, legacy.semantic_scores(jd, ["Unrelated Python profile", target_resume])[1])["score"]
            status["scoring_stable"] = score_a == score_b

            first = probe_rows[1]
            duplicate_payload = {
                "name": first["name"],
                "email": first["email"],
                "phone": "",
                "skills": "Python, Django, FastAPI",
                "resume_text": first["resume_text"],
                "resume_filename": first["resume_filename"],
                "source": source,
                "profile_details": first["profile_details"],
                "stage": "Contacted",
            }
            candidate_id, merged = _upsert_candidate(legacy, verify, duplicate_payload)
            verify.commit()
            duplicate_count = verify.execute("SELECT COUNT(*) FROM candidates WHERE email=?", (first["email"],)).fetchone()[0]
            status["duplicate_merge"] = merged and duplicate_count == 1 and candidate_id == first["id"]
            status["passed"] = all([
                status["bulk_count"] == 600,
                status["bulk_searchable"],
                status["scoring_stable"],
                status["duplicate_merge"],
                status["boolean_metadata_isolation"],
            ])
            verify.execute("DELETE FROM candidates WHERE source=?", (source,))
            verify.commit()
            verify.close()
        except Exception as exc:
            status["error"] = str(exc)
            try:
                con = legacy.db()
                con.execute("DELETE FROM candidates WHERE source=?", (source,))
                con.commit()
                con.close()
            except Exception:
                pass
        app.state.final_review_probe = status


def install_final_review(legacy) -> None:
    state = getattr(legacy.app, "state", None)
    if state is not None and getattr(state, "_shortlistai_final_review_installed", False):
        return
    _install_routes(legacy)
    if state is not None:
        state._shortlistai_final_review_installed = True


def schedule_final_review_patch(timeout_seconds: float = 10.0) -> None:
    def worker() -> None:
        deadline = time.monotonic() + timeout_seconds
        required = (
            "app","db","analyze","create_candidate","score_resume","semantic_scores","extract_text",
            "detect_name","detect_email","detect_phone","extract_profile_details","find_skills",
            "parse_required_years","_candidate_dict","_candidate_duplicate","_log_activity",
            "classify_talent_pools","encode_talent_pools","normalize","rating",
        )
        while time.monotonic() < deadline:
            module = sys.modules.get("shortlistai_legacy_main")
            if module is None:
                package = sys.modules.get("main")
                module = getattr(package, "legacy", None) if package is not None else None
                if module is None and package is not None and all(hasattr(package, name) for name in required):
                    module = package
            if module is not None and all(hasattr(module, name) for name in required):
                try:
                    install_final_review(module)
                except Exception as exc:
                    print(f"ShortlistAI final review patch failed: {exc}", file=sys.stderr)
                return
            time.sleep(0.01)
        print("ShortlistAI final review patch timed out waiting for runtime.", file=sys.stderr)

    threading.Thread(target=worker, name="shortlistai-final-review", daemon=True).start()
