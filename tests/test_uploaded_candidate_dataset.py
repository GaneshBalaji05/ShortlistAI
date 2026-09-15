import os
import re
import tempfile
import time
from pathlib import Path

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SQLITE_PATH"] = db_path
os.environ["SHORTLISTAI_EXPOSE_RESET_LINK"] = "false"

from fastapi.testclient import TestClient

import main


# Privacy-safe aggregate patterns derived from the candidate records supplied for QA.
# No candidate names, email addresses, phone numbers, RHIDs, employers, or actual CTC values are stored.
SKILL_COUNTS = {'Devops Engineer': 8,
 '.Net & Web Api': 1,
 'L1 support Engineer': 7,
 'Sql Server': 2,
 'Andriod Developer': 1,
 'RPA developer': 4,
 'PHP Developer': 2,
 'Cognos Bi': 2,
 '.NET Core': 1,
 'Data Migration': 3,
 'Mainframe Assembler': 1,
 'SFDC': 36,
 'Angular JS': 1,
 'REACT JS': 1,
 'SAS Devloper': 4,
 'SAP consultant': 1,
 'Firmware Test Engineer': 2,
 'SAP BASIS': 3,
 'Test Automation': 1,
 'BDD cucumber': 2,
 'Java SpringBoot': 2,
 'UI REAC JS': 3,
 'Angular Lead': 2,
 'SFMC': 3,
 'BA': 9,
 'Service now': 1,
 'service now': 6,
 'DBA': 5,
 'Azure devops PowerShell': 4,
 'Network Engineer': 11,
 'MS CRM Sr. Developer': 1,
 'Java Full Stack Developer': 7,
 'AWS Architect': 2,
 'React JS': 2,
 'Java Microservices': 7,
 'IOS Developer': 2,
 'Python developer': 1,
 'Devops': 3,
 'Mainframe Developer': 1,
 'Postgre Sql': 2,
 'AWS Cloud engineer': 1,
 'Change manager': 1,
 'ETL Developer': 5,
 'SDFC Developer': 2,
 'Wintell & Vmware': 1,
 'Citrix Admin': 8,
 '. Net Full stack': 3,
 'MainFrame Developer': 2,
 'RPA BA': 3,
 'Adobe analystics': 1,
 'Mainframe tester': 1,
 'FSCM': 1,
 'Full stack Developer': 2,
 'Test Automation QA': 2,
 '12 LPA': 1,
 'Firmware testing With printer Domain': 1,
 'Sailpoint': 2,
 'sailpoint': 1,
 'Graphics Designer': 1,
 'Network Consultant': 1,
 'Java react': 2,
 'Mainframe developer': 1,
 'aem consultant': 2,
 'Migration consultant': 5,
 '.Net': 4,
 'Unix Developer': 1,
 'Java': 2,
 'Sementic information': 1,
 'IBM BPM': 1,
 'Ui Automation (RPA)': 2,
 'Pega developer': 7,
 'Golang': 1,
 'AS400': 5,
 'React node': 1,
 'React Js': 1,
 'NetCore + Azure': 1,
 'Devops admin': 1,
 'ITSM': 7,
 'Peoplesoft': 1,
 'Front end developer': 2,
 'perl developer': 2,
 'React js developer': 2,
 'Java with react': 1,
 'React Node': 2,
 'Dot net with microservices': 1,
 'CTS': 1,
 'NTT data': 1,
 'Sr frontend developer': 1,
 'Web developer-ML': 1,
 'Java developer': 1,
 'Java & react': 2,
 'Senior Full stack developer': 1,
 'Snowflake': 4,
 'Networking': 7,
 '.Net Azure': 1,
 'Linux Admin': 5,
 'Data engineer': 1,
 '7 Years': 1,
 'Golang Developer': 1,
 'go lang': 1,
 'Account Lead': 2,
 'Vmware Admin': 2,
 'As400': 1,
 'Python, Azure Developer': 2,
 'peoplesoft Fscm': 1,
 'Development Manager': 1,
 'Linux T-3': 5,
 'Java & kafka': 2,
 'Senior solution architect': 1,
 'Peoplesoft Fscm': 2,
 'java & AWS': 1,
 'Commvalut': 4,
 'Java struct': 1}
CURRENT_LOCATION_COUNTS = {'Bangalore': 129,
 'Hyderabad': 62,
 'Chennai': 34,
 'Pune': 26,
 'Mumbai': 9,
 'Andhra Pradesh': 9,
 'Bihar': 3,
 'Noida': 3,
 'Karnataka': 3,
 'Other': 3,
 'Mysuru': 2,
 'Nellore': 2,
 'Nagpur': 2,
 'Kolhapur': 1,
 'Visakhapatnam': 1,
 'Tirunelveli': 1,
 'Gurugram': 1,
 'Pata': 1,
 'Thane': 1,
 'Delhi': 1,
 'Up': 1,
 'Odissa': 1,
 'Indore': 1,
 'Mellore': 1,
 'Tirupathi': 1,
 'Meerut': 1,
 'Rajastan': 1,
 'Varnasi': 1,
 'Chittoor': 1,
 'Bhopal': 1,
 'Kovilpati': 1,
 'St Thomas Mount': 1,
 'Hariyana': 1}
PREFERRED_LOCATION_COUNTS = {'Bangalore': 175,
 'Hyderabad': 54,
 'Pune': 29,
 'Chennai': 28,
 'Mumbai': 7,
 'Noida': 6,
 'Other': 4,
 'Con': 3,
 'Mepz': 1}
EXPERIENCE_BAND_COUNTS = {
    "0-<2": 19,
    "2-<4": 66,
    "4-<6": 93,
    "6-<8": 63,
    "8-<12": 47,
    "12+": 19,
}

EXPERIENCE_VALUES = {
    "0-<2": [0.0, 1.1, 1.5, 1.8],
    "2-<4": [2.0, 2.4, 2.8, 3.0, 3.4, 3.8],
    "4-<6": [4.0, 4.3, 4.7, 5.0, 5.2, 5.8],
    "6-<8": [6.0, 6.4, 6.8, 7.0, 7.5],
    "8-<12": [8.0, 8.5, 9.0, 9.8, 10.0, 11.0],
    "12+": [12.0, 13.0, 14.0, 15.0, 17.0, 19.0, 22.0],
}
NOTICE_VALUES = [
    "Immediate", "immediate", "15 Days", "30 Days", "60 Days", "90 Days",
    "1 Month", "30 Days (Neg-15 Days)", "1 month neg 15-20", "Immediate (LWD available)",
]


def expand_counts(counts):
    output = []
    for value, count in counts.items():
        output.extend([value] * int(count))
    return output


def build_dataset():
    skills = expand_counts(SKILL_COUNTS)
    current_locations = expand_counts(CURRENT_LOCATION_COUNTS)
    preferred_locations = expand_counts(PREFERRED_LOCATION_COUNTS)
    experiences = []
    for band, count in EXPERIENCE_BAND_COUNTS.items():
        values = EXPERIENCE_VALUES[band]
        experiences.extend(values[index % len(values)] for index in range(count))

    assert len(skills) == 307
    assert len(current_locations) == 307
    assert len(preferred_locations) == 307
    assert len(experiences) == 307

    # Deterministic rotations prevent one-to-one reconstruction of any source candidate.
    current_locations = current_locations[47:] + current_locations[:47]
    preferred_locations = preferred_locations[91:] + preferred_locations[:91]
    experiences = experiences[133:] + experiences[:133]

    rows = []
    for index, skill in enumerate(skills, 1):
        experience = float(experiences[index - 1])
        current_location = current_locations[index - 1]
        preferred_location = preferred_locations[index - 1]
        notice = NOTICE_VALUES[(index * 7) % len(NOTICE_VALUES)]
        current_ctc = round(max(2.0, 1.35 * max(experience, 1.0)), 1)
        expected_ctc = round(current_ctc * 1.35, 1)
        candidate_code = f"QA{index:04d}"
        rows.append(
            {
                "name": f"Dataset Candidate {index:03d}",
                "email": f"dataset-candidate-{index:03d}@example.test",
                "phone": f"9{index:09d}"[-10:],
                "experience": experience,
                "skills": skill,
                "source": "Uploaded candidate dataset QA",
                "notice_period": notice,
                "current_ctc": f"{current_ctc} LPA",
                "expected_ctc": f"{expected_ctc} LPA",
                "resume_text": (
                    f"{candidate_code} is a privacy-safe QA profile with {experience} years of experience. "
                    f"Primary skill evidence: {skill}. Current location: {current_location}. "
                    f"Preferred location: {preferred_location}. Notice period: {notice}. "
                    "This synthetic resume text intentionally preserves the shape and vocabulary of the supplied "
                    "candidate records without retaining personal identifiers."
                ),
                "resume_filename": f"dataset_candidate_{index:03d}.txt",
                "profile_details": {
                    "qa_dataset_code": candidate_code,
                    "current_location": current_location,
                    "preferred_location": preferred_location,
                    "notice_period": notice,
                    "source_shape": "uploaded-candidate-records",
                },
                "stage": "Applied",
            }
        )

    # Explicit control case for the Java-vs-JavaScript regression previously seen in Talent Pool search.
    rows.append(
        {
            "name": "Dataset JavaScript Control",
            "email": "dataset-javascript-control@example.test",
            "phone": "9888800001",
            "experience": 5.0,
            "skills": "Python, Django, React, JavaScript",
            "source": "Uploaded candidate dataset QA control",
            "notice_period": "Immediate",
            "current_ctc": "8.0 LPA",
            "expected_ctc": "11.0 LPA",
            "resume_text": (
                "Five years of Python and Django backend experience with React and JavaScript frontend delivery. "
                "This intentionally represents a JavaScript-only profile with no JVM backend language experience. "
                "It exists only as a Boolean word-boundary control and contains no real candidate data."
            ),
            "resume_filename": "dataset_javascript_control.txt",
            "profile_details": {
                "qa_dataset_code": "QA-JS-CONTROL",
                "current_location": "Chennai",
                "preferred_location": "Chennai",
                "notice_period": "Immediate",
                "source_shape": "boolean-boundary-control",
            },
            "stage": "Applied",
        }
    )
    return rows


def wait_for_runtime():
    deadline = time.time() + 10
    while time.time() < deadline:
        state = main.app.state
        if (
            getattr(state, "shortlistai_tenant_security", False)
            and getattr(state, "_shortlistai_final_review_installed", False)
            and getattr(state, "_shortlistai_data_foundation_installed", False)
            and getattr(state, "_shortlistai_boolean_search_installed", False)
        ):
            return
        time.sleep(0.02)
    raise AssertionError("ShortlistAI secured/data/Boolean runtime did not install")


def register(client, email, workspace):
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


def run():
    wait_for_runtime()
    dataset = build_dataset()
    try:
        with TestClient(main.app) as client:
            register(client, "uploaded-dataset-one@example.test", "Uploaded Dataset QA")

            job = client.post(
                "/api/jobs",
                json={
                    "title": "Senior Java Engineer - Dataset QA",
                    "department": "Engineering",
                    "location": "Chennai",
                    "status": "Open",
                    "jd": (
                        "We are hiring a Senior Java Engineer with 4+ years of experience in Java, Spring Boot, "
                        "microservices, REST API development, SQL and cloud delivery. Strong recent hands-on Java "
                        "evidence is required. React is useful but JavaScript-only experience is not Java experience."
                    ),
                },
            )
            assert job.status_code == 200, job.text
            job_id = job.json()["id"]
            for row in dataset:
                row["job_id"] = job_id

            bulk = client.post("/api/candidates/bulk", json=dataset)
            assert bulk.status_code == 200, bulk.text
            body = bulk.json()
            assert body["received"] == 308
            assert body["created"] == 308
            assert body["merged"] == 0
            assert body["total_candidates"] == 308

            health = client.get("/api/data-health")
            assert health.status_code == 200, health.text
            health_body = health.json()
            assert health_body["candidate_count"] == 308
            assert health_body["identity_count"] >= 308
            assert health_body["bulk_limit"] == 800
            assert health_body["journal_mode"].lower() == "wal"
            assert health_body["busy_timeout_ms"] >= 5000
            assert health_body["foreign_keys"] is True

            # Realistic Boolean search: Java must not return the JavaScript-only control row.
            java = client.get("/api/candidates", params={"q": "Java"})
            assert java.status_code == 200, java.text
            java_rows = java.json()
            assert java_rows, "dataset contains Java profiles and should return matches"
            assert all(row["email"] != "dataset-javascript-control@example.test" for row in java_rows)
            standalone_java = re.compile(r"(?<![a-z0-9])java(?![a-z0-9])", re.I)
            assert all(
                standalone_java.search(
                    " ".join(
                        [
                            str(row.get("skills") or ""),
                            str(row.get("resume_text") or ""),
                        ]
                    )
                )
                for row in java_rows
            )

            spring = client.get(
                "/api/candidates",
                params={"q": 'Java AND (SpringBoot OR "Spring Boot")'},
            )
            assert spring.status_code == 200, spring.text
            spring_rows = spring.json()
            assert spring_rows, "uploaded-data distribution includes Java SpringBoot profiles"
            assert all(standalone_java.search(str(row.get("resume_text") or "")) for row in spring_rows)

            react_not_java = client.get("/api/candidates", params={"q": "React NOT Java"})
            assert react_not_java.status_code == 200, react_not_java.text
            assert react_not_java.json(), "dataset includes React-only profiles"
            assert all(
                not standalone_java.search(
                    " ".join([str(row.get("skills") or ""), str(row.get("resume_text") or "")])
                )
                for row in react_not_java.json()
            )

            # Candidate filters should behave against realistic location, experience and notice-period mixes.
            chennai = client.get("/api/candidates", params={"location": "Chennai"})
            assert chennai.status_code == 200, chennai.text
            assert chennai.json()
            assert all(
                "chennai"
                in " ".join(
                    [
                        str((row.get("profile_details") or {}).get("current_location") or ""),
                        str((row.get("profile_details") or {}).get("preferred_location") or ""),
                    ]
                ).lower()
                for row in chennai.json()
            )

            experienced = client.get(
                "/api/candidates",
                params={"min_experience": 4, "max_experience": 8},
            )
            assert experienced.status_code == 200, experienced.text
            assert experienced.json()
            assert all(4 <= float(row["experience"]) <= 8 for row in experienced.json())

            immediate = client.get("/api/candidates", params={"notice_period": "Immediate"})
            assert immediate.status_code == 200, immediate.text
            assert immediate.json()
            assert all("immediate" in str(row.get("notice_period") or "").lower() for row in immediate.json())

            # Duplicate identity must merge, not create a silent duplicate.
            first = dataset[0]
            duplicate_payload = dict(first)
            duplicate_payload["email"] = first["email"].upper()
            duplicate_payload["skills"] = first["skills"] + ", FastAPI"
            duplicate_payload["profile_details"] = dict(first["profile_details"])
            duplicate_payload["profile_details"]["preferred_location"] = "Hyderabad"
            duplicate = client.post("/api/candidates", json=duplicate_payload)
            assert duplicate.status_code == 200, duplicate.text
            duplicate_body = duplicate.json()
            assert duplicate_body["merged"] is True

            after_merge = client.get("/api/data-health")
            assert after_merge.status_code == 200
            assert after_merge.json()["candidate_count"] == 308

            merged_candidate = client.get(f"/api/candidates/{duplicate_body['id']}")
            assert merged_candidate.status_code == 200, merged_candidate.text
            merged_body = merged_candidate.json()
            assert "fastapi" in merged_body["skills"].lower()
            assert merged_body["profile_details"]["duplicate_merge_count"] >= 1

            # Core recruiter workflow: notes, stage transition, dashboard and deterministic scoring.
            note = client.post(
                f"/api/candidates/{duplicate_body['id']}/notes",
                json={"note": "Dataset QA regression note"},
            )
            assert note.status_code == 200, note.text

            stage = client.patch(
                f"/api/candidates/{duplicate_body['id']}/stage",
                json={"stage": "Hired"},
            )
            assert stage.status_code == 200, stage.text

            detail = client.get(f"/api/candidates/{duplicate_body['id']}")
            assert detail.status_code == 200, detail.text
            detail_body = detail.json()
            assert detail_body["stage"] == "Hired"
            assert any(n["note"] == "Dataset QA regression note" for n in detail_body["notes"])

            dashboard = client.get("/api/dashboard-v2")
            assert dashboard.status_code == 200, dashboard.text
            dashboard_body = dashboard.json()
            assert dashboard_body["summary"]["profiles_sourced"] == 308
            assert dashboard_body["summary"]["hired"] == 1
            assert dashboard_body["summary"]["in_pipeline"] == 307

            # Score one real-shape Java record twice: result should be stable, not random/dummy.
            java_candidate = next(row for row in java_rows if "spring" in (row.get("skills") or "").lower())
            first_score = client.post(f"/api/candidates/{java_candidate['id']}/evaluate")
            second_score = client.post(f"/api/candidates/{java_candidate['id']}/evaluate")
            assert first_score.status_code == 200, first_score.text
            assert second_score.status_code == 200, second_score.text
            assert first_score.json()["score"] == second_score.json()["score"]
            assert first_score.json()["rating"] == second_score.json()["rating"]

            # Tenant isolation: a new workspace must not see the first workspace's 308 profiles.
            logout = client.post("/api/auth/logout", json={"token": ""})
            assert logout.status_code == 200, logout.text
            register(client, "uploaded-dataset-two@example.test", "Uploaded Dataset QA Two")
            isolated_health = client.get("/api/data-health")
            assert isolated_health.status_code == 200, isolated_health.text
            assert isolated_health.json()["candidate_count"] == 0

            isolated_candidates = client.get("/api/candidates")
            assert isolated_candidates.status_code == 200, isolated_candidates.text
            assert isolated_candidates.json() == []

        print("Uploaded candidate dataset regression passed")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
