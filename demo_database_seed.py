from __future__ import annotations

import json
import sqlite3
from datetime import datetime

DEMO_SOURCE = "Demo Database"

JOBS = [
    {
        "title": "Senior Python Full Stack Developer",
        "department": "Engineering",
        "location": "Chennai / Hybrid",
        "jd": "4-8 years of experience with Python, FastAPI, React, TypeScript, REST APIs, PostgreSQL and exposure to Generative AI or Agentic AI.",
    },
    {
        "title": "Lead QA Automation Engineer",
        "department": "Quality Engineering",
        "location": "Chennai",
        "jd": "7+ years of hands-on automation experience with Playwright or Selenium, API testing, CI/CD and modern AI-assisted testing practices.",
    },
    {
        "title": "Product Manager",
        "department": "Product",
        "location": "Chennai / Bengaluru",
        "jd": "5+ years in product management with roadmap ownership, stakeholder management, analytics, agile delivery and strong technical product exposure.",
    },
]

# Fictional profiles exist only to exercise ATS workflow states. Assessment score,
# rating and AI details are intentionally left empty: ShortlistAI must calculate
# those from the real JD/resume scoring engine rather than seed dummy values.
# name, email, exp, skills, ATS stage, job index, L1 status, L2 status
CANDIDATES = [
    ("Arjun Raman", "arjun.raman@example.test", 6.8, "python, fastapi, react, typescript, postgresql, generative ai, docker", "Contacted", 0, "Pending Scheduling", "Not Started"),
    ("Meera Nair", "meera.nair@example.test", 5.4, "python, django, react, javascript, aws, rest api", "Interview Scheduled", 0, "Cleared", "Pending Scheduling"),
    ("Karthik S", "karthik.s@example.test", 4.2, "python, flask, react, sql, docker", "Applied", 0, "Pending Scheduling", "Not Started"),
    ("Priya Menon", "priya.menon@example.test", 7.1, "java, spring boot, angular, mysql", "Dropped", 0, "Not Applicable", "Not Applicable"),
    ("Naveen Kumar", "naveen.kumar@example.test", 9.0, "playwright, selenium, api testing, pytest, jenkins, github actions", "L2", 1, "Cleared", "Cleared"),
    ("Divya R", "divya.r@example.test", 7.8, "selenium, cypress, api testing, automation testing, jira", "Contacted", 1, "Pending Scheduling", "Not Started"),
    ("Rahul Iyer", "rahul.iyer@example.test", 6.5, "manual testing, jira, sql", "Applied", 1, "Pending Scheduling", "Not Started"),
    ("Sanjana V", "sanjana.v@example.test", 8.2, "product management, roadmap, analytics, agile, stakeholder management, jira", "Selected", 2, "Cleared", "Cleared"),
    ("Vikram Rao", "vikram.rao@example.test", 6.0, "product management, scrum, stakeholder management, figma", "L1", 2, "Cleared", "Pending Scheduling"),
    ("Ananya S", "ananya.s@example.test", 5.2, "business analysis, agile, jira, analytics", "Contacted", 2, "Pending Scheduling", "Not Started"),
    ("Suresh B", "suresh.b@example.test", 8.5, "python, fastapi, react, agentic ai, llm, rag, langchain, aws", "Hired", 0, "Cleared", "Cleared"),
    ("Lavanya P", "lavanya.p@example.test", 7.3, "playwright, pytest, api testing, ci/cd, docker", "Selected", 1, "Cleared", "Cleared"),
]


def seed_demo_database(db_path: str) -> None:
    """Seed/refresh fictional ATS data without inventing AI assessment results."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    now = datetime.utcnow().isoformat()

    job_ids: list[int] = []
    for job in JOBS:
        row = con.execute("SELECT id FROM jobs WHERE title=? AND department=? LIMIT 1", (job["title"], job["department"])).fetchone()
        if row:
            job_ids.append(int(row["id"]))
            continue
        cur = con.execute(
            "INSERT INTO jobs(title,department,location,jd,status,created_at) VALUES(?,?,?,?,?,?)",
            (job["title"], job["department"], job["location"], job["jd"], "Open", now),
        )
        job_ids.append(int(cur.lastrowid))

    for name, email, exp, skills, stage, job_index, l1_status, l2_status in CANDIDATES:
        profile_details = {
            "candidate_full_name": name,
            "email_id": email,
            "total_experience": exp,
            "relevant_experience": str(max(1.0, exp - 1.0)),
            "current_organization": "Demo Company",
            "current_designation": "Senior Professional" if exp >= 7 else "Professional",
            "current_location": "Chennai",
            "preferred_location": "Chennai",
            "notice_period": "30 Days",
            "screening_status": stage,
            "interview_level": "L2 Cleared" if l2_status == "Cleared" else "L1 Cleared" if l1_status == "Cleared" else "L1 Pending",
            "l1_status": l1_status,
            "l2_status": l2_status,
            "role_name": JOBS[job_index]["title"],
            "recruiter_name": "Demo Recruiter",
            "remarks": "Fictional workflow profile for ShortlistAI product validation. AI assessment intentionally not pre-scored.",
        }
        resume_text = f"{name}\n{exp} years of experience\nSkills: {skills}\nRecent project aligned to {JOBS[job_index]['title']}."

        existing = con.execute("SELECT id FROM candidates WHERE source=? AND email=? LIMIT 1", (DEMO_SOURCE, email)).fetchone()
        if existing:
            con.execute(
                """UPDATE candidates SET experience=?,skills=?,resume_text=?,resume_filename=?,job_id=?,stage=?,
                   ai_score=NULL,rating=NULL,ai_details=NULL,profile_details=?,updated_at=? WHERE id=?""",
                (exp, skills, resume_text, f"{name.replace(' ', '_')}_Demo.txt", job_ids[job_index], stage, json.dumps(profile_details), now, int(existing["id"])),
            )
            continue

        con.execute(
            """INSERT INTO candidates(
                name,email,phone,experience,skills,resume_text,resume_filename,source,
                notice_period,current_ctc,expected_ctc,job_id,stage,ai_score,rating,
                ai_details,profile_details,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,email,"",exp,skills,resume_text,f"{name.replace(' ', '_')}_Demo.txt",DEMO_SOURCE,
                "30 Days","","",job_ids[job_index],stage,None,None,None,json.dumps(profile_details),now,now,
            ),
        )

    con.commit()
    con.close()
