from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from shortlistai.db.models import Base
from shortlistai.db.repositories import RepositoryConflict, RepositoryNotFound


def identity_values(email: str = "", phone: str = "", resume_text: str = "") -> list[tuple[str, str]]:
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


def _stage_value(existing: str, incoming: str) -> str:
    existing = existing or "Sourced"
    incoming = incoming or "Sourced"
    if existing in {"Joined", "Rejected"}:
        return existing
    rank = {"Sourced": 0, "Screened": 1, "Interview": 2, "Offered": 3, "Joined": 4}
    return incoming if rank.get(incoming, 0) > rank.get(existing, 0) else existing


@dataclass
class CandidatePersistenceService:
    """Atomic candidate create/merge persistence shared by SQLite rollback and PostgreSQL.

    The legacy object is used only for stable product semantics around talent-pool encoding
    and the accepted stage set. Database access itself is entirely SQLAlchemy-based.
    """

    engine: Engine
    workspace_id: int
    legacy: Any

    @property
    def candidates(self):
        return Base.metadata.tables["candidates"]

    @property
    def identities(self):
        return Base.metadata.tables["candidate_identities"]

    @property
    def jobs(self):
        return Base.metadata.tables["jobs"]

    @property
    def activity(self):
        return Base.metadata.tables["activity_log"]

    def _validate_job(self, connection: Connection, job_id: Any) -> None:
        if job_id in (None, ""):
            return
        try:
            job_id = int(job_id)
        except (TypeError, ValueError) as exc:
            raise RepositoryNotFound("Invalid job reference") from exc
        row = connection.execute(
            select(self.jobs.c.id).where(
                and_(self.jobs.c.id == job_id, self.jobs.c.workspace_id == int(self.workspace_id))
            )
        ).first()
        if row is None:
            raise RepositoryNotFound("Job not found in this workspace")

    def _find_duplicate(self, connection: Connection, incoming: dict) -> dict[str, Any] | None:
        values = identity_values(
            incoming.get("email") or "",
            incoming.get("phone") or "",
            incoming.get("resume_text") or "",
        )
        for identity_type, identity_value in values:
            row = connection.execute(
                select(self.candidates)
                .select_from(
                    self.identities.join(
                        self.candidates, self.candidates.c.id == self.identities.c.candidate_id
                    )
                )
                .where(
                    and_(
                        self.identities.c.workspace_id == int(self.workspace_id),
                        self.identities.c.identity_type == identity_type,
                        self.identities.c.identity_value == identity_value,
                        self.candidates.c.workspace_id == int(self.workspace_id),
                    )
                )
                .limit(1)
            ).mappings().first()
            if row:
                return dict(row)

        # Transitional fallback for pre-identity data. Keep it workspace-scoped.
        email = (incoming.get("email") or "").strip().lower()
        if email:
            row = connection.execute(
                select(self.candidates).where(
                    and_(
                        self.candidates.c.workspace_id == int(self.workspace_id),
                        func.lower(self.candidates.c.email) == email,
                    )
                ).limit(1)
            ).mappings().first()
            if row:
                return dict(row)

        phone = re.sub(r"\D", "", incoming.get("phone") or "")
        if len(phone) >= 10:
            phone = phone[-10:]
            rows = connection.execute(
                select(self.candidates.c.id, self.candidates.c.phone).where(
                    self.candidates.c.workspace_id == int(self.workspace_id)
                )
            ).all()
            for candidate_id, stored_phone in rows:
                normalized = re.sub(r"\D", "", stored_phone or "")
                if len(normalized) >= 10 and normalized[-10:] == phone:
                    row = connection.execute(
                        select(self.candidates).where(
                            and_(
                                self.candidates.c.id == int(candidate_id),
                                self.candidates.c.workspace_id == int(self.workspace_id),
                            )
                        )
                    ).mappings().first()
                    return dict(row) if row else None
        return None

    def _replace_identities(self, connection: Connection, candidate_id: int, row: dict[str, Any]) -> None:
        values = identity_values(row.get("email") or "", row.get("phone") or "", row.get("resume_text") or "")
        for identity_type, identity_value in values:
            owner = connection.execute(
                select(self.identities.c.candidate_id).where(
                    and_(
                        self.identities.c.workspace_id == int(self.workspace_id),
                        self.identities.c.identity_type == identity_type,
                        self.identities.c.identity_value == identity_value,
                    )
                )
            ).scalar_one_or_none()
            if owner is not None and int(owner) != int(candidate_id):
                raise RepositoryConflict(
                    f"Candidate identity {identity_type} already belongs to candidate {int(owner)}"
                )
        connection.execute(
            delete(self.identities).where(
                and_(
                    self.identities.c.workspace_id == int(self.workspace_id),
                    self.identities.c.candidate_id == int(candidate_id),
                )
            )
        )
        if values:
            now = datetime.utcnow().isoformat()
            connection.execute(
                insert(self.identities),
                [
                    {
                        "workspace_id": int(self.workspace_id),
                        "candidate_id": int(candidate_id),
                        "identity_type": identity_type,
                        "identity_value": identity_value,
                        "created_at": now,
                    }
                    for identity_type, identity_value in values
                ],
            )

    def _log(self, connection: Connection, candidate_id: int, action: str, details: str) -> None:
        connection.execute(
            insert(self.activity).values(
                workspace_id=int(self.workspace_id),
                candidate_id=int(candidate_id),
                action=action,
                details=details,
                created_at=datetime.utcnow().isoformat(),
            )
        )

    def _merge_pools(self, existing: Any, incoming: Any) -> str:
        left = self.legacy.decode_talent_pools(existing)
        right = incoming if isinstance(incoming, list) else self.legacy.decode_talent_pools(incoming)
        merged: list[str] = []
        for value in [*left, *right]:
            value = str(value).strip()
            if value and value not in merged:
                merged.append(value)
        return self.legacy.encode_talent_pools(merged)

    def _upsert_in_transaction(self, connection: Connection, incoming: dict, reason: str) -> dict:
        stage = incoming.get("stage") or "Sourced"
        if stage not in self.legacy.STAGES:
            raise HTTPException(status_code=400, detail="Invalid stage")
        self._validate_job(connection, incoming.get("job_id"))
        duplicate = self._find_duplicate(connection, incoming)
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

            updates["profile_details"] = _merge_profile(
                current.get("profile_details"),
                incoming.get("profile_details"),
                incoming.get("source") or "",
                incoming.get("job_id"),
                incoming.get("resume_filename") or "",
            )
            updates["talent_pools"] = self._merge_pools(
                current.get("talent_pools"), incoming.get("talent_pools") or []
            )

            same_role = incoming.get("job_id") in (None, current.get("job_id")) or current.get("job_id") is None
            if same_role and incoming.get("ai_score") is not None:
                for field in ("ai_score", "rating", "ai_details"):
                    if incoming.get(field) is not None:
                        updates[field] = incoming[field]

            updates["updated_at"] = now
            changed = [key for key in updates if key != "updated_at"]
            connection.execute(
                update(self.candidates)
                .where(
                    and_(
                        self.candidates.c.id == int(current["id"]),
                        self.candidates.c.workspace_id == int(self.workspace_id),
                    )
                )
                .values(**updates)
            )
            refreshed = connection.execute(
                select(self.candidates).where(
                    and_(
                        self.candidates.c.id == int(current["id"]),
                        self.candidates.c.workspace_id == int(self.workspace_id),
                    )
                )
            ).mappings().one()
            self._replace_identities(connection, int(current["id"]), dict(refreshed))
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
                "talent_pools": self.legacy.decode_talent_pools(updates["talent_pools"]),
            }

        profile = incoming.get("profile_details") or {}
        pools = incoming.get("talent_pools") or []
        payload = {
            "workspace_id": int(self.workspace_id),
            "name": incoming.get("name") or "Candidate",
            "email": incoming.get("email") or "",
            "phone": incoming.get("phone") or "",
            "experience": incoming.get("experience"),
            "skills": incoming.get("skills") or "",
            "resume_text": incoming.get("resume_text") or "",
            "resume_filename": incoming.get("resume_filename") or "",
            "source": incoming.get("source") or "",
            "notice_period": incoming.get("notice_period") or "",
            "current_ctc": incoming.get("current_ctc") or "",
            "expected_ctc": incoming.get("expected_ctc") or "",
            "profile_details": json.dumps(profile, ensure_ascii=False),
            "talent_pools": self.legacy.encode_talent_pools(pools),
            "job_id": incoming.get("job_id"),
            "stage": stage,
            "ai_score": incoming.get("ai_score"),
            "rating": incoming.get("rating"),
            "ai_details": incoming.get("ai_details"),
            "created_at": now,
            "updated_at": now,
        }
        candidate_id = int(
            connection.execute(insert(self.candidates).values(**payload).returning(self.candidates.c.id)).scalar_one()
        )
        created = dict(connection.execute(
            select(self.candidates).where(self.candidates.c.id == candidate_id)
        ).mappings().one())
        self._replace_identities(connection, candidate_id, created)
        self._log(connection, candidate_id, "Candidate created", f"{reason}; Stage: {stage}")
        return {"id": candidate_id, "merged": False, "changed": list(payload.keys()), "talent_pools": pools}

    def upsert(self, incoming: dict, reason: str) -> dict:
        with self.engine.begin() as connection:
            return self._upsert_in_transaction(connection, incoming, reason)

    def upsert_many(self, items: Iterable[dict], reason: str, *, chunk_size: int = 50) -> dict:
        items = list(items)
        created = merged = 0
        ids: list[int] = []
        # Bounded transactions preserve the existing bulk-import behavior while avoiding a
        # single long SQLite write lock. Each candidate merge itself remains fully atomic.
        for start in range(0, len(items), max(1, int(chunk_size))):
            with self.engine.begin() as connection:
                for incoming in items[start:start + max(1, int(chunk_size))]:
                    result = self._upsert_in_transaction(connection, incoming, reason)
                    ids.append(result["id"])
                    merged += int(result["merged"])
                    created += int(not result["merged"])
        return {"received": len(items), "created": created, "merged": merged, "ids": ids}

    def candidate_count(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(
                select(func.count()).select_from(self.candidates).where(
                    self.candidates.c.workspace_id == int(self.workspace_id)
                )
            ).scalar_one())

    def identity_count(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(
                select(func.count()).select_from(self.identities).where(
                    self.identities.c.workspace_id == int(self.workspace_id)
                )
            ).scalar_one())

    def job_exists(self, job_id: int) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(
                select(self.jobs.c.id).where(
                    and_(self.jobs.c.id == int(job_id), self.jobs.c.workspace_id == int(self.workspace_id))
                )
            ).first() is not None
