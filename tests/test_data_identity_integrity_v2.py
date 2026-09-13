import os
import tempfile
import time

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SQLITE_PATH"] = db_path
os.environ["SHORTLISTAI_EXPOSE_RESET_LINK"] = "false"

from fastapi.testclient import TestClient

import data_foundation
import main


def wait_for_runtime() -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        state = main.app.state
        safe_bulk = any(
            getattr(route, "path", None) == "/api/profiles/bulk"
            and "POST" in (getattr(route, "methods", set()) or set())
            and getattr(getattr(route, "endpoint", None), "__name__", "") == "bulk_profiles_integrity_v2"
            for route in main.app.routes
        )
        if (
            getattr(state, "shortlistai_tenant_security", False)
            and getattr(state, "_shortlistai_final_review_installed", False)
            and getattr(state, "_shortlistai_data_foundation_installed", False)
            and safe_bulk
        ):
            return
        time.sleep(0.02)
    raise AssertionError("data integrity v2 runtime did not install")


def register(client: TestClient, email: str, workspace: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": workspace,
            "email": email,
            "password": "Secure123",
            "confirm_password": "Secure123",
            "workspace_name": workspace,
        },
    )
    assert response.status_code == 200, response.text


def create_candidate(client: TestClient, **overrides):
    payload = {
        "name": "Identity Candidate",
        "email": "",
        "phone": "",
        "experience": 5,
        "skills": "Python",
        "source": "Identity regression",
        "stage": "Applied",
        "profile_details": {},
    }
    payload.update(overrides)
    return client.post("/api/candidates", json=payload)


def run() -> None:
    wait_for_runtime()
    try:
        with TestClient(main.app) as client:
            register(client, "identity-one@example.test", "Identity One")

            first = create_candidate(
                client,
                name="Alpha",
                email="Alpha@Example.Test",
                phone="+91 90000 00001",
                profile_details={"linkedin_id": "https://www.linkedin.com/in/Alpha-Engineer/"},
            )
            assert first.status_code == 200, first.text
            alpha_id = first.json()["id"]
            assert first.json()["merged"] is False

            same_email = create_candidate(client, name="Alpha Case", email="alpha@example.test")
            assert same_email.status_code == 200, same_email.text
            assert same_email.json()["merged"] is True
            assert same_email.json()["id"] == alpha_id

            same_phone = create_candidate(client, name="Alpha Phone", phone="9000000001")
            assert same_phone.status_code == 200, same_phone.text
            assert same_phone.json()["merged"] is True
            assert same_phone.json()["id"] == alpha_id

            same_linkedin = create_candidate(
                client,
                name="Alpha LinkedIn",
                profile_details={"linkedin_url": "linkedin.com/in/alpha-engineer?trk=public_profile"},
            )
            assert same_linkedin.status_code == 200, same_linkedin.text
            assert same_linkedin.json()["merged"] is True
            assert same_linkedin.json()["id"] == alpha_id

            partial = create_candidate(client, name="Partial", email="partial@example.test")
            assert partial.status_code == 200, partial.text
            partial_id = partial.json()["id"]
            partial_add_phone = create_candidate(
                client,
                name="Partial Enriched",
                email="PARTIAL@example.test",
                phone="+91 98888 00000",
            )
            assert partial_add_phone.status_code == 200, partial_add_phone.text
            assert partial_add_phone.json()["id"] == partial_id
            phone_only = create_candidate(client, name="Partial Phone Only", phone="9888800000")
            assert phone_only.status_code == 200, phone_only.text
            assert phone_only.json()["id"] == partial_id

            beta = create_candidate(
                client,
                name="Beta",
                email="beta@example.test",
                phone="9000000002",
                profile_details={"linkedin_id": "https://linkedin.com/in/beta-engineer"},
            )
            assert beta.status_code == 200, beta.text
            beta_id = beta.json()["id"]

            conflict = create_candidate(
                client,
                name="Conflict Must Not Merge",
                email="alpha@example.test",
                phone="9000000002",
            )
            assert conflict.status_code == 409, conflict.text
            assert "manual review" in conflict.json()["detail"].lower()

            alpha_saved = client.get(f"/api/candidates/{alpha_id}")
            beta_saved = client.get(f"/api/candidates/{beta_id}")
            assert alpha_saved.status_code == 200 and beta_saved.status_code == 200
            assert alpha_saved.json()["phone"].replace(" ", "").endswith("00001")
            assert beta_saved.json()["email"].lower() == "beta@example.test"

            original_refresh = data_foundation._refresh_identities

            def fail_after_write(con, candidate_id: int):
                row = con.execute("SELECT email FROM candidates WHERE id=?", (candidate_id,)).fetchone()
                if row and (row["email"] or "").lower() == "fail-savepoint@example.test":
                    raise RuntimeError("forced post-write identity failure")
                return original_refresh(con, candidate_id)

            data_foundation._refresh_identities = fail_after_write
            try:
                failed_profile = (
                    "Fail Savepoint\nEmail: fail-savepoint@example.test\n"
                    "Professional Summary: Five years of Python FastAPI backend engineering experience.\n"
                    "Skills: Python, FastAPI, PostgreSQL, Docker. Recent work includes reliable API services."
                )
                good_profile = (
                    "Good Savepoint\nEmail: good-savepoint@example.test\n"
                    "Professional Summary: Five years of Python Django backend engineering experience.\n"
                    "Skills: Python, Django, PostgreSQL, Docker. Recent work includes reliable web services."
                )
                bulk = client.post(
                    "/api/profiles/bulk",
                    files=[
                        ("profiles", ("fail.txt", failed_profile, "text/plain")),
                        ("profiles", ("good.txt", good_profile, "text/plain")),
                    ],
                    data={"source": "Savepoint regression"},
                )
            finally:
                data_foundation._refresh_identities = original_refresh

            assert bulk.status_code == 200, bulk.text
            body = bulk.json()
            assert body["received"] == 2
            assert body["created"] == 1
            assert body["merged"] == 0
            assert body["skipped"] == 0
            assert body["failed"] == 1
            assert body["error_count"] == 1
            rows = client.get("/api/candidates").json()
            emails = {(row.get("email") or "").lower() for row in rows}
            assert "fail-savepoint@example.test" not in emails, "failed item leaked a partial candidate write"
            assert "good-savepoint@example.test" in emails

            logout = client.post("/api/auth/logout", json={"token": ""})
            assert logout.status_code == 200, logout.text
            register(client, "identity-two@example.test", "Identity Two")
            cross_workspace = create_candidate(
                client,
                name="Workspace Two Alpha",
                email="ALPHA@example.test",
                phone="+91 90000 00001",
                profile_details={"linkedin_id": "https://www.linkedin.com/in/alpha-engineer"},
            )
            assert cross_workspace.status_code == 200, cross_workspace.text
            assert cross_workspace.json()["merged"] is False
            health = client.get("/api/data-health")
            assert health.status_code == 200, health.text
            assert health.json()["candidate_count"] == 1

        print("Data identity integrity v2 regression passed")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
