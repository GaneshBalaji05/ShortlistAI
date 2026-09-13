import functools
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import File, Form, HTTPException, UploadFile


IDENTITY_TYPES = ("email", "phone", "resume")
MAX_BULK_ITEMS = 800


def _configure_sqlite(con: sqlite3.Connection) -> sqlite3.Connection:
    """Apply conservative SQLite settings for concurrent recruiter traffic."""
    for statement in (
        "PRAGMA foreign_keys=ON",
        "PRAGMA busy_timeout=5000",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA journal_mode=WAL",
    ):
        try:
            con.execute(statement)
        except sqlite3.DatabaseError:
            pass
    return con


def _identity_values(email: str = "", phone: str = "", resume_text: str = "") -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    email_value = (email or "").strip().lower()
    if email_value:
        values.append(("email", email_value))
    phone_value = re.sub(r"\D", "", phone or "")
    if len(phone_value) >= 10:
        values.append(("phone", phone_value[-10:]))
    normalized_resume = re.sub(r"\s+", " ", (resume_text or "").strip().lower())
    if len(normalized_resume) >= 80:
        values.append(("resume", hashlib.sha256(normalized_resume.encode("utf-8")).hexdigest()))
    return values


def _workspace_id(con: sqlite3.Connection) -> int:
    value = getattr(con, "workspace_id", None)
    if value is not None:
        return int(value)
    import tenant_security

    return int(tenant_security.current_workspace())


def _ensure_identity_schema(legacy) -> None:
    import tenant_security

    tenant_security.ensure_schema()
    con = _configure_sqlite(tenant_security._raw())
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS candidate_identities(
                workspace_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                identity_type TEXT NOT NULL,
                identity_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, identity_type, identity_value),
                FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidate_identities_candidate ON candidate_identities(workspace_id,candidate_id)"
        )
        rows = con.execute(
            "SELECT id,workspace_id,email,phone,resume_text FROM candidates WHERE workspace_id IS NOT NULL"
        ).fetchall()
        now = datetime.utcnow().isoformat()
        for row in rows:
            for identity_type, identity_value in _identity_values(
                row["email"] or "", row["phone"] or "", row["resume_text"] or ""
            ):
                con.execute(
                    """INSERT OR IGNORE INTO candidate_identities(
                        workspace_id,candidate_id,identity_type,identity_value,created_at
                    ) VALUES(?,?,?,?,?)""",
                    (int(row["workspace_id"]), int(row["id"]), identity_type, identity_value, now),
                )
        con.commit()
    finally:
        con.close()


def _refresh_identities(con: sqlite3.Connection, candidate_id: int) -> None:
    wid = _workspace_id(con)
    row = con.execute(
        "SELECT id,email,phone,resume_text FROM candidates WHERE id=?", (candidate_id,)
    ).fetchone()
    if not row:
        return
    con.execute(
        "DELETE FROM candidate_identities WHERE workspace_id=? AND candidate_id=?",
        (wid, candidate_id),
    )
    now = datetime.utcnow().isoformat()
    for identity_type, identity_value in _identity_values(
        row["email"] or "", row["phone"] or "", row["resume_text"] or ""
    ):
        con.execute(
            """INSERT OR IGNORE INTO candidate_identities(
                workspace_id,candidate_id,identity_type,identity_value,created_at
            ) VALUES(?,?,?,?,?)""",
            (wid, candidate_id, identity_type, identity_value, now),
        )


def _find_duplicate(con: sqlite3.Connection, legacy, email: str, phone: str, resume_text: str):
    wid = _workspace_id(con)
    for identity_type, identity_value in _identity_values(email, phone, resume_text):
        try:
            match = con.execute(
                """SELECT c.* FROM candidate_identities i
                   JOIN candidates c ON c.id=i.candidate_id
                   WHERE i.workspace_id=? AND i.identity_type=? AND i.identity_value=?
                   LIMIT 1""",
                (wid, identity_type, identity_value),
            ).fetchone()
        except sqlite3.OperationalError:
            match = None
        if match:
            return match
    fallback = legacy._candidate_duplicate(con, email, phone)
    if fallback:
        return con.execute("SELECT * FROM candidates WHERE id=?", (fallback["id"],)).fetchone()
    return None


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


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


def _merge_profile(existing: Any, incoming: Any, source: str, job_id: Any, resume_filename: str) -> str:
    current = _safe_json(existing)
    newer = _safe_json(incoming)
    for key, value in newer.items():
        if _nonempty(value) and not _nonempty(current.get(key)):
            current[key] = value

    source_history = current.get("source_history")
    if not isinstance(source_history, list):
        source_history = []
    source_entry = {
        "merged_at": datetime.utcnow().isoformat(),
        "source": source or "",
        "job_id": job_id,
        "resume_filename": resume_filename or "",
    }
    if any(source_entry.values()):
        source_history.append(source_entry)
        current["source_history"] = source_history[-20:]
    current["duplicate_merge_count"] = int(current.get("duplicate_merge_count") or 0) + 1
    return json.dumps(current, ensure_ascii=False)


def _merge_csv(existing: str, incoming: str) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for raw in (existing or "", incoming or ""):
        for item in [x.strip() for x in raw.split(",") if x.strip()]:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                output.append(item)
    return ", ".join(output)


def _merge_pools(legacy, existing: Any, incoming: Any) -> str:
    left = legacy.decode_talent_pools(existing)
    right = incoming if isinstance(incoming, list) else legacy.decode_talent_pools(incoming)
    merged: list[str] = []
    for value in [*left, *right]:
        value = str(value).strip()
        if value and value not in merged:
            merged.append(value)
    return legacy.encode_talent_pools(merged)


def _stage_value(existing: str, incoming: str) -> str:
    existing = existing or "Sourced"
    incoming = incoming or "Sourced"
    if existing in {"Joined", "Rejected"}:
        return existing
    rank = {"Sourced": 0, "Screened": 1, "Interview": 2, "Offered": 3, "Joined": 4}
    return incoming if rank.get(incoming, 0) > rank.get(existing, 0) else existing


def _candidate_payload(legacy, item: Any) -> dict:
    if hasattr(item, "model_dump"):
        data = item.model_dump()
    elif hasattr(item, "dict"):
        data = item.dict()
    else:
        data = dict(item)
    profile = data.get("profile_details") or {}
    pools = data.get("talent_pools")
    if pools is None:
        pools = legacy.classify_talent_pools(
            data.get("resume_text") or "",
            data.get("skills") or "",
            json.dumps(profile, ensure_ascii=False),
        )
    data["profile_details"] = profile
    data["talent_pools"] = pools
    return data


def _upsert_candidate(con: sqlite3.Connection, legacy, incoming: dict, reason: str) -> dict:
    stage = incoming.get("stage") or "Sourced"
    if stage not in legacy.STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")

    duplicate = _find_duplicate(
        con,
        legacy,
        incoming.get("email") or "",
        incoming.get("phone") or "",
        incoming.get("resume_text") or "",
    )
    now = datetime.utcnow().isoformat()
    if duplicate:
        current = dict(duplicate)
        updates: dict[str, Any] = {}
        changed: list[str] = []

        for field in (
            "name", "email", "phone", "source", "notice_period", "current_ctc", "expected_ctc",
        ):
            if _nonempty(incoming.get(field)) and not _nonempty(current.get(field)):
                updates[field] = incoming[field]

        if incoming.get("experience") is not None and current.get("experience") is None:
            updates["experience"] = incoming["experience"]

        merged_skills = _merge_csv(current.get("skills") or "", incoming.get("skills") or "")
        if merged_skills != (current.get("skills") or ""):
            updates["skills"] = merged_skills

        incoming_resume = incoming.get("resume_text") or ""
        current_resume = current.get("resume_text") or ""
        if len(incoming_resume.strip()) > len(current_resume.strip()):
            updates["resume_text"] = incoming_resume
            if incoming.get("resume_filename"):
                updates["resume_filename"] = incoming["resume_filename"]
        elif incoming.get("resume_filename") and not current.get("resume_filename"):
            updates["resume_filename"] = incoming["resume_filename"]

        if current.get("job_id") is None and incoming.get("job_id") is not None:
            updates["job_id"] = incoming["job_id"]

        merged_stage = _stage_value(current.get("stage") or "Sourced", stage)
        if merged_stage != current.get("stage"):
            updates["stage"] = merged_stage

        merged_profile = _merge_profile(
            current.get("profile_details"),
            incoming.get("profile_details"),
            incoming.get("source") or "",
            incoming.get("job_id"),
            incoming.get("resume_filename") or "",
        )
        updates["profile_details"] = merged_profile
        updates["talent_pools"] = _merge_pools(
            legacy, current.get("talent_pools"), incoming.get("talent_pools") or []
        )

        same_role = incoming.get("job_id") in (None, current.get("job_id")) or current.get("job_id") is None
        if same_role and incoming.get("ai_score") is not None:
            for field in ("ai_score", "rating", "ai_details"):
                if incoming.get(field) is not None:
                    updates[field] = incoming[field]

        updates["updated_at"] = now
        for key in updates:
            if key != "updated_at":
                changed.append(key)
        assignments = ",".join(f"{key}=?" for key in updates)
        con.execute(
            f"UPDATE candidates SET {assignments} WHERE id=?",
            (*updates.values(), int(current["id"])),
        )
        legacy._log_activity(
            con,
            int(current["id"]),
            "Duplicate merged",
            f"{reason}; merged fields: {', '.join(changed) or 'identity only'}",
        )
        _refresh_identities(con, int(current["id"]))
        return {
            "id": int(current["id"]),
            "merged": True,
            "changed": changed,
            "talent_pools": legacy.decode_talent_pools(updates["talent_pools"]),
        }

    profile = incoming.get("profile_details") or {}
    pools = incoming.get("talent_pools") or []
    columns = [
        "name", "email", "phone", "experience", "skills", "resume_text", "resume_filename", "source",
        "notice_period", "current_ctc", "expected_ctc", "profile_details", "talent_pools", "job_id", "stage",
        "ai_score", "rating", "ai_details", "created_at", "updated_at",
    ]
    values = [
        incoming.get("name") or "Candidate",
        incoming.get("email") or "",
        incoming.get("phone") or "",
        incoming.get("experience"),
        incoming.get("skills") or "",
        incoming.get("resume_text") or "",
        incoming.get("resume_filename") or "",
        incoming.get("source") or "",
        incoming.get("notice_period") or "",
        incoming.get("current_ctc") or "",
        incoming.get("expected_ctc") or "",
        json.dumps(profile, ensure_ascii=False),
        legacy.encode_talent_pools(pools),
        incoming.get("job_id"),
        stage,
        incoming.get("ai_score"),
        incoming.get("rating"),
        incoming.get("ai_details"),
        now,
        now,
    ]
    placeholders = ",".join("?" for _ in columns)
    cur = con.execute(
        f"INSERT INTO candidates({','.join(columns)}) VALUES({placeholders})",
        values,
    )
    candidate_id = int(cur.lastrowid)
    legacy._log_activity(con, candidate_id, "Candidate created", f"{reason}; Stage: {stage}")
    _refresh_identities(con, candidate_id)
    return {"id": candidate_id, "merged": False, "changed": columns, "talent_pools": pools}


def _patch_connections(legacy) -> None:
    import auth_runtime
    import tenant_security

    if not getattr(tenant_security, "_shortlistai_data_connections_patched", False):
        raw_original = tenant_security._raw
        workspace_original = tenant_security.workspace_db

        @functools.wraps(raw_original)
        def safe_raw():
            return _configure_sqlite(raw_original())

        @functools.wraps(workspace_original)
        def safe_workspace_db():
            return _configure_sqlite(workspace_original())

        tenant_security._raw = safe_raw
        tenant_security.workspace_db = safe_workspace_db
        tenant_security._shortlistai_data_connections_patched = True
        legacy.db = safe_workspace_db

    if not getattr(auth_runtime, "_shortlistai_data_connection_patched", False):
        auth_original = auth_runtime._connect

        @functools.wraps(auth_original)
        def safe_auth_connect():
            return _configure_sqlite(auth_original())

        auth_runtime._connect = safe_auth_connect
        auth_runtime._shortlistai_data_connection_patched = True


def _remove_route(app, path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


def install_data_foundation(app, legacy) -> None:
    state = getattr(app, "state", None)
    if state is not None and getattr(state, "_shortlistai_data_foundation_installed", False):
        return

    _patch_connections(legacy)

    @app.on_event("startup")
    def ensure_data_foundation_schema():
        _ensure_identity_schema(legacy)

    try:
        _ensure_identity_schema(legacy)
    except (sqlite3.OperationalError, HTTPException):
        pass

    _remove_route(app, "/api/candidates", "POST")
    _remove_route(app, "/analyze", "POST")

    @app.post("/api/candidates")
    def create_candidate_merge(x: legacy.CandidateIn):
        incoming = _candidate_payload(legacy, x)
        con = legacy.db()
        try:
            result = _upsert_candidate(con, legacy, incoming, "Manual candidate save")
            con.commit()
            return result
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @app.post("/api/candidates/bulk")
    def bulk_candidates(items: list[legacy.CandidateIn]):
        if not items:
            raise HTTPException(status_code=400, detail="Add at least one candidate.")
        if len(items) > MAX_BULK_ITEMS:
            raise HTTPException(status_code=400, detail=f"Bulk candidate limit is {MAX_BULK_ITEMS} per request.")
        con = legacy.db()
        created = merged = 0
        ids: list[int] = []
        try:
            for index, item in enumerate(items, 1):
                result = _upsert_candidate(con, legacy, _candidate_payload(legacy, item), "Bulk candidate import")
                ids.append(result["id"])
                merged += int(result["merged"])
                created += int(not result["merged"])
                if index % 50 == 0:
                    con.commit()
            con.commit()
            total = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            return {
                "received": len(items),
                "created": created,
                "merged": merged,
                "ids": ids,
                "total_candidates": int(total),
            }
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @app.post("/api/profiles/bulk")
    async def bulk_profiles(
        profiles: list[UploadFile] = File(...),
        job_id: Optional[int] = Form(None),
        source: str = Form("Bulk profile upload"),
    ):
        if not profiles:
            raise HTTPException(status_code=400, detail="Upload at least one profile.")
        if len(profiles) > MAX_BULK_ITEMS:
            raise HTTPException(status_code=400, detail=f"Bulk profile limit is {MAX_BULK_ITEMS} per request.")
        con = legacy.db()
        created = merged = failed = 0
        errors: list[dict[str, str]] = []
        try:
            if job_id is not None and not con.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Job not found in this workspace")
            for index, profile in enumerate(profiles, 1):
                filename = profile.filename or f"profile-{index}"
                try:
                    text = legacy.extract_text(filename, await profile.read())
                    if len(text.strip()) < 80:
                        raise ValueError("Very little readable text was extracted")
                    details = legacy.extract_profile_details(text, filename)
                    incoming = {
                        "name": legacy.detect_name(text, filename),
                        "email": legacy.detect_email(text),
                        "phone": legacy.detect_phone(text),
                        "experience": legacy.parse_candidate_years(text),
                        "skills": ", ".join(legacy.find_skills(text)),
                        "resume_text": text,
                        "resume_filename": filename,
                        "source": source,
                        "notice_period": details.get("notice_period") or "",
                        "current_ctc": details.get("current_ctc") or "",
                        "expected_ctc": details.get("expected_ctc") or "",
                        "profile_details": details,
                        "talent_pools": legacy.classify_talent_pools(text, details.get("skills") or "", json.dumps(details, ensure_ascii=False)),
                        "job_id": job_id,
                        "stage": "Sourced",
                    }
                    result = _upsert_candidate(con, legacy, incoming, "Bulk profile upload")
                    merged += int(result["merged"])
                    created += int(not result["merged"])
                    if index % 25 == 0:
                        con.commit()
                except Exception as exc:
                    failed += 1
                    errors.append({"file": filename, "error": str(exc)})
            con.commit()
            total = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            return {
                "received": len(profiles),
                "created": created,
                "merged": merged,
                "failed": failed,
                "total_candidates": int(total),
                "errors": errors[:50],
            }
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @app.post("/analyze")
    async def analyze_merge(
        jd: str = Form(...),
        resumes: list[UploadFile] = File(...),
        job_id: Optional[int] = Form(None),
        save_to_ats: bool = Form(False),
    ):
        if len(jd.strip()) < 50:
            raise HTTPException(status_code=400, detail="Please paste a more complete job description.")
        if not resumes:
            raise HTTPException(status_code=400, detail="Upload at least one resume.")
        texts: list[str] = []
        names: list[str] = []
        errors: list[str] = []
        for profile in resumes[:50]:
            try:
                text = legacy.extract_text(profile.filename or "resume", await profile.read())
                if len(text.strip()) < 80:
                    raise ValueError("Very little readable text was extracted")
                texts.append(text)
                names.append(profile.filename or "resume")
            except Exception as exc:
                errors.append(str(exc))
        if not texts:
            raise HTTPException(status_code=400, detail="No resumes could be read. " + "; ".join(errors))

        sims = legacy.semantic_scores(jd, texts)
        results: list[dict[str, Any]] = []
        duplicates_merged: list[dict[str, Any]] = []
        con = legacy.db() if save_to_ats else None
        try:
            for text, filename, sim in zip(texts, names, sims):
                score = legacy.score_resume(jd, text, sim)
                score.update({"candidate": legacy.detect_name(text, filename), "file": filename})
                results.append(score)
                if con is not None:
                    details = legacy.extract_profile_details(text, filename)
                    incoming = {
                        "name": score["candidate"],
                        "email": legacy.detect_email(text),
                        "phone": legacy.detect_phone(text),
                        "experience": score.get("candidate_years"),
                        "skills": ", ".join(legacy.find_skills(text)),
                        "resume_text": text,
                        "resume_filename": filename,
                        "source": "Resume upload",
                        "profile_details": details,
                        "talent_pools": legacy.classify_talent_pools(text, details.get("skills") or "", json.dumps(details, ensure_ascii=False)),
                        "job_id": job_id,
                        "stage": "Sourced",
                        "ai_score": score.get("score"),
                        "rating": score.get("rating"),
                        "ai_details": json.dumps(score, ensure_ascii=False),
                    }
                    upserted = _upsert_candidate(con, legacy, incoming, "AI shortlist save")
                    score["candidate_id"] = upserted["id"]
                    if upserted["merged"]:
                        duplicates_merged.append({
                            "candidate": score["candidate"],
                            "existing_id": upserted["id"],
                        })
            if con is not None:
                con.commit()
        except Exception:
            if con is not None:
                con.rollback()
            raise
        finally:
            if con is not None:
                con.close()

        results.sort(key=lambda row: row["score"], reverse=True)
        required = legacy.find_skills(jd)
        return {
            "summary": {
                "candidates": len(results),
                "required_skills": required,
                "required_years": legacy.parse_required_years(jd),
                "strong": sum(row["rating"] == "Strong" for row in results),
                "average": sum(row["rating"] == "Average" for row in results),
                "weak": sum(row["rating"] == "Weak" for row in results),
                "duplicates_merged": len(duplicates_merged),
                "duplicates_skipped": 0,
            },
            "results": results,
            "errors": errors,
            "duplicates_merged": duplicates_merged,
            "duplicates_skipped": [],
            "methodology": "20% calibrated semantic fit + 45% JD skill coverage + 20% experience fit + 15% recent experience evidence. Raw semantic similarity is shown separately. Use as recruiter decision support, not an autonomous hiring decision.",
        }

    @app.get("/api/data-health")
    def data_health():
        con = legacy.db()
        try:
            total = int(con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
            journal = str(con.execute("PRAGMA journal_mode").fetchone()[0])
            busy_timeout = int(con.execute("PRAGMA busy_timeout").fetchone()[0])
            foreign_keys = int(con.execute("PRAGMA foreign_keys").fetchone()[0])
            wid = _workspace_id(con)
            identities = int(con.execute(
                "SELECT COUNT(*) FROM candidate_identities WHERE workspace_id=?", (wid,)
            ).fetchone()[0])
            return {
                "storage_backend": "sqlite",
                "migration_target": "postgresql",
                "candidate_count": total,
                "identity_count": identities,
                "journal_mode": journal,
                "busy_timeout_ms": busy_timeout,
                "foreign_keys": bool(foreign_keys),
                "bulk_limit": MAX_BULK_ITEMS,
                "durability_note": "Local SQLite is process-local unless SQLITE_PATH points to durable storage; PostgreSQL migration remains the production durability target.",
            }
        finally:
            con.close()

    legacy.create_candidate = create_candidate_merge
    legacy.analyze = analyze_merge
    if state is not None:
        state._shortlistai_data_foundation_installed = True


def schedule_data_foundation_patch(module_name: str = "main", timeout_seconds: float = 15.0) -> None:
    """Install after routes and tenant security are ready."""

    def worker() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            module = sys.modules.get("main") or sys.modules.get("shortlistai_legacy_main")
            target = getattr(module, "legacy", module) if module is not None else None
            app = getattr(target, "app", None) if target is not None else None
            state = getattr(app, "state", None) if app is not None else None
            if (
                target is not None
                and app is not None
                and all(hasattr(target, name) for name in ("create_candidate", "analyze", "CandidateIn"))
                and state is not None
                and getattr(state, "shortlistai_tenant_security", False)
            ):
                try:
                    install_data_foundation(app, target)
                except Exception as exc:
                    print(f"ShortlistAI data foundation patch failed: {exc}", file=sys.stderr)
                return
            time.sleep(0.01)
        print("ShortlistAI data foundation patch timed out waiting for secured runtime.", file=sys.stderr)

    threading.Thread(target=worker, name="shortlistai-data-foundation", daemon=True).start()
