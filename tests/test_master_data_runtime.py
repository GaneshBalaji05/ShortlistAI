import base64
import bz2
import hashlib
import json
import os
import tempfile
import time

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SQLITE_PATH"] = db_path
os.environ["SHORTLISTAI_EXPOSE_RESET_LINK"] = "false"

rows = [
    ["1", "RH-001", "Java Candidate", "9000000001", "java@example.test", "Java SpringBoot", "6 Years", "5 Years", "Example One", "10 LPA", "14 LPA", "Chennai", "Chennai", "30 Days", ""],
    ["2", "", "JavaScript Candidate", "9000000002", "javascript@example.test", "React JS / JavaScript", "5 Years", "4 Years", "Example Two", "9 LPA", "13 LPA", "Bangalore", "Chennai", "Immediate", ""],
    ["3", "", "Python Candidate", "9000000003", "python@example.test", "Python developer", "4 Years", "4 Years", "Example Three", "8 LPA", "12 LPA", "Hyderabad", "Bangalore", "15 Days", ""],
]
raw = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
encoded = base64.b64encode(bz2.compress(raw)).decode("ascii")
os.environ.update({
    "SHORTLISTAI_MASTER_DATA_ENABLED": "true",
    "SHORTLISTAI_MASTER_DATA_CHUNK_COUNT": "1",
    "SHORTLISTAI_MASTER_DATA_001": encoded,
    "SHORTLISTAI_MASTER_DATA_SHA256": hashlib.sha256(raw).hexdigest(),
    "SHORTLISTAI_MASTER_DATA_EXPECTED_COUNT": str(len(rows)),
    "SHORTLISTAI_MASTER_DATA_VERSION": "ci-master-data-v1",
    "SHORTLISTAI_MASTER_QA_EMAIL": "master-data-ci@example.test",
    "SHORTLISTAI_MASTER_QA_PASSWORD": "MasterData123!",
    "SHORTLISTAI_MASTER_QA_WORKSPACE": "Master Data CI",
})

from fastapi.testclient import TestClient

import main
from master_data_runtime import seed_master_data_from_env


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
    raise AssertionError("secured runtime did not install")


def run() -> None:
    wait_for_runtime()
    try:
        with TestClient(main.app) as client:
            login = client.post(
                "/api/auth/login",
                json={"email": "master-data-ci@example.test", "password": "MasterData123!", "remember": True},
            )
            assert login.status_code == 200, login.text

            all_rows = client.get("/api/candidates")
            assert all_rows.status_code == 200, all_rows.text
            body = all_rows.json()
            assert len(body) == 3, len(body)

            by_name = {item["name"]: item for item in body}
            assert by_name["JavaScript Candidate"]["profile_details"]["rhid"] == ""
            assert by_name["Java Candidate"]["profile_details"]["rhid"] == "RH-001"
            assert by_name["Java Candidate"]["profile_details"]["sheet2"]["Resource Name"] == "Java Candidate"

            java = client.get("/api/candidates", params={"q": "Java"})
            assert java.status_code == 200, java.text
            java_rows = java.json()
            assert [item["name"] for item in java_rows] == ["Java Candidate"], java_rows

            boolean = client.get("/api/candidates", params={"q": 'Java AND (SpringBoot OR Spring)'})
            assert boolean.status_code == 200, boolean.text
            assert [item["name"] for item in boolean.json()] == ["Java Candidate"]

            react = client.get("/api/candidates", params={"q": "React"})
            assert react.status_code == 200, react.text
            assert [item["name"] for item in react.json()] == ["JavaScript Candidate"]

            chennai = client.get("/api/candidates", params={"location": "Chennai"})
            assert chennai.status_code == 200, chennai.text
            assert {item["name"] for item in chennai.json()} == {"Java Candidate", "JavaScript Candidate"}

            second_seed = seed_master_data_from_env(db_path)
            assert second_seed is not None and second_seed["seeded"] is False, second_seed
            assert second_seed["count"] == 3

            register = client.post(
                "/api/auth/register",
                json={
                    "full_name": "Other Workspace",
                    "email": "other-master-data@example.test",
                    "password": "Secure123!",
                    "confirm_password": "Secure123!",
                    "workspace_name": "Other Master Data Workspace",
                },
            )
            assert register.status_code == 200, register.text
            isolated = client.get("/api/candidates")
            assert isolated.status_code == 200, isolated.text
            assert isolated.json() == [], isolated.json()

        print("Master data runtime regression passed")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
