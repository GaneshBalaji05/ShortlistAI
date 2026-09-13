from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete, insert, select

from shortlistai.db.models import Base
from shortlistai.db.repositories import RepositoryNotFound
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url
from shortlistai.services.candidate_persistence import CandidatePersistenceService


class LegacySemantics:
    STAGES = ["Sourced", "Screened", "Interview", "Offered", "Joined", "Rejected"]

    @staticmethod
    def encode_talent_pools(values):
        return json.dumps(list(values or []), ensure_ascii=False)

    @staticmethod
    def decode_talent_pools(value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []


def make_engine():
    configured = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if is_postgres_url(configured):
        return create_database_engine(configured), None
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "candidate-persistence.db"
    engine = create_database_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine, directory


def candidate_payload(index: int, *, job_id: int, suffix: str) -> dict:
    return {
        "name": f"Bulk Candidate {index}",
        "email": f"bulk-{suffix}-{index}@example.test",
        "phone": f"90000{index:05d}",
        "experience": float(index % 12),
        "skills": "Python, FastAPI",
        "resume_text": (
            f"Bulk candidate {index} has Python FastAPI backend experience, SQL, testing and delivery. "
            "This text is intentionally long enough to generate a stable resume identity for persistence tests."
        ),
        "resume_filename": f"candidate-{index}.txt",
        "source": "800 profile regression",
        "notice_period": "30 days",
        "current_ctc": "",
        "expected_ctc": "",
        "profile_details": {"current_location": "Chennai"},
        "talent_pools": ["Backend"],
        "job_id": job_id,
        "stage": "Sourced",
    }


def main() -> None:
    engine, temporary = make_engine()
    suffix = uuid.uuid4().hex[:10]
    tables = Base.metadata.tables
    workspaces = tables["workspaces"]
    jobs = tables["jobs"]
    candidates = tables["candidates"]
    identities = tables["candidate_identities"]
    activity = tables["activity_log"]
    created_workspace_ids: list[int] = []

    try:
        with engine.begin() as connection:
            w1 = int(connection.execute(
                insert(workspaces).values(name=f"Candidate Service One {suffix}", created_at="2026-09-14").returning(workspaces.c.id)
            ).scalar_one())
            w2 = int(connection.execute(
                insert(workspaces).values(name=f"Candidate Service Two {suffix}", created_at="2026-09-14").returning(workspaces.c.id)
            ).scalar_one())
            created_workspace_ids.extend([w1, w2])
            job1 = int(connection.execute(
                insert(jobs).values(workspace_id=w1, title="Python Role", jd="Python FastAPI", status="Open", created_at="2026-09-14").returning(jobs.c.id)
            ).scalar_one())
            job1_alt = int(connection.execute(
                insert(jobs).values(workspace_id=w1, title="Data Role", jd="Python Pandas", status="Open", created_at="2026-09-14").returning(jobs.c.id)
            ).scalar_one())
            job2 = int(connection.execute(
                insert(jobs).values(workspace_id=w2, title="Python Role Two", jd="Python FastAPI", status="Open", created_at="2026-09-14").returning(jobs.c.id)
            ).scalar_one())

        service1 = CandidatePersistenceService(engine, w1, LegacySemantics())
        service2 = CandidatePersistenceService(engine, w2, LegacySemantics())

        original = service1.upsert(
            {
                "name": "Stable Candidate",
                "email": f"same-{suffix}@example.test",
                "phone": "+91 98765 43210",
                "experience": 5.0,
                "skills": "Python",
                "resume_text": "Python engineer with production APIs. " * 4,
                "resume_filename": "old.txt",
                "source": "Manual",
                "profile_details": {"current_location": "Chennai"},
                "talent_pools": ["Backend"],
                "job_id": job1,
                "stage": "Sourced",
                "ai_score": 61.0,
                "rating": "Average",
                "ai_details": json.dumps({"score": 61, "rating": "Average"}),
            },
            "Initial create",
        )
        assert original["merged"] is False

        other_workspace = service2.upsert(
            {
                "name": "Same Identity Different Workspace",
                "email": f"same-{suffix}@example.test",
                "phone": "+91 98765 43210",
                "skills": "Python",
                "resume_text": "Different workspace profile. " * 5,
                "profile_details": {},
                "talent_pools": ["Backend"],
                "job_id": job2,
                "stage": "Sourced",
            },
            "Cross workspace control",
        )
        assert other_workspace["merged"] is False
        assert other_workspace["id"] != original["id"]

        merged = service1.upsert(
            {
                "name": "Incoming Duplicate Name",
                "email": f"same-{suffix}@example.test",
                "phone": "9876543210",
                "experience": 7.0,
                "skills": "FastAPI, PostgreSQL",
                "resume_text": "Longer Python FastAPI PostgreSQL production resume with delivery evidence. " * 8,
                "resume_filename": "new.txt",
                "source": "Resume upload",
                "notice_period": "15 days",
                "profile_details": {"preferred_location": "Remote"},
                "talent_pools": ["Platform"],
                "job_id": job1,
                "stage": "Screened",
                "ai_score": 82.0,
                "rating": "Strong",
                "ai_details": json.dumps({"score": 82, "rating": "Strong"}),
            },
            "Duplicate regression",
        )
        assert merged["merged"] is True and merged["id"] == original["id"]

        with engine.connect() as connection:
            row = dict(connection.execute(
                select(candidates).where(candidates.c.id == original["id"])
            ).mappings().one())
            assert row["name"] == "Stable Candidate", "existing non-empty recruiter data must win"
            assert row["experience"] == 5.0, "existing experience must not be overwritten"
            assert "FastAPI" in row["skills"] and "PostgreSQL" in row["skills"]
            assert row["resume_filename"] == "new.txt"
            assert row["stage"] == "Screened"
            assert row["ai_score"] == 82.0 and row["rating"] == "Strong"
            profile = json.loads(row["profile_details"])
            assert profile["current_location"] == "Chennai"
            assert profile["preferred_location"] == "Remote"
            assert profile["duplicate_merge_count"] == 1
            assert len(profile["source_history"]) == 1
            pool_values = LegacySemantics.decode_talent_pools(row["talent_pools"])
            assert pool_values == ["Backend", "Platform"]
            identity_rows = connection.execute(
                select(identities).where(
                    (identities.c.workspace_id == w1) & (identities.c.candidate_id == original["id"])
                )
            ).all()
            assert len(identity_rows) >= 2
            activity_rows = connection.execute(
                select(activity).where(
                    (activity.c.workspace_id == w1) & (activity.c.candidate_id == original["id"])
                )
            ).mappings().all()
            assert [item["action"] for item in activity_rows] == ["Candidate created", "Duplicate merged"]

        service1.upsert(
            {
                "email": f"same-{suffix}@example.test",
                "skills": "Redis",
                "resume_text": "Longer resume for another role that must not replace the prior score. " * 10,
                "profile_details": {},
                "talent_pools": [],
                "job_id": job1_alt,
                "stage": "Interview",
                "ai_score": 99.0,
                "rating": "Strong",
                "ai_details": json.dumps({"score": 99}),
            },
            "Different role score guard",
        )
        with engine.connect() as connection:
            row = connection.execute(
                select(candidates.c.job_id, candidates.c.ai_score, candidates.c.stage).where(candidates.c.id == original["id"])
            ).one()
            assert row.job_id == job1
            assert row.ai_score == 82.0, "score from a different incoming role must not overwrite current role score"
            assert row.stage == "Interview"

        try:
            service1.upsert(
                {
                    "name": "Bad Cross Workspace Job",
                    "email": f"bad-{suffix}@example.test",
                    "profile_details": {},
                    "talent_pools": [],
                    "job_id": job2,
                    "stage": "Sourced",
                },
                "Cross workspace job",
            )
            raise AssertionError("Cross-workspace job reference must be rejected")
        except RepositoryNotFound:
            pass

        bulk = service1.upsert_many(
            [candidate_payload(index, job_id=job1, suffix=suffix) for index in range(1, 801)],
            "800 profile persistence regression",
            chunk_size=50,
        )
        assert bulk["received"] == 800
        assert bulk["created"] == 800
        assert bulk["merged"] == 0
        assert len(bulk["ids"]) == 800
        assert len(set(bulk["ids"])) == 800
        assert service1.candidate_count() == 801
        assert service2.candidate_count() == 1
        assert service1.identity_count() >= 802

        print("Candidate persistence duplicate/isolation/scoring/800-ingestion regression OK")
    finally:
        if created_workspace_ids:
            # Explicit child cleanup keeps this deterministic even if SQLite FK enforcement
            # differs by environment.
            with engine.begin() as connection:
                for table_name in ("candidate_identities", "activity_log", "notes", "interviews"):
                    table = tables[table_name]
                    connection.execute(delete(table).where(table.c.workspace_id.in_(created_workspace_ids)))
                connection.execute(delete(candidates).where(candidates.c.workspace_id.in_(created_workspace_ids)))
                connection.execute(delete(jobs).where(jobs.c.workspace_id.in_(created_workspace_ids)))
                connection.execute(delete(workspaces).where(workspaces.c.id.in_(created_workspace_ids)))
        engine.dispose()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
