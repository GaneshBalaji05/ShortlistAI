from __future__ import annotations

import os

from sqlalchemy import text

from shortlistai.db.repositories import WorkspaceRepository
from shortlistai.db.runtime import create_database_engine


def main() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        w1 = connection.execute(
            text("INSERT INTO workspaces(name,created_at) VALUES('Workspace One','2026-09-14') RETURNING id")
        ).scalar_one()
        w2 = connection.execute(
            text("INSERT INTO workspaces(name,created_at) VALUES('Workspace Two','2026-09-14') RETURNING id")
        ).scalar_one()

    repo1 = WorkspaceRepository(engine, int(w1))
    repo2 = WorkspaceRepository(engine, int(w2))

    job1 = repo1.create_row(
        "jobs",
        {"title": "Workspace One Role", "jd": "Python", "status": "Open", "created_at": "2026-09-14"},
    )
    job2 = repo2.create_row(
        "jobs",
        {"title": "Workspace Two Role", "jd": "Java", "status": "Open", "created_at": "2026-09-14"},
    )

    assert repo1.get_row("jobs", job1)["title"] == "Workspace One Role"
    assert repo1.get_row("jobs", job2) is None
    assert repo2.get_row("jobs", job1) is None

    assert {row["id"] for row in repo1.list_rows("jobs")} == {job1}
    assert {row["id"] for row in repo2.list_rows("jobs")} == {job2}

    assert repo1.update_row("jobs", job2, {"title": "Cross tenant mutation"}) is False
    assert repo1.delete_row("jobs", job2) is False
    assert repo2.get_row("jobs", job2)["title"] == "Workspace Two Role"

    try:
        repo1.create_row(
            "jobs",
            {
                "workspace_id": int(w2),
                "title": "Bad Insert",
                "jd": "Should fail",
                "status": "Open",
                "created_at": "2026-09-14",
            },
        )
        raise AssertionError("Cross-workspace insert should have failed")
    except ValueError as exc:
        assert "Cross-workspace" in str(exc)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM jobs WHERE workspace_id IN (:w1,:w2)"), {"w1": w1, "w2": w2})
        connection.execute(text("DELETE FROM workspaces WHERE id IN (:w1,:w2)"), {"w1": w1, "w2": w2})
    engine.dispose()
    print("Workspace repository isolation OK")


if __name__ == "__main__":
    main()
