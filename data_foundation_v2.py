from __future__ import annotations

import json
import re
import sys
import threading
import time
from contextvars import ContextVar
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import File, Form, HTTPException, UploadFile

import data_foundation as foundation
import ingestion_runtime as ingestion
from final_review import STAGE_RANK, canonical_stage


_original_upsert = foundation._upsert_candidate
_original_identity_values = foundation._identity_values
_incoming_linkedin: ContextVar[str] = ContextVar("shortlistai_incoming_linkedin", default="")


def _normalize_linkedin(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().strip()
    if lowered.startswith("www."):
        lowered = "https://" + lowered
    elif lowered.startswith("linkedin.com/"):
        lowered = "https://" + lowered

    if "://" in lowered:
        try:
            parsed = urlsplit(lowered)
        except ValueError:
            return ""
        host = (parsed.hostname or "").lower()
        if host not in {"linkedin.com", "www.linkedin.com"}:
            return ""
        path = parsed.path.strip("/")
        match = re.match(r"(?i)^in/([^/]+)$", path)
        if not match:
            return ""
        handle = match.group(1)
    else:
        match = re.search(r"(?i)(?:^|/)in/([^/?#]+)", lowered)
        if match:
            handle = match.group(1)
        elif re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", lowered):
            handle = lowered
        else:
            return ""
    return handle.strip().strip("/").lower()


def _linkedin_from_profile(profile: Any) -> str:
    data = foundation._safe_json(profile)
    for key in ("linkedin_id", "linkedin_url", "linkedin_profile", "linkedin"):
        value = _normalize_linkedin(data.get(key))
        if value:
            return value
    return ""


def _identity_values(
    email: str = "",
    phone: str = "",
    resume_text: str = "",
    linkedin: str = "",
) -> list[tuple[str, str]]:
    values = list(_original_identity_values(email, phone, resume_text))
    linkedin_value = _normalize_linkedin(linkedin)
    if linkedin_value:
        values.append(("linkedin", linkedin_value))
    return values


def _linkedin_candidate_ids(con, normalized_linkedin: str, exclude_id: Optional[int] = None) -> set[int]:
    if not normalized_linkedin:
        return set()
    params: list[Any] = []
    sql = "SELECT id,profile_details FROM candidates"
    if exclude_id is not None:
        sql += " WHERE id<>?"
        params.append(int(exclude_id))
    matches: set[int] = set()
    for row in con.execute(sql, params).fetchall():
        if _linkedin_from_profile(row["profile_details"]) == normalized_linkedin:
            matches.add(int(row["id"]))
    return matches


def _safe_find_duplicate(con, legacy, email: str, phone: str, resume_text: str):
    """Resolve all supplied identities before merging; never pick an arbitrary first match."""
    wid = foundation._workspace_id(con)
    linkedin = _incoming_linkedin.get()
    identities = _identity_values(email, phone, resume_text, linkedin)
    matched_ids: set[int] = set()

    for identity_type, identity_value in identities:
        try:
            rows = con.execute(
                """SELECT candidate_id FROM candidate_identities
                   WHERE workspace_id=? AND identity_type=? AND identity_value=?""",
                (wid, identity_type, identity_value),
            ).fetchall()
        except Exception:
            rows = []
        matched_ids.update(int(row["candidate_id"]) for row in rows)
        if identity_type == "linkedin":
            matched_ids.update(_linkedin_candidate_ids(con, identity_value))

    fallback = legacy._candidate_duplicate(con, email, phone)
    if fallback:
        matched_ids.add(int(fallback["id"]))

    if len(matched_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail="Conflicting candidate identities resolve to multiple existing candidates; manual review is required.",
        )
    if not matched_ids:
        return None
    candidate_id = next(iter(matched_ids))
    return con.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()


def _safe_refresh_identities(con, candidate_id: int) -> None:
    """Refresh identity keys only after proving none belongs to another candidate."""
    wid = foundation._workspace_id(con)
    row = con.execute(
        "SELECT id,email,phone,resume_text,profile_details FROM candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return

    linkedin = _linkedin_from_profile(row["profile_details"])
    identities = _identity_values(
        row["email"] or "",
        row["phone"] or "",
        row["resume_text"] or "",
        linkedin,
    )

    for identity_type, identity_value in identities:
        owner = con.execute(
            """SELECT candidate_id FROM candidate_identities
               WHERE workspace_id=? AND identity_type=? AND identity_value=?
               LIMIT 1""",
            (wid, identity_type, identity_value),
        ).fetchone()
        if owner and int(owner["candidate_id"]) != int(candidate_id):
            raise HTTPException(
                status_code=409,
                detail="Candidate identity is already owned by another candidate; write was not applied.",
            )
        if identity_type == "linkedin" and _linkedin_candidate_ids(con, identity_value, int(candidate_id)):
            raise HTTPException(
                status_code=409,
                detail="LinkedIn identity is already present on another candidate; write was not applied.",
            )

    con.execute(
        "DELETE FROM candidate_identities WHERE workspace_id=? AND candidate_id=?",
        (wid, candidate_id),
    )
    now = foundation.datetime.utcnow().isoformat()
    for identity_type, identity_value in identities:
        con.execute(
            """INSERT INTO candidate_identities(
                workspace_id,candidate_id,identity_type,identity_value,created_at
            ) VALUES(?,?,?,?,?)""",
            (wid, int(candidate_id), identity_type, identity_value, now),
        )


def _pipeline_stage_value(existing: str, incoming: str) -> str:
    old = canonical_stage(existing)
    new = canonical_stage(incoming)
    if old in {"Hired", "Dropped"}:
        return old
    return new if STAGE_RANK.get(new, 0) > STAGE_RANK.get(old, 0) else old


def _pipeline_upsert(con, legacy, incoming: dict, reason: str):
    payload = dict(incoming)
    payload["stage"] = canonical_stage(payload.get("stage"))
    token = _incoming_linkedin.set(_linkedin_from_profile(payload.get("profile_details")))
    try:
        return _original_upsert(con, legacy, payload, reason)
    finally:
        _incoming_linkedin.reset(token)


# The foundation module resolves these functions from module globals at runtime.
# Replace only data-integrity adapters while keeping the existing storage/API behavior.
foundation._identity_values = _identity_values
foundation._find_duplicate = _safe_find_duplicate
foundation._refresh_identities = _safe_refresh_identities
foundation._stage_value = _pipeline_stage_value
foundation._upsert_candidate = _pipeline_upsert


def _install_safe_bulk_profile_route(app, legacy) -> None:
    """Keep the bulk-upload API while persisting resumable batch/item state underneath it."""
    foundation._remove_route(app, "/api/profiles/bulk", "POST")

    @app.post("/api/profiles/bulk")
    async def bulk_profiles_integrity_v2(
        profiles: list[UploadFile] = File(...),
        job_id: Optional[int] = Form(None),
        source: str = Form("Bulk profile upload"),
    ):
        if not profiles:
            raise HTTPException(status_code=400, detail="Upload at least one profile.")
        if len(profiles) > foundation.MAX_BULK_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=f"Bulk profile limit is {foundation.MAX_BULK_ITEMS} per request.",
            )
        con = legacy.db()
        try:
            if job_id is not None and not con.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Job not found in this workspace")
            batch_id, resumed = await ingestion.stage_uploaded_profiles(
                con,
                legacy,
                profiles,
                job_id=job_id,
                source=source,
            )
            before = ingestion.current_counts(con, batch_id)
            ingestion.process_ingestion_batch(con, legacy, batch_id)
            return ingestion.batch_response(
                con,
                batch_id,
                before_counts=before,
                resumed=resumed,
            )
        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk candidate import failed: {exc}")
        finally:
            con.close()


def schedule_data_foundation_v2_patch(timeout_seconds: float = 15.0) -> None:
    """Install only after final-review and tenant-security patches are both active."""

    def worker() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            package = sys.modules.get("main")
            legacy = getattr(package, "legacy", None) if package is not None else None
            if legacy is None:
                legacy = sys.modules.get("shortlistai_legacy_main")
            app = getattr(legacy, "app", None) if legacy is not None else None
            state = getattr(app, "state", None) if app is not None else None
            if (
                legacy is not None
                and app is not None
                and state is not None
                and getattr(state, "shortlistai_tenant_security", False)
                and getattr(state, "_shortlistai_final_review_installed", False)
            ):
                try:
                    foundation.install_data_foundation(app, legacy)
                    ingestion.ensure_ingestion_schema()
                    _install_safe_bulk_profile_route(app, legacy)
                except Exception as exc:
                    print(f"ShortlistAI data foundation v2 patch failed: {exc}", file=sys.stderr)
                return
            time.sleep(0.01)
        print("ShortlistAI data foundation v2 patch timed out waiting for final-review/security runtime.", file=sys.stderr)

    threading.Thread(target=worker, name="shortlistai-data-foundation-v2", daemon=True).start()
