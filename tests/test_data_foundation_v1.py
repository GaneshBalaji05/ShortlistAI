import os
import tempfile
import time

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SQLITE_PATH"] = db_path
os.environ["SHORTLISTAI_EXPOSE_RESET_LINK"] = "false"

from fastapi.testclient import TestClient

import main


def wait_for_runtime() -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        state = main.app.state
        if (
            getattr(state, "shortlistai_tenant_security", False)
            and getattr(state, "_shortlistai_final_review_installed", False)
            and getattr(state, "_shortlistai_data_foundation_installed", False)
        ):
            return
        time.sleep(0.02)
    raise AssertionError("data foundation runtime did not install")


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


def run() -> None:
    wait_for_runtime()
    try:
        with TestClient(main.app) as client:
            register(client, "foundation-one@example.test", "Foundation One")

            first = client.post(
                "/api/candidates",
                json={
                    "name": "Merge Candidate",
                    "email": "merge@example.test",
                    "phone": "",
                    "experience": 5,
                    "skills": "Python, Django",
                    "source": "Manual",
                    "stage": "Applied",
                    "profile_details": {"current_location": "Chennai"},
                },
            )
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert first_body["merged"] is False
            candidate_id = first_body["id"]

            duplicate = client.post(
                "/api/candidates",
                json={
                    "name": "Merge Candidate Updated",
                    "email": "MERGE@example.test",
                    "phone": "+91 9876543210",
                    "skills": "Python, FastAPI",
                    "source": "Referral",
                    "stage": "Contacted",
                    "profile_details": {"preferred_location": "Chennai"},
                },
            )
            assert duplicate.status_code == 200, duplicate.text
            duplicate_body = duplicate.json()
            assert duplicate_body["merged"] is True
            assert duplicate_body["id"] == candidate_id

            saved = client.get(f"/api/candidates/{candidate_id}")
            assert saved.status_code == 200, saved.text
            saved_body = saved.json()
            assert "django" in saved_body["skills"].lower()
            assert "fastapi" in saved_body["skills"].lower()
            assert saved_body["stage"] == "Contacted"
            assert saved_body["profile_details"]["preferred_location"] == "Chennai"
            assert saved_body["profile_details"]["duplicate_merge_count"] >= 1

            payload = []
            for index in range(800):
                is_java = index == 799
                payload.append(
                    {
                        "name": f"Foundation Bulk {index}",
                        "email": f"foundation-bulk-{index}@example.test",
                        "phone": "",
                        "experience": 5,
                        "skills": "Java, Spring Boot" if is_java else "Python, Django, JavaScript",
                        "resume_text": (
                            f"Foundation Bulk {index} has five years of software engineering experience. "
                            + ("Hands-on Java and Spring Boot microservices delivery. " if is_java else "Hands-on Python and Django delivery with JavaScript. ")
                            + "This profile contains enough text for identity and search regression coverage."
                        ),
                        "resume_filename": f"foundation_bulk_{index}.txt",
                        "source": "Foundation 800 Test",
                        "stage": "Applied",
                    }
                )

            bulk = client.post("/api/candidates/bulk", json=payload)
            assert bulk.status_code == 200, bulk.text
            bulk_body = bulk.json()
            assert bulk_body["received"] == 800
            assert bulk_body["created"] == 800
            assert bulk_body["merged"] == 0
            assert bulk_body["total_candidates"] == 801

            java = client.get(
                "/api/candidates",
                params={"q": 'Java AND ("Spring Boot" OR Spring)'},
            )
            assert java.status_code == 200, java.text
            java_rows = java.json()
            assert len(java_rows) == 1
            assert java_rows[0]["email"] == "foundation-bulk-799@example.test"

            profile_text = (
                "Merge Candidate Updated\n"
                "Email: merge@example.test\n"
                "Phone: +91 9876543210\n"
                "Professional Summary: Six years of Python FastAPI Django engineering experience.\n"
                "Skills: Python, FastAPI, Django, PostgreSQL, Docker.\n"
                "Current Location: Chennai. Recent work includes FastAPI APIs and Django services."
            )
            profile_upload = client.post(
                "/api/profiles/bulk",
                files=[("profiles", ("merge_candidate.txt", profile_text, "text/plain"))],
                data={"source": "Bulk Resume Test"},
            )
            assert profile_upload.status_code == 200, profile_upload.text
            profile_body = profile_upload.json()
            assert profile_body["received"] == 1
            assert profile_body["created"] == 0
            assert profile_body["merged"] == 1
            assert profile_body["failed"] == 0
            assert profile_body["total_candidates"] == 801

            health = client.get("/api/data-health")
            assert health.status_code == 200, health.text
            health_body = health.json()
            assert health_body["candidate_count"] == 801
            assert health_body["bulk_limit"] == 800
            assert health_body["journal_mode"].lower() == "wal"
            assert health_body["busy_timeout_ms"] >= 5000
            assert health_body["foreign_keys"] is True
            assert health_body["identity_count"] >= 801

            logout = client.post("/api/auth/logout", json={"token": ""})
            assert logout.status_code == 200, logout.text
            register(client, "foundation-two@example.test", "Foundation Two")
            isolated = client.get("/api/data-health")
            assert isolated.status_code == 200, isolated.text
            assert isolated.json()["candidate_count"] == 0

        print("Data foundation v1 regression passed")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
