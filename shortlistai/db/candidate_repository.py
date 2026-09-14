from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from final_review import PIPELINE_STAGES, STAGE_RANK, canonical_stage
from shortlistai_talent import decode_talent_pools, encode_talent_pools

from .models import ActivityLog, Candidate, CandidateIdentity, Job


class CandidateIdentityConflict(RuntimeError):
    """Raised when supplied identity evidence points at multiple candidates."""


class CandidateReferenceError(RuntimeError):
    """Raised when a workspace-scoped foreign reference is invalid."""


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""


def _resume_fingerprint(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if len(normalized) < 80:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_linkedin(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("www."):
        raw = "https://" + raw
    elif raw.startswith("linkedin.com/"):
        raw = "https://" + raw

    if "://" in raw:
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return ""
        if (parsed.hostname or "").lower() not in {"linkedin.com", "www.linkedin.com"}:
            return ""
        path = parsed.path.strip("/")
        match = re.match(r"(?i)^in/([^/]+)$", path)
        if not match:
            return ""
        handle = match.group(1)
    else:
        match = re.search(r"(?i)(?:^|/)in/([^/?#]+)", raw)
        if match:
            handle = match.group(1)
        elif re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", raw):
            handle = raw
        else:
            return ""
    return handle.strip().strip("/").lower()


def _linkedin_from_profile(value: Any) -> str:
    profile = _safe_json(value)
    for key in ("linkedin_id", "profile_link", "linkedin_url", "linkedin_profile", "linkedin"):
        normalized = _normalize_linkedin(profile.get(key))
        if normalized:
            return normalized
    return ""


def _identity_values(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    email = _normalize_email(payload.get("email"))
    phone = _normalize_phone(payload.get("phone"))
    resume = _resume_fingerprint(payload.get("resume_text"))
    linkedin = _linkedin_from_profile(payload.get("profile_details"))
    if email:
        values.append(("email", email))
    if phone:
        values.append(("phone", phone))
    if resume:
        values.append(("resume", resume))
    if linkedin:
        values.append(("linkedin", linkedin))
    return values


def _merge_csv(existing: Any, incoming: Any) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for raw in (str(existing or ""), str(incoming or "")):
        for item in [part.strip() for part in raw.split(",") if part.strip()]:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
    return ", ".join(out)


def _merge_pools(existing: Any, incoming: Any) -> str:
    left = decode_talent_pools(existing if isinstance(existing, str) else encode_talent_pools(existing or []))
    right = decode_talent_pools(incoming if isinstance(incoming, str) else encode_talent_pools(incoming or []))
    merged: list[str] = []
    for value in [*left, *right]:
        value = str(value).strip()
        if value and value not in merged:
            merged.append(value)
    return encode_talent_pools(merged)


def _merge_profile(existing: Any, incoming: Any, *, source: Any, job_id: Any, resume_filename: Any) -> str:
    current = _safe_json(existing)
    newer = _safe_json(incoming)
    for key, value in newer.items():
        if value not in (None, "", [], {}) and current.get(key) in (None, "", [], {}):
            current[key] = value

    source_history = current.get("source_history")
    if not isinstance(source_history, list):
        source_history = []
    source_history.append(
        {
            "merged_at": datetime.utcnow().isoformat(),
            "source": str(source or ""),
            "job_id": job_id,
            "resume_filename": str(resume_filename or ""),
        }
    )
    current["source_history"] = source_history[-20:]
    current["duplicate_merge_count"] = int(current.get("duplicate_merge_count") or 0) + 1
    return json.dumps(current, ensure_ascii=False)


def _later_stage(existing: Any, incoming: Any) -> str:
    old = canonical_stage(existing)
    new = canonical_stage(incoming)
    if old in {"Hired", "Dropped"}:
        return old
    return new if STAGE_RANK.get(new, 0) > STAGE_RANK.get(old, 0) else old


@dataclass(frozen=True)
class CandidatePersistenceRepository:
    """Atomic workspace-scoped candidate create/merge boundary.

    This mirrors the conflict-safe behavior of ``data_foundation_v2`` without depending
    on the SQLite SQL-rewrite bridge. It is intentionally route-neutral so live routes
    can be migrated onto it incrementally after dual-engine regression is green.
    """

    engine: Engine
    workspace_id: int

    @property
    def _candidates(self):
        return Candidate.__table__

    @property
    def _identities(self):
        return CandidateIdentity.__table__

    @property
    def _jobs(self):
        return Job.__table__

    @property
    def _activity(self):
        return ActivityLog.__table__

    def _validate_job(self, connection: Connection, job_id: Any) -> None:
        if job_id in (None, ""):
            return
        try:
            job_id = int(job_id)
        except (TypeError, ValueError) as exc:
            raise CandidateReferenceError("Invalid job reference") from exc
        exists = connection.execute(
            select(self._jobs.c.id).where(
                and_(self._jobs.c.id == job_id, self._jobs.c.workspace_id == self.workspace_id)
            )
        ).first()
        if not exists:
            raise CandidateReferenceError("Job not found in this workspace")

    def _fallback_identity_matches(
        self,
        connection: Connection,
        payload: Mapping[str, Any],
        *,
        exclude_candidate_id: int | None = None,
    ) -> set[int]:
        email = _normalize_email(payload.get("email"))
        phone = _normalize_phone(payload.get("phone"))
        linkedin = _linkedin_from_profile(payload.get("profile_details"))
        if not (email or phone or linkedin):
            return set()

        stmt = select(
            self._candidates.c.id,
            self._candidates.c.email,
            self._candidates.c.phone,
            self._candidates.c.profile_details,
        ).where(self._candidates.c.workspace_id == self.workspace_id)
        if exclude_candidate_id is not None:
            stmt = stmt.where(self._candidates.c.id != int(exclude_candidate_id))

        matched: set[int] = set()
        for row in connection.execute(stmt).mappings():
            if email and _normalize_email(row["email"]) == email:
                matched.add(int(row["id"]))
            if phone and _normalize_phone(row["phone"]) == phone:
                matched.add(int(row["id"]))
            if linkedin and _linkedin_from_profile(row["profile_details"]) == linkedin:
                matched.add(int(row["id"]))
        return matched

    def _identity_match_ids(self, connection: Connection, payload: Mapping[str, Any]) -> set[int]:
        matched = self._fallback_identity_matches(connection, payload)
        for identity_type, identity_value in _identity_values(payload):
            rows = connection.execute(
                select(self._identities.c.candidate_id).where(
                    and_(
                        self._identities.c.workspace_id == self.workspace_id,
                        self._identities.c.identity_type == identity_type,
                        self._identities.c.identity_value == identity_value,
                    )
                )
            ).all()
            matched.update(int(row[0]) for row in rows)
        return matched

    def _find_duplicate(self, connection: Connection, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        matched = self._identity_match_ids(connection, payload)
        if len(matched) > 1:
            raise CandidateIdentityConflict(
                "Conflicting candidate identities resolve to multiple existing candidates; manual review is required."
            )
        if not matched:
            return None
        candidate_id = next(iter(matched))
        row = connection.execute(
            select(self._candidates).where(
                and_(
                    self._candidates.c.id == candidate_id,
                    self._candidates.c.workspace_id == self.workspace_id,
                )
            )
        ).mappings().first()
        return dict(row) if row else None

    def _refresh_identities(
        self,
        connection: Connection,
        candidate_id: int,
        candidate_payload: Mapping[str, Any],
    ) -> None:
        desired = _identity_values(candidate_payload)
        fallback_owners = self._fallback_identity_matches(
            connection, candidate_payload, exclude_candidate_id=candidate_id
        )
        if fallback_owners:
            raise CandidateIdentityConflict(
                "Candidate identity is already owned by another candidate; write was not applied."
            )

        for identity_type, identity_value in desired:
            owner = connection.execute(
                select(self._identities.c.candidate_id).where(
                    and_(
                        self._identities.c.workspace_id == self.workspace_id,
                        self._identities.c.identity_type == identity_type,
                        self._identities.c.identity_value == identity_value,
                    )
                )
            ).scalar_one_or_none()
            if owner is not None and int(owner) != int(candidate_id):
                raise CandidateIdentityConflict(
                    "Candidate identity is already owned by another candidate; write was not applied."
                )

        connection.execute(
            delete(self._identities).where(
                and_(
                    self._identities.c.workspace_id == self.workspace_id,
                    self._identities.c.candidate_id == int(candidate_id),
                )
            )
        )
        now = datetime.utcnow().isoformat()
        for identity_type, identity_value in desired:
            connection.execute(
                insert(self._identities).values(
                    workspace_id=self.workspace_id,
                    candidate_id=int(candidate_id),
                    identity_type=identity_type,
                    identity_value=identity_value,
                    created_at=now,
                )
            )

    def _log(self, connection: Connection, candidate_id: int, action: str, details: str) -> None:
        connection.execute(
            insert(self._activity).values(
                workspace_id=self.workspace_id,
                candidate_id=int(candidate_id),
                action=action,
                details=details,
                created_at=datetime.utcnow().isoformat(),
            )
        )

    def _current_candidate(self, connection: Connection, candidate_id: int) -> dict[str, Any]:
        row = connection.execute(
            select(self._candidates).where(
                and_(
                    self._candidates.c.id == int(candidate_id),
                    self._candidates.c.workspace_id == self.workspace_id,
                )
            )
        ).mappings().one()
        return dict(row)

    def upsert(self, values: Mapping[str, Any], *, reason: str = "Candidate save") -> dict[str, Any]:
        payload = dict(values)
        payload["stage"] = canonical_stage(payload.get("stage"))
        if payload["stage"] not in PIPELINE_STAGES:
            raise ValueError("Invalid candidate stage")
        self._validate_payload_workspace(payload)

        try:
            with self.engine.begin() as connection:
                self._validate_job(connection, payload.get("job_id"))
                duplicate = self._find_duplicate(connection, payload)
                now = datetime.utcnow().isoformat()

                if duplicate is None:
                    candidate_values = {
                        "workspace_id": self.workspace_id,
                        "name": payload.get("name") or "Candidate",
                        "email": payload.get("email") or "",
                        "phone": payload.get("phone") or "",
                        "experience": payload.get("experience"),
                        "skills": payload.get("skills") or "",
                        "resume_text": payload.get("resume_text") or "",
                        "source": payload.get("source") or "",
                        "notice_period": payload.get("notice_period") or "",
                        "current_ctc": payload.get("current_ctc") or "",
                        "expected_ctc": payload.get("expected_ctc") or "",
                        "job_id": payload.get("job_id"),
                        "stage": payload["stage"],
                        "ai_score": payload.get("ai_score"),
                        "rating": payload.get("rating"),
                        "created_at": now,
                        "updated_at": now,
                        "ai_details": payload.get("ai_details"),
                        "resume_filename": payload.get("resume_filename") or "",
                        "profile_details": json.dumps(_safe_json(payload.get("profile_details")), ensure_ascii=False),
                        "talent_pools": _merge_pools("", payload.get("talent_pools") or []),
                    }
                    result = connection.execute(insert(self._candidates).values(**candidate_values))
                    candidate_id = int(result.inserted_primary_key[0])
                    current = self._current_candidate(connection, candidate_id)
                    self._refresh_identities(connection, candidate_id, current)
                    self._log(connection, candidate_id, "Candidate created", f"{reason}; Stage: {payload['stage']}")
                    return {
                        "id": candidate_id,
                        "merged": False,
                        "changed": [key for key in candidate_values if key != "workspace_id"],
                        "talent_pools": decode_talent_pools(current.get("talent_pools")),
                    }

                current = dict(duplicate)
                updates: dict[str, Any] = {}
                changed: list[str] = []
                for field in (
                    "name",
                    "email",
                    "phone",
                    "source",
                    "notice_period",
                    "current_ctc",
                    "expected_ctc",
                ):
                    if payload.get(field) not in (None, "", [], {}) and current.get(field) in (None, "", [], {}):
                        updates[field] = payload[field]

                if payload.get("experience") is not None and current.get("experience") is None:
                    updates["experience"] = payload["experience"]

                merged_skills = _merge_csv(current.get("skills"), payload.get("skills"))
                if merged_skills != str(current.get("skills") or ""):
                    updates["skills"] = merged_skills

                incoming_resume = str(payload.get("resume_text") or "")
                current_resume = str(current.get("resume_text") or "")
                if len(incoming_resume.strip()) > len(current_resume.strip()):
                    updates["resume_text"] = incoming_resume
                    if payload.get("resume_filename"):
                        updates["resume_filename"] = payload["resume_filename"]
                elif payload.get("resume_filename") and not current.get("resume_filename"):
                    updates["resume_filename"] = payload["resume_filename"]

                if current.get("job_id") is None and payload.get("job_id") is not None:
                    updates["job_id"] = payload["job_id"]

                later_stage = _later_stage(current.get("stage"), payload.get("stage"))
                if later_stage != canonical_stage(current.get("stage")):
                    updates["stage"] = later_stage

                updates["profile_details"] = _merge_profile(
                    current.get("profile_details"),
                    payload.get("profile_details"),
                    source=payload.get("source"),
                    job_id=payload.get("job_id"),
                    resume_filename=payload.get("resume_filename"),
                )
                updates["talent_pools"] = _merge_pools(
                    current.get("talent_pools"), payload.get("talent_pools") or []
                )

                same_role = (
                    payload.get("job_id") in (None, current.get("job_id"))
                    or current.get("job_id") is None
                )
                if same_role and payload.get("ai_score") is not None:
                    for field in ("ai_score", "rating", "ai_details"):
                        if payload.get(field) is not None:
                            updates[field] = payload[field]

                updates["updated_at"] = now
                changed.extend(key for key in updates if key != "updated_at")
                connection.execute(
                    update(self._candidates)
                    .where(
                        and_(
                            self._candidates.c.id == int(current["id"]),
                            self._candidates.c.workspace_id == self.workspace_id,
                        )
                    )
                    .values(**updates)
                )
                refreshed = self._current_candidate(connection, int(current["id"]))
                self._refresh_identities(connection, int(current["id"]), refreshed)
                self._log(
                    connection,
                    int(current["id"]),
                    "Duplicate merged",
                    f"{reason}; merged fields: {', '.join(changed) or 'identity only'}",
                )
                return {
                    "id": int(current["id"]),
                    "merged": True,
                    "changed": changed,
                    "talent_pools": decode_talent_pools(refreshed.get("talent_pools")),
                }
        except IntegrityError as exc:
            if "candidate_identities" in str(getattr(exc, "orig", exc)).lower():
                raise CandidateIdentityConflict(
                    "Candidate identity is already owned by another candidate; write was not applied."
                ) from exc
            raise

    def _validate_payload_workspace(self, payload: Mapping[str, Any]) -> None:
        supplied = payload.get("workspace_id")
        if supplied not in (None, self.workspace_id):
            raise CandidateReferenceError("Cross-workspace candidate write rejected")
