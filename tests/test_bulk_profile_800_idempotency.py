import os
import sqlite3
import tempfile
import time

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SQLITE_PATH"] = db_path
os.environ["SHORTLISTAI_EXPOSE_RESET_LINK"] = "false"

from fastapi.testclient import TestClient

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
        if getattr(state, "_shortlistai_data_foundation_installed", False) and safe_bulk:
            return
        time.sleep(0.02)
    raise AssertionError("bulk profile integrity route did not install")


def register(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Bulk 800 Workspace",
            "email": "bulk-800@example.test",
            "password": "Secure123",
            "confirm_password": "Secure123",
            "workspace_name": "Bulk 800 Workspace",
        },
    )
    assert response.status_code == 200, response.text


def login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "bulk-800@example.test", "password": "Secure123", "remember": True},
    )
    assert response.status_code == 200, response.text


def files_for_batch():
    files = []
    for index in range(800):
        skill_text = "Java and Spring Boot" if index == 799 else "Python Django and JavaScript"
        text = (
            f"Bulk Candidate {index}\n"
            f"Email: bulk-profile-{index}@example.test\n"
            f"Professional Summary: Five years of software engineering experience using {skill_text}.\n"
            f"Skills: {skill_text}, PostgreSQL, Docker. Current project delivers production services and APIs."
        )
        files.append(("profiles", (f"bulk_profile_{index}.txt", text, "text/plain")))
    return files


def run() -> None:
    wait_for_runtime()
    try:
        with TestClient(main.app) as client:
            register(client)
            first = client.post(
                "/api/profiles/bulk",
                files=files_for_batch(),
                data={"source": "800 profile regression"},
            )
            assert first.status_code == 200, first.text[:1000]
            body = first.json()
            assert body["received"] == 800
            assert body["created"] == 800
            assert body["merged"] == 0
            assert body["skipped"] == 0
            assert body["failed"] == 0
            assert body["error_count"] == 0
            assert body["total_candidates"] == 800

            retry = client.post(
                "/api/profiles/bulk",
                files=files_for_batch(),
                data={"source": "800 profile regression retry"},
            )
            assert retry.status_code == 200, retry.text[:1000]
            retry_body = retry.json()
            assert retry_body["received"] == 800
            assert retry_body["created"] == 0
            assert retry_body["merged"] == 800
            assert retry_body["skipped"] == 0
            assert retry_body["failed"] == 0
            assert retry_body["total_candidates"] == 800

            java = client.get(
                "/api/candidates",
                params={"q": 'Java AND ("Spring Boot" OR Spring) NOT Python'},
            )
            assert java.status_code == 200, java.text
            java_rows = java.json()
            assert len(java_rows) == 1
            assert java_rows[0]["email"] == "bulk-profile-799@example.test"

            javascript_only = client.get("/api/candidates", params={"q": "Java"})
            assert javascript_only.status_code == 200, javascript_only.text
            java_emails = {(row.get("email") or "").lower() for row in javascript_only.json()}
            assert java_emails == {"bulk-profile-799@example.test"}, "Java matched JavaScript-only candidates"

        raw = sqlite3.connect(db_path)
        try:
            persisted = raw.execute(
                "SELECT COUNT(*) FROM candidates WHERE email LIKE 'bulk-profile-%@example.test'"
            ).fetchone()[0]
            assert persisted == 800, f"expected 800 persisted profiles after connection restart, found {persisted}"
        finally:
            raw.close()

        with TestClient(main.app) as restarted_client:
            login(restarted_client)
            health = restarted_client.get("/api/data-health")
            assert health.status_code == 200, health.text
            assert health.json()["candidate_count"] == 800
            sample = restarted_client.get("/api/candidates", params={"q": '"Bulk Candidate 400"'})
            assert sample.status_code == 200, sample.text
            assert any((row.get("email") or "") == "bulk-profile-400@example.test" for row in sample.json())

        print("800 profile ingestion/idempotency/persistence regression passed")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
