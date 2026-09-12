from pathlib import Path

p = Path("main.py")
s = p.read_text(encoding="utf-8")

# Import pure talent-pool helpers.
needle = "from sklearn.metrics.pairwise import cosine_similarity\n"
addition = "from shortlistai_talent import classify_talent_pools, encode_talent_pools, decode_talent_pools\n"
if addition not in s:
    s = s.replace(needle, needle + addition, 1)

# Database additions: activity log + persistent talent-pool assignments.
notes_block = '''    cur.execute("""CREATE TABLE IF NOT EXISTS notes(\n        id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)""")\n'''
activity_block = '''    cur.execute("""CREATE TABLE IF NOT EXISTS activity_log(\n        id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id INTEGER NOT NULL,action TEXT NOT NULL,details TEXT,created_at TEXT NOT NULL)""")\n'''
if activity_block not in s:
    if notes_block not in s:
        raise SystemExit("notes table marker not found")
    s = s.replace(notes_block, notes_block + activity_block, 1)

profile_col = '    _ensure_column(cur, "candidates", "profile_details", "TEXT")\n'
talent_col = '    _ensure_column(cur, "candidates", "talent_pools", "TEXT")\n'
if talent_col not in s:
    if profile_col not in s:
        raise SystemExit("profile_details column marker not found")
    s = s.replace(profile_col, profile_col + talent_col, 1)

# Candidate serialization: decode saved pools, and classify legacy/new rows when blank.
start = s.index('def _candidate_dict(row: sqlite3.Row) -> Dict[str,Any]:')
end = s.index('\n\ndef _candidate_duplicate', start)
new_candidate_dict = '''def _candidate_dict(row: sqlite3.Row) -> Dict[str,Any]:
    d = dict(row)
    d["ai_evaluation"] = _decode_ai_details(d.pop("ai_details", None))
    d["profile_details"] = _decode_ai_details(d.get("profile_details")) or {}
    pools = decode_talent_pools(d.get("talent_pools"))
    if not pools:
        pools = classify_talent_pools(
            d.get("resume_text") or "",
            d.get("skills") or "",
            json.dumps(d.get("profile_details") or {}, ensure_ascii=False),
        )
    d["talent_pools"] = pools
    return d
'''
s = s[:start] + new_candidate_dict + s[end:]

# Activity helper.
dup_end_marker = '\n\n@app.get("/", response_class=HTMLResponse)'
idx = s.index(dup_end_marker)
if 'def _log_activity(' not in s:
    helper = '''\n\ndef _log_activity(con: sqlite3.Connection, candidate_id: int, action: str, details: str = "") -> None:
    con.execute(
        "INSERT INTO activity_log(candidate_id,action,details,created_at) VALUES(?,?,?,?)",
        (candidate_id, action, details, datetime.utcnow().isoformat()),
    )
'''
    s = s[:idx] + helper + s[idx:]

# Extend request models for manual editing and manual pool assignment.
marker = '    stage: str = "Sourced"\n\nclass StageIn(BaseModel):\n'
if 'class CandidateUpdate(BaseModel):' not in s:
    replacement = '''    stage: str = "Sourced"
    talent_pools: Optional[List[str]] = None

class CandidateUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    experience: Optional[float] = None
    skills: Optional[str] = None
    source: Optional[str] = None
    notice_period: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    resume_text: Optional[str] = None
    resume_filename: Optional[str] = None
    profile_details: Optional[Dict[str,Any]] = None
    talent_pools: Optional[List[str]] = None
    job_id: Optional[int] = None
    stage: Optional[str] = None

class StageIn(BaseModel):
'''
    if marker not in s:
        raise SystemExit("CandidateIn marker not found")
    s = s.replace(marker, replacement, 1)

# Replace candidate-list endpoint with recruiter-style filters.
start = s.index('@app.get("/api/candidates")')
end = s.index('\n@app.get("/api/candidates/{candidate_id}")', start)
new_list = '''@app.get("/api/candidates")
def list_candidates(
    job_id: Optional[int] = None,
    stage: Optional[str] = None,
    q: Optional[str] = None,
    talent_pool: Optional[str] = None,
    min_experience: Optional[float] = None,
    max_experience: Optional[float] = None,
    location: Optional[str] = None,
    notice_period: Optional[str] = None,
):
    sql = """SELECT c.*,j.title job_title FROM candidates c
             LEFT JOIN jobs j ON j.id=c.job_id WHERE 1=1"""
    args: List[Any] = []
    if job_id:
        sql += " AND c.job_id=?"
        args.append(job_id)
    if stage:
        sql += " AND c.stage=?"
        args.append(stage)
    sql += " ORDER BY COALESCE(c.ai_score,0) DESC,c.id DESC"
    con = db()
    rows = [_candidate_dict(x) for x in con.execute(sql, args)]
    con.close()

    if q:
        term = q.strip().lower()
        rows = [r for r in rows if term in " ".join([
            str(r.get("name") or ""), str(r.get("email") or ""), str(r.get("phone") or ""),
            str(r.get("skills") or ""), str(r.get("job_title") or ""),
            json.dumps(r.get("profile_details") or {}, ensure_ascii=False),
            " ".join(r.get("talent_pools") or []),
        ]).lower()]
    if talent_pool:
        wanted = talent_pool.strip().lower()
        rows = [r for r in rows if any(p.lower() == wanted for p in (r.get("talent_pools") or []))]
    if min_experience is not None:
        rows = [r for r in rows if r.get("experience") is not None and float(r["experience"]) >= min_experience]
    if max_experience is not None:
        rows = [r for r in rows if r.get("experience") is not None and float(r["experience"]) <= max_experience]
    if location:
        wanted = location.strip().lower()
        rows = [r for r in rows if wanted in " ".join([
            str((r.get("profile_details") or {}).get("current_location") or ""),
            str((r.get("profile_details") or {}).get("preferred_location") or ""),
            str((r.get("profile_details") or {}).get("native_location") or ""),
        ]).lower()]
    if notice_period:
        wanted = notice_period.strip().lower()
        rows = [r for r in rows if wanted in str(r.get("notice_period") or (r.get("profile_details") or {}).get("notice_period") or "").lower()]
    return rows
'''
s = s[:start] + new_list + s[end:]

# Include candidate activity in profile response.
needle = '''    out["notes"] = [dict(x) for x in con.execute(
        "SELECT * FROM notes WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)
    )]
'''
replacement = needle + '''    out["activity"] = [dict(x) for x in con.execute(
        "SELECT * FROM activity_log WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)
    )]
'''
if 'out["activity"]' not in s:
    if needle not in s:
        raise SystemExit("get_candidate notes marker not found")
    s = s.replace(needle, replacement, 1)

# Rewrite candidate creation so talent pools are persisted immediately.
start = s.index('@app.post("/api/candidates")')
end = s.index('\n@app.patch("/api/candidates/{candidate_id}/stage")', start)
new_create_and_edit = '''@app.post("/api/candidates")
def create_candidate(x: CandidateIn):
    if x.stage not in STAGES:
        raise HTTPException(400, "Invalid stage")
    now = datetime.utcnow().isoformat()
    con = db()
    duplicate = _candidate_duplicate(con, x.email, x.phone)
    if duplicate:
        name = duplicate["name"] or "Existing candidate"
        con.close()
        raise HTTPException(409, f"Possible duplicate candidate: {name} already exists in the ATS.")
    profile = x.profile_details or {}
    pools = x.talent_pools if x.talent_pools is not None else classify_talent_pools(
        x.resume_text, x.skills, json.dumps(profile, ensure_ascii=False)
    )
    cur = con.cursor()
    cur.execute(
        """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,source,notice_period,current_ctc,
           expected_ctc,profile_details,talent_pools,job_id,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (x.name,x.email,x.phone,x.experience,x.skills,x.resume_text,x.resume_filename,x.source,x.notice_period,x.current_ctc,
         x.expected_ctc,json.dumps(profile),encode_talent_pools(pools),x.job_id,x.stage,now,now)
    )
    i = cur.lastrowid
    _log_activity(con, i, "Candidate created", f"Stage: {x.stage}")
    con.commit()
    con.close()
    return {"id": i, "talent_pools": pools}

@app.patch("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: int, x: CandidateUpdate):
    con = db()
    row = con.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Candidate not found")
    current = dict(row)
    data = x.dict(exclude_unset=True)
    if "stage" in data and data["stage"] is not None and data["stage"] not in STAGES:
        con.close()
        raise HTTPException(400, "Invalid stage")

    if "email" in data or "phone" in data:
        duplicate = _candidate_duplicate(
            con,
            data.get("email", current.get("email") or ""),
            data.get("phone", current.get("phone") or ""),
        )
        if duplicate and duplicate["id"] != candidate_id:
            name = duplicate["name"] or "Existing candidate"
            con.close()
            raise HTTPException(409, f"Possible duplicate candidate: {name} already exists in the ATS.")

    existing_profile = _decode_ai_details(current.get("profile_details")) or {}
    if "profile_details" in data:
        incoming_profile = data.pop("profile_details") or {}
        existing_profile.update(incoming_profile)
        data["profile_details"] = json.dumps(existing_profile)

    explicit_pools = data.pop("talent_pools", None) if "talent_pools" in data else None
    if explicit_pools is not None:
        data["talent_pools"] = encode_talent_pools(explicit_pools)
    elif any(k in data for k in ("skills", "resume_text", "profile_details")):
        skills = data.get("skills", current.get("skills") or "")
        resume_text = data.get("resume_text", current.get("resume_text") or "")
        profile_json = data.get("profile_details", current.get("profile_details") or "{}")
        data["talent_pools"] = encode_talent_pools(classify_talent_pools(resume_text, skills, profile_json))

    allowed = {
        "name","email","phone","experience","skills","source","notice_period","current_ctc","expected_ctc",
        "resume_text","resume_filename","profile_details","talent_pools","job_id","stage"
    }
    updates, values, changed = [], [], []
    for key, value in data.items():
        if key not in allowed:
            continue
        updates.append(f"{key}=?")
        values.append(value)
        changed.append(key)
    if not updates:
        con.close()
        return {"ok": True, "changed": []}
    updates.append("updated_at=?")
    values.append(datetime.utcnow().isoformat())
    values.append(candidate_id)
    con.execute(f"UPDATE candidates SET {', '.join(updates)} WHERE id=?", values)
    _log_activity(con, candidate_id, "Candidate updated", "Updated fields: " + ", ".join(changed))
    con.commit()
    updated = con.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    out = _candidate_dict(updated)
    con.close()
    return {"ok": True, "changed": changed, "candidate": out}
'''
s = s[:start] + new_create_and_edit + s[end:]

# Log pipeline stage changes.
old_stage = '''    con.execute(
        "UPDATE candidates SET stage=?,updated_at=? WHERE id=?",
        (x.stage, datetime.utcnow().isoformat(), candidate_id)
    )
    con.commit()
'''
new_stage = '''    old = con.execute("SELECT stage FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    con.execute(
        "UPDATE candidates SET stage=?,updated_at=? WHERE id=?",
        (x.stage, datetime.utcnow().isoformat(), candidate_id)
    )
    if old:
        _log_activity(con, candidate_id, "Stage changed", f"{old['stage']} → {x.stage}")
    con.commit()
'''
if '_log_activity(con, candidate_id, "Stage changed"' not in s:
    if old_stage not in s:
        raise SystemExit("stage update marker not found")
    s = s.replace(old_stage, new_stage, 1)

# Log recruiter notes.
old_note = '''    con.execute(
        "INSERT INTO notes(candidate_id,note,created_at) VALUES(?,?,?)",
        (candidate_id, x.note.strip(), datetime.utcnow().isoformat())
    )
    con.commit()
'''
new_note = '''    con.execute(
        "INSERT INTO notes(candidate_id,note,created_at) VALUES(?,?,?)",
        (candidate_id, x.note.strip(), datetime.utcnow().isoformat())
    )
    _log_activity(con, candidate_id, "Recruiter note added", x.note.strip()[:180])
    con.commit()
'''
if '_log_activity(con, candidate_id, "Recruiter note added"' not in s:
    if old_note not in s:
        raise SystemExit("note marker not found")
    s = s.replace(old_note, new_note, 1)

# Talent-pool summary endpoint for the future Talent Pools UI.
marker = '\n@app.post("/api/jobs")\ndef create_job(x: JobIn):\n'
if '@app.get("/api/talent-pools")' not in s:
    endpoint = '''
@app.get("/api/talent-pools")
def list_talent_pools():
    con = db()
    rows = [_candidate_dict(x) for x in con.execute("SELECT * FROM candidates ORDER BY id DESC")]
    con.close()
    counts: Dict[str,int] = {}
    for row in rows:
        for pool in row.get("talent_pools") or []:
            counts[pool] = counts.get(pool, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))]

'''
    if marker not in s:
        raise SystemExit("jobs endpoint marker not found")
    s = s.replace(marker, endpoint + marker, 1)

p.write_text(s, encoding="utf-8")
print("talent pools/manual edit/activity patch applied")
