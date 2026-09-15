import os
import tempfile
import uuid

from sqlalchemy import delete, insert, select

import tenant_security
from shortlistai.api.v1 import CandidateCreateIn, router
from shortlistai.db.models import ActivityLog, Base, Candidate, CandidateIdentity, Job, Workspace
from shortlistai.db.runtime import create_database_engine


def endpoint(path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Missing route {method} {path}")


def _exercise(database_url: str) -> None:
    engine = create_database_engine(database_url)
    if database_url.startswith("sqlite:///"):
        Base.metadata.create_all(engine)

    suffix = uuid.uuid4().hex[:10]
    workspace_ids: list[int] = []
    try:
        with engine.begin() as connection:
            workspace_one = int(
                connection.execute(
                    insert(Workspace.__table__).values(
                        name=f"Candidate Route One {suffix}", created_at="2026-09-15T00:00:00Z"
                    )
                ).inserted_primary_key[0]
            )
            workspace_two = int(
                connection.execute(
                    insert(Workspace.__table__).values(
                        name=f"Candidate Route Two {suffix}", created_at="2026-09-15T00:00:00Z"
                    )
                ).inserted_primary_key[0]
            )
            workspace_ids.extend([workspace_one, workspace_two])
            job_one = int(
                connection.execute(
                    insert(Job.__table__).values(
                        workspace_id=workspace_one,
                        title="Java Engineer",
                        department="Engineering",
                        location="Chennai",
                        jd="Build Java and Spring Boot services for the recruitment platform.",
                        status="Open",
                        created_at="2026-09-15T00:00:00Z",
                    )
                ).inserted_primary_key[0]
            )
            job_two = int(
                connection.execute(
                    insert(Job.__table__).values(
                        workspace_id=workspace_two,
                        title="Python Engineer",
                        department="Platform",
                        location="Bengaluru",
                        jd="Build Python and FastAPI services for the recruitment platform.",
                        status="Open",
                        created_at="2026-09-15T00:00:00Z",
                    )
                ).inserted_primary_key[0]
            )

        create = endpoint("/api/v1/candidates", "POST")
        token = tenant_security._workspace.set(workspace_one)
        try:
            payload = CandidateCreateIn(
                name="Candidate One",
                email=f"candidate-{suffix}@example.com",
                phone="+91 98765 43210",
                experience=5.5,
                skills="Java, Spring Boot",
                resume_text=("Java Spring Boot microservices " * 8).strip(),
                source="Route regression",
                job_id=job_one,
                stage="Sourced",
            )
            first = create(payload)
            candidate_id = int(first["data"]["id"])
            assert first["data"]["merged"] is False
            assert "Java" in first["data"]["talent_pools"]

            # Same authenticated workspace + same identity must merge atomically, not duplicate.
            merged = create(
                CandidateCreateIn(
                    name="Candidate One",
                    email=f"candidate-{suffix}@example.com",
                    skills="Java, Spring Boot, Kafka",
                    source="Duplicate route regression",
                    job_id=job_one,
                    stage="Screened",
                )
            )
            assert int(merged["data"]["id"]) == candidate_id
            assert merged["data"]["merged"] is True

            # A job owned by another workspace must be indistinguishable from a missing job.
            try:
                create(
                    CandidateCreateIn(
                        name="Foreign Job Candidate",
                        email=f"foreign-{suffix}@example.com",
                        job_id=job_two,
                        stage="Sourced",
                    )
                )
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 404
                assert getattr(exc, "detail", None) == "Job not found"
            else:
                raise AssertionError("Cross-workspace candidate job reference was accepted")

            # Preserve legacy stage validation: unknown stage values must fail, not become Applied.
            try:
                create(
                    CandidateCreateIn(
                        name="Invalid Stage Candidate",
                        email=f"invalid-stage-{suffix}@example.com",
                        stage="RandomStage",
                    )
                )
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 400
                assert getattr(exc, "detail", None) == "Invalid stage"
            else:
                raise AssertionError("Unknown candidate stage was silently accepted")
        finally:
            tenant_security._workspace.reset(token)

        with engine.connect() as connection:
            rows = connection.execute(
                select(Candidate.__table__).where(Candidate.__table__.c.workspace_id == workspace_one)
            ).mappings().all()
            assert len(rows) == 1
            row = dict(rows[0])
            assert int(row["id"]) == candidate_id
            assert int(row["workspace_id"]) == workspace_one
            assert int(row["job_id"]) == job_one
            assert "Kafka" in str(row["skills"])
            assert row["stage"] != "Dropped"

            identities = connection.execute(
                select(CandidateIdentity.__table__).where(
                    CandidateIdentity.__table__.c.workspace_id == workspace_one
                )
            ).mappings().all()
            assert identities
            activities = connection.execute(
                select(ActivityLog.__table__).where(ActivityLog.__table__.c.workspace_id == workspace_one)
            ).mappings().all()
            assert len(activities) >= 2

            foreign_rows = connection.execute(
                select(Candidate.__table__.c.id).where(
                    Candidate.__table__.c.workspace_id == workspace_two
                )
            ).all()
            assert foreign_rows == []
    finally:
        if workspace_ids:
            with engine.begin() as connection:
                for wid in workspace_ids:
                    candidate_ids = [
                        int(row[0])
                        for row in connection.execute(
                            select(Candidate.__table__.c.id).where(
                                Candidate.__table__.c.workspace_id == wid
                            )
                        ).all()
                    ]
                    if candidate_ids:
                        connection.execute(
                            delete(CandidateIdentity.__table__).where(
                                CandidateIdentity.__table__.c.workspace_id == wid
                            )
                        )
                        connection.execute(
                            delete(ActivityLog.__table__).where(
                                ActivityLog.__table__.c.workspace_id == wid
                            )
                        )
                        connection.execute(
                            delete(Candidate.__table__).where(Candidate.__table__.c.workspace_id == wid)
                        )
                    connection.execute(delete(Job.__table__).where(Job.__table__.c.workspace_id == wid))
                    connection.execute(delete(Workspace.__table__).where(Workspace.__table__.c.id == wid))
        engine.dispose()


def run() -> None:
    configured = os.environ.get("DATABASE_URL", "").strip()
    if configured:
        _exercise(configured)
        print("API v1 candidate create route PostgreSQL regression passed")
        return

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database_url = f"sqlite:///{path}"
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        _exercise(database_url)
        print("API v1 candidate create route SQLite regression passed")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    run()
