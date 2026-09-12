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

CANDIDATES = [
    ("Arjun Raman", "arjun.raman@example.test", 6.8, "python, fastapi, react, typescript, postgresql, generative ai, docker", "Screened", 88.0, "Strong", 0),
    ("Meera Nair", "meera.nair@example.test", 5.4, "python, django, react, javascript, aws, rest api", "Interview", 76.0, "Strong", 0),
    ("Karthik S", "karthik.s@example.test", 4.2, "python, flask, react, sql, docker", "Sourced", 63.0, "Average", 0),
    ("Priya Menon", "priya.menon@example.test", 7.1, "java, spring boot, angular, mysql", "Rejected", 41.0, "Weak", 0),
    ("Naveen Kumar", "naveen.kumar@example.test", 9.0, "playwright, selenium, api testing, pytest, jenkins, github actions", "Interview", 91.0, "Strong", 1),
    ("Divya R", "divya.r@example.test", 7.8, "selenium, cypress, api testing, automation testing, jira", "Screened", 74.0, "Average", 1),
    ("Rahul Iyer", "rahul.iyer@example.test", 6.5, "manual testing, jira, sql", "Sourced", 46.0, "Weak", 1),
    ("Sanjana V", "sanjana.v@example.test", 8.2, "product management, roadmap, analytics, agile, stakeholder management, jira", "Offered", 89.0, "Strong", 2),
    ("Vikram Rao", "vikram.rao@example.test", 6.0, "product management, scrum, stakeholder management, figma", "Interview", 72.0, "Average", 2),
    ("Ananya S", "ananya.s@example.test", 5.2, "business analysis, agile, jira, analytics", "Screened", 58.0, "Average", 2),
    ("Suresh B", "suresh.b@example.test", 8.5, "python, fastapi, react, agentic ai, llm, rag, langchain, aws", "Joined", 94.0, "Strong", 0),
    ("Lavanya P", "lavanya.p@example.test", 7.3, "playwright, pytest, api testing, ci/cd, docker", "Offered", 84.0, "Strong", 1),
]


def seed_demo_database(db_path: str) -> None:
    """Seed idempotent fictional data so dashboard, pipeline and AI states are testable."""
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

    for name, email, exp, skills, stage, score, rating, job_index in CANDIDATES:
        existing = con.execute("SELECT id FROM candidates WHERE source=? AND email=? LIMIT 1", (DEMO_SOURCE, email)).fetchone()
        if existing:
            continue

        matched = [s.strip() for s in skills.split(",")[:5]]
        missing = [] if rating == "Strong" else (["generative ai"] if job_index == 0 else ["advanced automation framework design"] if job_index == 1 else ["deeper product analytics"])
        ai_details = {
            "score": score,
            "rating": rating,
            "candidate_years": exp,
            "required_years": 4 if job_index == 0 else 7 if job_index == 1 else 5,
            "semantic_similarity": min(96.0, score + 3),
            "skill_coverage": score,
            "recent_evidence": max(35.0, score - 8),
            "matched_skills": matched,
            "missing_skills": missing,
            "recent_skills": matched[:3],
            "risks": [] if rating == "Strong" else ["Validate depth in the missing requirement during screening."],
            "screening_questions": ["Describe your most relevant recent project and what you personally owned."],
            "test_source": DEMO_SOURCE,
        }
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
            "role_name": JOBS[job_index]["title"],
            "recruiter_name": "Demo Recruiter",
            "remarks": "Fictional test profile generated for ShortlistAI product validation.",
        }
        resume_text = f"{name}\n{exp} years of experience\nSkills: {skills}\nRecent project aligned to {JOBS[job_index]['title']}."

        con.execute(
            """INSERT INTO candidates(
                name,email,phone,experience,skills,resume_text,resume_filename,source,
                notice_period,current_ctc,expected_ctc,job_id,stage,ai_score,rating,
                ai_details,profile_details,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,email,"",exp,skills,resume_text,f"{name.replace(' ', '_')}_Demo.txt",DEMO_SOURCE,
                "30 Days","","",job_ids[job_index],stage,score,rating,
                json.dumps(ai_details),json.dumps(profile_details),now,now,
            ),
        )

    con.commit()
    con.close()
