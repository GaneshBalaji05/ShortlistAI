from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete

from shortlistai.db.models import Base
from shortlistai.db.repositories import (
    AuthRepository,
    RepositoryConflict,
    RepositoryNotFound,
    WorkspaceRepository,
)
from shortlistai.db.runtime import create_database_engine, is_postgres_url, normalize_database_url


def _engine():
    configured = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if is_postgres_url(configured):
        return create_database_engine(configured), None
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "repository-layer.db"
    engine = create_database_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine, directory


def main() -> None:
    engine, temporary = _engine()
    suffix = uuid.uuid4().hex[:10]
    email1 = f"repo-one-{suffix}@example.test"
    email2 = f"repo-two-{suffix}@example.test"
    auth = AuthRepository(engine)

    try:
        w1, u1 = auth.create_workspace_user(
            workspace_name=f"Repository Workspace One {suffix}",
            full_name="Repository Admin One",
            email=email1,
            password_hash="hash-one",
            password_salt="salt-one",
            role="Workspace Admin",
            created_at="2026-09-14T00:00:00Z",
            last_login_at=None,
        )
        w2, u2 = auth.create_workspace_user(
            workspace_name=f"Repository Workspace Two {suffix}",
            full_name="Repository Admin Two",
            email=email2,
            password_hash="hash-two",
            password_salt="salt-two",
            role="Workspace Admin",
            created_at="2026-09-14T00:00:00Z",
            last_login_at=None,
        )

        assert auth.get_user_by_email(email1.upper())["id"] == u1
        assert auth.get_user(u2)["workspace_id"] == w2
        assert auth.get_workspace(w1)["name"].startswith("Repository Workspace One")

        auth.create_session(
            token_hash=f"session-{suffix}",
            user_id=u1,
            created_at="2026-09-14T00:00:00Z",
            expires_at="2099-09-14T00:00:00Z",
        )
        session = auth.get_session_user(f"session-{suffix}")
        assert session and session["workspace_id"] == w1 and session["email"] == email1

        repo1 = WorkspaceRepository(engine, w1)
        repo2 = WorkspaceRepository(engine, w2)

        job1 = repo1.create_row(
            "jobs",
            {
                "title": "Workspace One Role",
                "jd": "Python FastAPI",
                "status": "Open",
                "created_at": "2026-09-14T00:00:00Z",
            },
        )
        job2 = repo2.create_row(
            "jobs",
            {
                "title": "Workspace Two Role",
                "jd": "Java Spring",
                "status": "Open",
                "created_at": "2026-09-14T00:00:00Z",
            },
        )

        candidate1 = repo1.create_row(
            "candidates",
            {
                "name": "Candidate One",
                "email": f"candidate-{suffix}@example.test",
                "job_id": job1,
                "stage": "Applied",
                "created_at": "2026-09-14T00:00:00Z",
                "updated_at": "2026-09-14T00:00:00Z",
            },
        )

        try:
            repo1.create_row(
                "candidates",
                {
                    "name": "Cross Workspace Candidate",
                    "job_id": job2,
                    "stage": "Applied",
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
            )
            raise AssertionError("Cross-workspace job reference should be rejected")
        except RepositoryNotFound:
            pass

        note_id = repo1.create_row(
            "notes",
            {
                "candidate_id": candidate1,
                "note": "Repository note",
                "created_at": "2026-09-14T00:00:00Z",
            },
        )
        activity_id = repo1.create_row(
            "activity_log",
            {
                "candidate_id": candidate1,
                "action": "Created",
                "details": "Repository test",
                "created_at": "2026-09-14T00:00:00Z",
            },
        )
        interview_id = repo1.create_row(
            "interviews",
            {
                "candidate_id": candidate1,
                "job_id": job1,
                "round_name": "L1",
                "interviewer_name": "Interviewer",
                "interviewer_email": "interviewer@example.test",
                "scheduled_at": "2026-09-15T10:00:00+05:30",
                "timezone": "Asia/Kolkata",
                "duration_minutes": 45,
                "meeting_url": "",
                "status": "Scheduled",
                "outcome": "Pending",
                "notes": "",
                "created_at": "2026-09-14T00:00:00Z",
                "updated_at": "2026-09-14T00:00:00Z",
            },
        )

        assert repo1.get_row("notes", note_id)["candidate_id"] == candidate1
        assert repo1.get_row("activity_log", activity_id)["candidate_id"] == candidate1
        assert repo1.get_row("interviews", interview_id)["job_id"] == job1
        assert repo2.get_row("candidates", candidate1) is None

        repo1.replace_candidate_identities(
            candidate1,
            [("email", f"candidate-{suffix}@example.test"), ("phone", "+919999999999")],
            created_at="2026-09-14T00:00:00Z",
        )
        assert repo1.find_candidate_by_identity("phone", "+919999999999") == candidate1
        assert len(repo1.list_candidate_identities(candidate1)) == 2
        assert repo2.find_candidate_by_identity("phone", "+919999999999") is None

        candidate2 = repo1.create_row(
            "candidates",
            {
                "name": "Candidate Two",
                "stage": "Applied",
                "created_at": "2026-09-14T00:00:00Z",
                "updated_at": "2026-09-14T00:00:00Z",
            },
        )
        try:
            repo1.replace_candidate_identities(
                candidate2,
                [("phone", "+919999999999")],
                created_at="2026-09-14T00:00:00Z",
            )
            raise AssertionError("Identity ownership conflict should be rejected")
        except RepositoryConflict:
            pass

        jobs, candidates = repo1.dashboard_rows()
        assert {row["id"] for row in jobs} == {job1}
        assert candidate1 in {row["id"] for row in candidates}
        interviews = repo1.list_interviews(candidate_id=candidate1)
        assert len(interviews) == 1 and interviews[0]["id"] == interview_id
        assert interviews[0]["candidate_name"] == "Candidate One"

        auth.replace_password_reset(
            user_id=u1,
            token_hash=f"reset-{suffix}",
            created_at="2026-09-14T00:00:00Z",
            expires_at="2099-09-14T00:00:00Z",
        )
        reset = auth.get_password_reset(f"reset-{suffix}")
        assert reset and reset["user_id"] == u1
        auth.reset_password(
            token_hash=f"reset-{suffix}",
            user_id=u1,
            password_hash="new-hash",
            password_salt="new-salt",
            used_at="2026-09-14T01:00:00Z",
        )
        assert auth.get_user(u1)["password_hash"] == "new-hash"
        assert auth.get_session_user(f"session-{suffix}") is None

        print("Repository layer auth/workspace isolation OK")
    finally:
        if is_postgres_url(normalize_database_url(os.getenv("DATABASE_URL", ""))):
            workspaces = Base.metadata.tables["workspaces"]
            with engine.begin() as connection:
                connection.execute(delete(workspaces).where(workspaces.c.id.in_([w1, w2])))
        engine.dispose()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
