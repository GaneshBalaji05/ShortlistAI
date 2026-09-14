from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete, func, insert, select

from shortlistai.db.candidate_repository import (
    CandidateIdentityConflict,
    CandidatePersistenceRepository,
    CandidateReferenceError,
)
from shortlistai.db.models import ActivityLog, Base, Candidate, CandidateIdentity, Job, Workspace
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url


def _engine_for_test():
    configured = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if is_postgres_url(configured):
        return create_database_engine(configured), None

    temp_dir = tempfile.TemporaryDirectory(prefix="shortlistai-candidate-repo-")
    path = Path(temp_dir.name) / "candidate-repository.db"
    engine = create_database_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine, temp_dir


def _seed_workspace_and_job(engine, suffix: str):
    now = "2026-09-14T00:00:00"
    with engine.begin() as connection:
        workspace_id = int(
            connection.execute(
                insert(Workspace.__table__)
                .values(name=f"Candidate Repo {suffix}", created_at=now)
                .returning(Workspace.__table__.c.id)
            ).scalar_one()
        )
        job_id = int(
            connection.execute(
                insert(Job.__table__)
                .values(
                    workspace_id=workspace_id,
                    title=f"Role {suffix}",
                    department="Engineering",
                    location="Chennai",
                    jd="Java Spring Boot",
                    status="Open",
                    created_at=now,
                )
                .returning(Job.__table__.c.id)
            ).scalar_one()
        )
    return workspace_id, job_id


def run() -> None:
    engine, temp_dir = _engine_for_test()
    suffix = uuid.uuid4().hex[:10]
    w1 = w2 = None
    try:
        w1, job1 = _seed_workspace_and_job(engine, suffix + "a")
        w2, job2 = _seed_workspace_and_job(engine, suffix + "b")
        repo1 = CandidatePersistenceRepository(engine, w1)
        repo2 = CandidatePersistenceRepository(engine, w2)

        resume = "Java Spring Boot backend engineer " * 8
        created = repo1.upsert(
            {
                "name": "Candidate One",
                "email": "candidate.one@example.com",
                "phone": "+91 98765 43210",
                "skills": "Java, Spring Boot",
                "resume_text": resume,
                "resume_filename": "candidate-one.pdf",
                "source": "Naukri",
                "profile_details": {
                    "linkedin_id": "https://www.linkedin.com/in/candidate-one/",
                    "current_location": "Chennai",
                },
                "talent_pools": ["Java"],
                "job_id": job1,
                "stage": "Sourced",
                "ai_score": 72.0,
                "rating": "Average",
                "ai_details": json.dumps({"score": 72.0}),
            },
            reason="Repository test create",
        )
        candidate_id = created["id"]
        assert created["merged"] is False

        merged = repo1.upsert(
            {
                "name": "Different Incoming Name",
                "email": "CANDIDATE.ONE@EXAMPLE.COM",
                "phone": "98765-43210",
                "skills": "Java, PostgreSQL",
                "resume_text": resume + " PostgreSQL production ownership and API reliability.",
                "resume_filename": "candidate-one-v2.pdf",
                "source": "Referral",
                "profile_details": {
                    "linkedin_id": "linkedin.com/in/candidate-one",
                    "current_location": "Bengaluru",
                    "notice_period": "30 days",
                },
                "talent_pools": ["Java", "Cloud"],
                "job_id": job1,
                "stage": "Screened",
                "ai_score": 88.0,
                "rating": "Strong",
                "ai_details": json.dumps({"score": 88.0}),
            },
            reason="Repository test merge",
        )
        assert merged["merged"] is True
        assert merged["id"] == candidate_id

        candidates = Candidate.__table__
        identities = CandidateIdentity.__table__
        activity = ActivityLog.__table__
        with engine.connect() as connection:
            row = connection.execute(
                select(candidates).where(
                    (candidates.c.id == candidate_id) & (candidates.c.workspace_id == w1)
                )
            ).mappings().one()
            assert row["name"] == "Candidate One"
            assert row["ai_score"] == 88.0
            assert row["stage"] == "Contacted"
            assert "PostgreSQL" in (row["skills"] or "")
            profile = json.loads(row["profile_details"] or "{}")
            assert profile["current_location"] == "Chennai"
            assert profile["notice_period"] == "30 days"
            assert profile["duplicate_merge_count"] == 1
            identity_types = {
                item[0]
                for item in connection.execute(
                    select(identities.c.identity_type).where(
                        (identities.c.workspace_id == w1)
                        & (identities.c.candidate_id == candidate_id)
                    )
                )
            }
            assert {"email", "phone", "resume", "linkedin"}.issubset(identity_types)
            activity_count = int(
                connection.execute(
                    select(func.count()).select_from(activity).where(
                        (activity.c.workspace_id == w1)
                        & (activity.c.candidate_id == candidate_id)
                    )
                ).scalar_one()
            )
            assert activity_count == 2

        # Same identity values are legal in a different workspace.
        other = repo2.upsert(
            {
                "name": "Workspace Two Candidate",
                "email": "candidate.one@example.com",
                "phone": "9876543210",
                "resume_text": resume,
                "profile_details": {"linkedin_id": "https://linkedin.com/in/candidate-one"},
                "job_id": job2,
                "stage": "Applied",
            }
        )
        assert other["id"] != candidate_id

        # A job owned by another workspace must never be attached.
        try:
            repo1.upsert(
                {
                    "name": "Wrong Job",
                    "email": f"wrong-job-{suffix}@example.com",
                    "job_id": job2,
                    "stage": "Applied",
                }
            )
            raise AssertionError("Cross-workspace job reference should have failed")
        except CandidateReferenceError:
            pass

        # Scoring is role-specific: a duplicate submitted for another role must not
        # overwrite the score or original job assignment.
        repo1.upsert(
            {
                "email": "candidate.one@example.com",
                "phone": "9876543210",
                "job_id": job2,
                "stage": "Applied",
                "ai_score": 5.0,
                "rating": "Weak",
                "ai_details": json.dumps({"score": 5.0}),
            },
            reason="Different role duplicate",
        ) if False else None
        # Use a same-workspace second job for the role-specific score test.
        with engine.begin() as connection:
            second_job = int(
                connection.execute(
                    insert(Job.__table__)
                    .values(
                        workspace_id=w1,
                        title=f"Second Role {suffix}",
                        department="Engineering",
                        location="Chennai",
                        jd="Python",
                        status="Open",
                        created_at="2026-09-14T00:00:00",
                    )
                    .returning(Job.__table__.c.id)
                ).scalar_one()
            )
        repo1.upsert(
            {
                "email": "candidate.one@example.com",
                "phone": "9876543210",
                "job_id": second_job,
                "stage": "Applied",
                "ai_score": 5.0,
                "rating": "Weak",
                "ai_details": json.dumps({"score": 5.0}),
            },
            reason="Different role duplicate",
        )
        with engine.connect() as connection:
            row = connection.execute(
                select(candidates).where(candidates.c.id == candidate_id)
            ).mappings().one()
            assert row["job_id"] == job1
            assert row["ai_score"] == 88.0
            assert row["rating"] == "Strong"

        # Terminal pipeline stages must not regress.
        repo1.upsert(
            {"email": "candidate.one@example.com", "job_id": job1, "stage": "Hired"},
            reason="Hire candidate",
        )
        repo1.upsert(
            {"email": "candidate.one@example.com", "job_id": job1, "stage": "Applied"},
            reason="Stale pipeline replay",
        )
        with engine.connect() as connection:
            stage = connection.execute(
                select(candidates.c.stage).where(candidates.c.id == candidate_id)
            ).scalar_one()
            assert stage == "Hired"

        # Conflicting identity evidence must never choose an arbitrary candidate.
        first = repo1.upsert(
            {
                "name": "Conflict Email Owner",
                "email": f"conflict-a-{suffix}@example.com",
                "phone": "9000000001",
                "stage": "Applied",
            }
        )
        second = repo1.upsert(
            {
                "name": "Conflict Phone Owner",
                "email": f"conflict-b-{suffix}@example.com",
                "phone": "9000000002",
                "stage": "Applied",
            }
        )
        assert first["id"] != second["id"]
        try:
            repo1.upsert(
                {
                    "name": "Ambiguous Candidate",
                    "email": f"conflict-a-{suffix}@example.com",
                    "phone": "9000000002",
                    "stage": "Applied",
                }
            )
            raise AssertionError("Conflicting identities should require manual review")
        except CandidateIdentityConflict:
            pass

        with engine.connect() as connection:
            count = int(
                connection.execute(
                    select(func.count()).select_from(candidates).where(candidates.c.workspace_id == w1)
                ).scalar_one()
            )
            assert count == 3

        print("Candidate persistence repository regression OK")
    finally:
        if w1 is not None or w2 is not None:
            with engine.begin() as connection:
                ids = [value for value in (w1, w2) if value is not None]
                if ids:
                    connection.execute(delete(Workspace.__table__).where(Workspace.__table__.c.id.in_(ids)))
        engine.dispose()
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    run()
