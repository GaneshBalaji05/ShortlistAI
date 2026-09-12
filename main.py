from __future__ import annotations
import io, re, sqlite3, os, json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "shortlistai.db"))
app = FastAPI(title="ShortlistAI ATS", version="1.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

SKILLS = [
    "python","fastapi","django","flask","java","spring boot","javascript","typescript","react","react.js","react 19","next.js","node.js","angular","vue",
    "html","css","tailwind","redux","rest api","graphql","microservices","sql","mysql","postgresql","mongodb","redis","elasticsearch","kafka","rabbitmq",
    "aws","azure","gcp","docker","kubernetes","terraform","jenkins","github actions","gitlab","ci/cd","linux","nginx",
    "generative ai","genai","agentic ai","llm","rag","langchain","langgraph","anthropic","claude","openai","mlflow","databricks","machine learning","deep learning",
    "pandas","numpy","scikit-learn","pytorch","tensorflow","computer vision","nlp","prompt engineering",
    "swift","ios","xcode","swiftui","uikit","android","kotlin","jetpack compose","flutter","react native",
    "selenium","playwright","cypress","appium","pytest","junit","testng","automation testing","api testing",
    "magento 2","adobe commerce","hcl commerce","shopify","salesforce","zoho crm","sap","oracle",
    "cybersecurity","google adk","oauth","rbac","sso","jwt","event streaming","erp integration",
    "product management","jira","figma","agile","scrum","stakeholder management","roadmap","analytics",
    "talent acquisition","it recruitment","technical recruitment","end-to-end recruitment","candidate sourcing","naukri","linkedin recruiter",
    "screening","interview coordination","offer negotiation","candidate engagement","recruitment mis","onboarding","pipeline building",
    "boolean search","recruitment reporting"
]

ALIASES = {
    "react.js":"react","reactjs":"react","nodejs":"node.js","node":"node.js","gen ai":"genai",
    "amazon web services":"aws","google cloud":"gcp","k8s":"kubernetes","postgres":"postgresql",
    "restful api":"rest api","restful apis":"rest api"
}

SKILL_SYNONYMS = {
    "talent acquisition": ["talent acquisition"],
    "it recruitment": ["it recruitment","it hiring","technology recruitment","technology hiring"],
    "technical recruitment": ["technical recruitment","technical hiring","tech recruitment","tech hiring"],
    "end-to-end recruitment": ["end-to-end recruitment","end to end recruitment","complete recruitment lifecycle","complete recruitment life cycle","recruitment lifecycle","recruitment life cycle"],
    "candidate sourcing": ["candidate sourcing","sourcing candidates","sourced candidates","sourcing & hiring","sourcing and hiring","head hunting","headhunting"],
    "naukri": ["naukri"],
    "linkedin recruiter": ["linkedin recruiter","linkedin"],
    "screening": ["screening","resume screening","profile screening","screen profiles","screened profiles"],
    "interview coordination": ["interview coordination","coordinate interviews","coordinated interviews","schedule interviews","scheduled interviews"],
    "offer negotiation": ["offer negotiation","salary negotiation","compensation negotiation","negotiated compensation","offer discussions"],
    "stakeholder management": ["stakeholder management","stakeholder relationships","hiring managers","leadership teams"],
    "candidate engagement": ["candidate engagement","engaging candidates","candidate experience","candidate relationship","candidate communication","communication with candidates"],
    "recruitment mis": ["recruitment mis","mis reports","recruitment reporting","pipeline reports","hiring reports","recruitment trackers","hiring updates"],
    "onboarding": ["onboarding"],
    "pipeline building": ["candidate pipeline","talent pipeline","pipeline building","candidate pipelines","talent pipelines"],
    "boolean search": ["boolean search"],
    "recruitment reporting": ["recruitment reporting","pipeline reports","hiring reports","hiring updates","recruitment trackers"]
}

STOP = set("a an the and or of in on to for with from by as is are be been being this that these those you we our your will would should can may must role job candidate experience years year work working knowledge strong good excellent hands hand responsibilities requirements required preferred plus team teams ability skills skill using use used development developer engineer engineering design build building maintain maintaining".split())
STAGES = ["Sourced","Screened","Interview","Offered","Joined","Rejected"]

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def _ensure_column(cur, table: str, column: str, ddl: str):
    cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,department TEXT,location TEXT,
        jd TEXT NOT NULL,status TEXT DEFAULT 'Open',created_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS candidates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT,phone TEXT,experience REAL,
        skills TEXT,resume_text TEXT,source TEXT,notice_period TEXT,current_ctc TEXT,expected_ctc TEXT,
        job_id INTEGER,stage TEXT DEFAULT 'Sourced',ai_score REAL,rating TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)""")
    _ensure_column(cur, "candidates", "ai_details", "TEXT")
    _ensure_column(cur, "candidates", "resume_filename", "TEXT")
    _ensure_column(cur, "candidates", "profile_details", "TEXT")
    con.commit()
    con.close()

@app.on_event("startup")
def startup():
    init_db()

def normalize(text: str) -> str:
    text = (text or "").lower().replace("–","-").replace("—","-")
    for src, dst in sorted(ALIASES.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"(?<![a-z0-9])" + re.escape(src) + r"(?![a-z0-9])", dst, text)
    text = re.sub(r"[^a-z0-9+#./\- &]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _dedupe_text(parts: List[str]) -> List[str]:
    out, seen = [], set()
    for part in parts:
        clean = re.sub(r"\s+", " ", part or "").strip()
        if not clean or clean in {"•","●","▪","◦"}:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean)
    return out

def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        if ext == ".docx":
            doc = Document(io.BytesIO(data))
            parts: List[str] = []
            parts.extend(p.text for p in doc.paragraphs if p.text and p.text.strip())
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text and cell.text.strip():
                            parts.append(cell.text)
            for sec in doc.sections:
                parts.extend(p.text for p in sec.header.paragraphs if p.text and p.text.strip())
                parts.extend(p.text for p in sec.footer.paragraphs if p.text and p.text.strip())
            try:
                base = " ".join(parts).lower()
                for node in doc.element.body.iter():
                    if node.tag.endswith("}t") and node.text:
                        clean = re.sub(r"\s+", " ", node.text).strip()
                        if clean and clean not in {"•","●","▪","◦"} and clean.lower() not in base:
                            parts.append(clean)
            except Exception:
                pass
            return "\n".join(_dedupe_text(parts))
        if ext in {".txt",".md"}:
            return data.decode("utf-8", errors="ignore")
    except Exception as e:
        raise ValueError(f"Could not read {filename}: {e}")
    raise ValueError(f"Unsupported format for {filename}. Use PDF, DOCX, TXT or MD.")

def _contains_phrase(text_norm: str, phrase: str) -> bool:
    p = normalize(phrase)
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", text_norm))

def find_skills(text: str) -> List[str]:
    n = " " + normalize(text) + " "
    out: List[str] = []
    for skill in SKILLS:
        phrases = SKILL_SYNONYMS.get(skill, [skill])
        if any(_contains_phrase(n, phrase) for phrase in phrases):
            canonical = ALIASES.get(skill, skill)
            if canonical not in out:
                out.append(canonical)
    return out

def parse_required_years(jd: str) -> Optional[float]:
    n = normalize(jd)
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?",
        r"(?:minimum|min|at least)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?",
        r"(\d+(?:\.\d+)?)\s*\+\s*years?",
        r"(\d+(?:\.\d+)?)\s*years?\s*(?:of)?\s*experience",
    ]
    for p in patterns:
        m = re.search(p, n)
        if m:
            return float(m.group(1))
    return None

def _experience_from_dates(resume: str) -> Optional[float]:
    ranges = []
    now = datetime.utcnow()
    pat = re.compile(r"(\d{1,2})/(\d{4})\s*-\s*(?:(\d{1,2})/(\d{4})|present|current)", re.I)
    for m in pat.finditer(resume):
        sm, sy = int(m.group(1)), int(m.group(2))
        if m.group(3) and m.group(4):
            em, ey = int(m.group(3)), int(m.group(4))
        else:
            em, ey = now.month, now.year
        if 1 <= sm <= 12 and 1 <= em <= 12 and 1990 <= sy <= ey <= now.year + 1:
            start = sy * 12 + sm
            end = ey * 12 + em
            if 0 <= end - start <= 600:
                ranges.append((start, end))
    if not ranges:
        return None
    ranges.sort()
    merged = []
    for start, end in ranges:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    months = sum(max(0, end - start + 1) for start, end in merged)
    years = round(months / 12.0, 1)
    return years if 0 < years <= 50 else None

def parse_candidate_years(resume: str) -> Optional[float]:
    n = normalize(resume)
    vals: List[float] = []
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s*(?:of)?\s*(?:overall|total|professional|relevant)?\s*experience",
        r"experience\s*(?:of|:)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?",
        r"(\d+(?:\.\d+)?)\s*\+\s*years?\s+(?:in|of|with)\b",
        r"(?:over|more than)\s+(\d+(?:\.\d+)?)\s*years?",
    ]
    for p in patterns:
        vals.extend(float(x) for x in re.findall(p, n))
    vals = [v for v in vals if 0 <= v <= 50]
    explicit = max(vals) if vals else None
    dated = _experience_from_dates(resume)
    return explicit if explicit is not None else dated

def detect_name(text: str, filename: str) -> str:
    lines = [re.sub(r"\s+"," ",x).strip() for x in text.splitlines() if x.strip()]
    for line in lines[:14]:
        if 2 <= len(line.split()) <= 5 and len(line) < 60 and not any(k in line.lower() for k in ["resume","curriculum","summary","profile","email","phone","mobile","skills"]):
            if re.fullmatch(r"[A-Za-z .'-]+", line):
                return line.title()
    return Path(filename).stem.replace("_"," ").replace("-"," ").title()

def detect_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""

def detect_phone(text: str) -> str:
    compact = re.sub(r"[() ]","", text)
    m = re.search(r"(?:\+?91[\s-]?)?[6-9]\d{9}", compact)
    return m.group(0) if m else ""


def _label_value(text: str, labels: List[str], max_len: int = 100) -> str:
    for label in labels:
        m = re.search(rf"(?im)^\s*(?:{label})\s*[:\-–|]\s*([^\n\r]{{1,{max_len}}})", text)
        if m:
            value = re.sub(r"\s+", " ", m.group(1)).strip(" |:-")
            if value:
                return value
    return ""

def _money_value(text: str, labels: List[str]) -> str:
    value = _label_value(text, labels, 55)
    if value:
        return value
    label = "|".join(labels)
    m = re.search(rf"(?i)(?:{label})\s*(?:is|of|:|-)?\s*(?:inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lakh|lac|k|pa)?", text)
    if not m:
        return ""
    return (m.group(1) + (" " + m.group(2) if m.group(2) else "")).strip()

def _detect_education(text: str) -> Dict[str,str]:
    patterns = [
        (r"(?i)\b(?:ph\.?d|doctor(?:ate)?\s+of\s+philosophy)\b", "PHD", "PG"),
        (r"(?i)\b(?:m\.?tech|master\s+of\s+technology)\b", "MTECH", "PG"),
        (r"(?i)\b(?:m\.?e\.?|master\s+of\s+engineering)\b", "ME", "PG"),
        (r"(?i)\b(?:mca|master\s+of\s+computer\s+applications?)\b", "MCA", "PG"),
        (r"(?i)\b(?:mba|master\s+of\s+business\s+administration)\b", "MBA", "PG"),
        (r"(?i)\b(?:m\.?sc|master\s+of\s+science)\b", "MSC", "PG"),
        (r"(?i)\b(?:b\.?tech|bachelor\s+of\s+technology)\b", "BTECH", "UG"),
        (r"(?i)\b(?:b\.?e\.?|bachelor\s+of\s+engineering)\b", "BE", "UG"),
        (r"(?i)\b(?:bca|bachelor\s+of\s+computer\s+applications?)\b", "BCA", "UG"),
        (r"(?i)\b(?:b\.?sc|bachelor\s+of\s+science)\b", "BSC", "UG"),
        (r"(?i)\b(?:b\.?com|bachelor\s+of\s+commerce)\b", "BCOM", "UG"),
        (r"(?i)\b(?:b\.?a\.?|bachelor\s+of\s+arts)\b", "BA", "UG"),
    ]
    found = []
    for pattern, code, level in patterns:
        if re.search(pattern, text):
            found.append((code, level))
    ug = next((code for code, level in found if level == "UG"), "")
    pg = next((code for code, level in found if level == "PG"), "")
    return {"ug": ug, "highest_qualification": pg or ug}


def _detect_location(text: str) -> str:
    labelled = _label_value(text, [r"current\s*location", r"present\s*location", r"location"], 70)
    if labelled:
        return labelled
    cities = [
        "Chennai","Bengaluru","Bangalore","Hyderabad","Pune","Mumbai","Delhi","New Delhi",
        "Noida","Gurugram","Gurgaon","Kolkata","Coimbatore","Kochi","Ahmedabad","Indore",
        "Bhopal","Jaipur","Trivandrum","Thiruvananthapuram","Mysuru","Mysore"
    ]
    top = "\n".join([x.strip() for x in text.splitlines()[:30] if x.strip()])
    for city in cities:
        if re.search(r"(?i)(?<![A-Za-z])" + re.escape(city) + r"(?![A-Za-z])", top):
            return "Bengaluru" if city.lower() == "bangalore" else "Gurugram" if city.lower() == "gurgaon" else city
    return ""


def _latest_experience(text: str) -> Dict[str,str]:
    lines = [re.sub(r"\s+", " ", x).strip(" \t•") for x in text.splitlines()]
    date_re = re.compile(r"(?i)\b(?:0?[1-9]|1[0-2])[/\-.](?:19|20)\d{2}\s*(?:-|–|to)\s*(?:(?:0?[1-9]|1[0-2])[/\-.](?:19|20)\d{2}|present|current)\b")
    for i, line in enumerate(lines):
        if not line or not date_re.search(line):
            continue
        title = date_re.sub("", line).strip(" ,-–|")
        title = re.sub(r"\s+,\s*$", "", title).strip()
        company_line = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            cand = lines[j].strip()
            if not cand or cand.lower() in {"experience", "work experience", "professional experience"}:
                continue
            if cand.startswith(("•", "-")):
                continue
            company_line = cand
            break
        company, location = company_line, ""
        if company_line and "," in company_line:
            parts = [p.strip() for p in company_line.split(",") if p.strip()]
            if parts:
                company = parts[0]
                if len(parts) > 1:
                    location = parts[-1]
        return {"current_designation": title, "current_organization": company, "current_location": location}
    return {"current_designation":"", "current_organization":"", "current_location":""}

def extract_profile_details(text: str, filename: str) -> Dict[str,Any]:
    edu = _detect_education(text)
    latest = _latest_experience(text)
    linkedin = ""
    m = re.search(r"(?i)(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_\-%/]+", text)
    if m:
        linkedin = m.group(0)
        if not linkedin.lower().startswith("http"):
            linkedin = "https://" + linkedin
    notice = _label_value(text, [r"notice\s*period", r"np"], 45)
    if not notice and re.search(r"(?i)\bimmediate(?:ly)?\s+(?:available|joiner|joining)\b|\bimmediate joiner\b", text):
        notice = "Immediate"
    current_org = _label_value(text, [r"current\s*(?:organization|organisation|company)", r"present\s*(?:organization|organisation|company)"], 90) or latest["current_organization"]
    current_role = _label_value(text, [r"current\s*(?:designation|role|title)", r"designation", r"job\s*title"], 90) or latest["current_designation"]
    current_loc = _label_value(text, [r"current\s*location", r"present\s*location"], 60) or latest["current_location"] or _detect_location(text)
    summary = ""
    sm = re.search(r"(?is)\b(?:summary|professional summary|profile summary)\b\s*[:\-]?\s*(.{40,800}?)(?=\n\s*(?:skills?|experience|employment|education|projects?|certifications?)\b)", text)
    if sm:
        summary = re.sub(r"\s+", " ", sm.group(1)).strip()[:700]
    details = {
        "candidate_full_name": detect_name(text, filename),
        "contact_no": detect_phone(text),
        "email_id": detect_email(text),
        "total_experience": parse_candidate_years(text),
        "relevant_experience": _label_value(text, [r"relevant\s*(?:experience|exp)"], 40),
        "current_organization": current_org,
        "current_designation": current_role,
        "current_company_experience": _label_value(text, [r"current\s*company\s*(?:experience|exp)"], 40),
        "current_ctc": _money_value(text, [r"current\s*ctc", r"present\s*ctc"]),
        "expected_ctc": _money_value(text, [r"expected\s*ctc", r"expecting\s*ctc"]),
        "holding_offers": _label_value(text, [r"holding\s*offers?", r"offers?\s*in\s*hand", r"offer\s*in\s*hand"], 80),
        "notice_period": notice,
        "lwd": _label_value(text, [r"lwd", r"last\s*working\s*day"], 45),
        "tentative_doj": _label_value(text, [r"tentative\s*doj", r"date\s*of\s*joining", r"doj"], 45),
        "native_location": _label_value(text, [r"native\s*location", r"native\s*place"], 60),
        "current_location": current_loc,
        "preferred_location": _label_value(text, [r"preferred\s*location", r"preferred\s*locations"], 100),
        "linkedin_id": linkedin,
        "profile_link": linkedin,
        "ug": edu["ug"],
        "highest_qualification": edu["highest_qualification"],
        "skills": ", ".join(find_skills(text)),
        "profile_summary": summary,
    }
    return details

def semantic_scores(jd: str, resumes: List[str]) -> List[float]:
    try:
        mat = TfidfVectorizer(stop_words="english", ngram_range=(1,2), max_features=12000).fit_transform(
            [normalize(jd)] + [normalize(r) for r in resumes]
        )
        return [float(x) for x in cosine_similarity(mat[0:1], mat[1:]).flatten()]
    except Exception:
        return [0.0] * len(resumes)

def rating(score: float) -> str:
    return "Strong" if score >= 75 else "Average" if score >= 55 else "Weak"

def recent_skill_evidence(resume: str, matched: List[str]) -> List[str]:
    n = normalize(resume)
    pos = n.find("experience")
    work = n[pos + len("experience"):] if pos >= 0 else n
    stops = []
    for marker in [" education ", " certifications ", " certification ", " awards ", " projects ", " academic ", " personal details "]:
        p = work.find(marker)
        if p > 0:
            stops.append(p)
    if stops:
        work = work[:min(stops)]
    zone = work[:max(500, int(len(work) * 0.55))]
    year = datetime.utcnow().year
    chunks = re.findall(rf".{{0,300}}(?:present|current|currently|{year}|{year-1}).{{0,500}}", work)
    if chunks:
        zone += " " + " ".join(chunks)
    z = " " + zone + " "
    recent = []
    for skill in matched:
        phrases = SKILL_SYNONYMS.get(skill, [skill])
        if any(_contains_phrase(z, p) for p in phrases):
            recent.append(skill)
    return recent

def score_resume(jd: str, resume: str, sim: float) -> Dict[str,Any]:
    req = find_skills(jd)
    got = find_skills(resume)
    matched = [s for s in req if s in got]
    missing = [s for s in req if s not in got]
    skill_cov = len(matched) / len(req) if req else 0.5
    reqy = parse_required_years(jd)
    cy = parse_candidate_years(resume)
    if reqy is None:
        exp_fit = 0.80 if cy is not None else 0.60
    elif cy is None:
        exp_fit = 0.45
    else:
        exp_fit = min(cy / max(reqy, 1), 1.0)
    recent_skills = recent_skill_evidence(resume, matched)
    recent_fit = len(recent_skills) / len(matched) if matched else 0.0
    semantic_fit = min(max(sim / 0.55, 0.0), 1.0)
    total = 20 * semantic_fit + 45 * skill_cov + 20 * exp_fit + 15 * recent_fit
    total = round(max(0, min(total, 100)), 1)
    risks = []
    if missing:
        risks.append("Missing/unclear JD skills: " + ", ".join(missing[:8]))
    if cy is None:
        risks.append("Total years of experience could not be reliably extracted; verify manually.")
    if reqy is not None and cy is not None and cy < reqy:
        risks.append(f"Resume indicates ~{cy:g} years vs JD minimum ~{reqy:g} years.")
    if matched and recent_fit < 0.45:
        risks.append("Several matched skills are not clearly evidenced in the recent experience section.")
    if not risks:
        risks.append("No major resume-level gap detected; validate depth, notice period, compensation and motivation during screening.")
    evidence = []
    if req:
        evidence.append(f"Matched {len(matched)}/{len(req)} detected JD skills ({round(skill_cov*100)}%).")
    if recent_skills:
        evidence.append("Recent experience evidence: " + ", ".join(recent_skills[:8]) + ".")
    if cy is not None:
        evidence.append(f"Estimated/declared total experience: ~{cy:g} years.")
    evidence.append(f"Raw semantic similarity: {round(sim*100,1)}%; calibrated semantic fit: {round(semantic_fit*100,1)}%.")
    focus = missing[:2] + [s for s in matched[:3] if s not in missing]
    questions = [
        f"Describe your most recent hands-on work with {s}. What did you personally own, and what was the outcome?"
        for s in focus
    ][:5]
    if not questions:
        questions = ["Walk me through the most relevant recent project or hiring assignment and what you personally owned."]
    return {
        "score": total,
        "rating": rating(total),
        "semantic_similarity": round(sim*100,1),
        "semantic_fit": round(semantic_fit*100,1),
        "skill_coverage": round(skill_cov*100,1),
        "experience_fit": round(exp_fit*100,1),
        "recent_evidence": round(recent_fit*100,1),
        "candidate_years": cy,
        "required_years": reqy,
        "matched_skills": matched,
        "missing_skills": missing,
        "recent_skills": recent_skills,
        "risks": risks,
        "evidence": evidence,
        "screening_questions": questions,
    }

def _decode_ai_details(value: Optional[str]):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None

def _candidate_dict(row: sqlite3.Row) -> Dict[str,Any]:
    d = dict(row)
    d["ai_evaluation"] = _decode_ai_details(d.pop("ai_details", None))
    d["profile_details"] = _decode_ai_details(d.get("profile_details")) or {}
    return d


def _candidate_duplicate(con: sqlite3.Connection, email: str = "", phone: str = ""):
    email = (email or "").strip().lower()
    phone_digits = re.sub(r"\D", "", phone or "")[-10:]
    if email:
        row = con.execute("SELECT id,name,email,phone FROM candidates WHERE lower(trim(email))=? LIMIT 1", (email,)).fetchone()
        if row:
            return row
    if phone_digits:
        rows = con.execute("SELECT id,name,email,phone FROM candidates WHERE phone IS NOT NULL AND phone<>''").fetchall()
        for row in rows:
            if re.sub(r"\D", "", row["phone"] or "")[-10:] == phone_digits:
                return row
    return None

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

class JobIn(BaseModel):
    title: str
    department: str = ""
    location: str = ""
    jd: str
    status: str = "Open"

class CandidateIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    experience: Optional[float] = None
    skills: str = ""
    source: str = ""
    notice_period: str = ""
    current_ctc: str = ""
    expected_ctc: str = ""
    resume_text: str = ""
    resume_filename: str = ""
    profile_details: Optional[Dict[str,Any]] = None
    job_id: Optional[int] = None
    stage: str = "Sourced"

class StageIn(BaseModel):
    stage: str

class NoteIn(BaseModel):
    note: str

class ExportPayload(BaseModel):
    results: List[Dict[str,Any]]


@app.post("/api/profile/parse")
async def parse_profile(profile: UploadFile = File(...)):
    name = profile.filename or "resume"
    data = await profile.read()
    try:
        text = extract_text(name, data)
    except Exception as e:
        raise HTTPException(400, str(e))
    if len(text.strip()) < 80:
        raise HTTPException(400, "Very little readable text was found in this profile. Try a text-based PDF or DOCX.")
    details = extract_profile_details(text, name)
    detected = [k for k,v in details.items() if v not in (None, "", [])]
    return {"filename": name,"details": details,"detected_count": len(detected),"detected_fields": detected,"resume_text": text,"message": "Profile details captured. Review the auto-filled fields before saving."}

@app.get("/api/stats")
def stats():
    con = db()
    c = con.cursor()
    out = {
        "jobs": c.execute("SELECT COUNT(*) FROM jobs WHERE status='Open'").fetchone()[0],
        "candidates": c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "interviews": c.execute("SELECT COUNT(*) FROM candidates WHERE stage='Interview'").fetchone()[0],
        "offers": c.execute("SELECT COUNT(*) FROM candidates WHERE stage='Offered'").fetchone()[0],
        "joined": c.execute("SELECT COUNT(*) FROM candidates WHERE stage='Joined'").fetchone()[0],
    }
    con.close()
    return out

@app.get("/api/jobs")
def list_jobs():
    con = db()
    rows = [dict(x) for x in con.execute("SELECT * FROM jobs ORDER BY id DESC")]
    con.close()
    return rows

@app.post("/api/jobs")
def create_job(x: JobIn):
    if len(x.jd.strip()) < 20:
        raise HTTPException(400, "Please enter a fuller JD")
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO jobs(title,department,location,jd,status,created_at) VALUES(?,?,?,?,?,?)",
        (x.title, x.department, x.location, x.jd, x.status, datetime.utcnow().isoformat())
    )
    con.commit()
    i = cur.lastrowid
    con.close()
    return {"id": i}

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    con = db()
    con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    con.commit()
    con.close()
    return {"ok": True}

@app.get("/api/candidates")
def list_candidates(job_id: Optional[int]=None, stage: Optional[str]=None, q: Optional[str]=None):
    sql = """SELECT c.*,j.title job_title FROM candidates c
             LEFT JOIN jobs j ON j.id=c.job_id WHERE 1=1"""
    args: List[Any] = []
    if job_id:
        sql += " AND c.job_id=?"
        args.append(job_id)
    if stage:
        sql += " AND c.stage=?"
        args.append(stage)
    if q:
        sql += " AND (c.name LIKE ? OR c.email LIKE ? OR c.skills LIKE ?)"
        v = f"%{q}%"
        args += [v,v,v]
    sql += " ORDER BY COALESCE(c.ai_score,0) DESC,c.id DESC"
    con = db()
    rows = [_candidate_dict(x) for x in con.execute(sql, args)]
    con.close()
    return rows

@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: int):
    con = db()
    row = con.execute(
        """SELECT c.*,j.title job_title,j.jd job_jd FROM candidates c
           LEFT JOIN jobs j ON j.id=c.job_id WHERE c.id=?""",
        (candidate_id,)
    ).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Candidate not found")
    out = _candidate_dict(row)
    out["notes"] = [dict(x) for x in con.execute(
        "SELECT * FROM notes WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)
    )]
    con.close()
    return out

@app.post("/api/candidates")
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
    cur = con.cursor()
    cur.execute(
        """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,source,notice_period,current_ctc,
           expected_ctc,profile_details,job_id,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (x.name,x.email,x.phone,x.experience,x.skills,x.resume_text,x.resume_filename,x.source,x.notice_period,x.current_ctc,
         x.expected_ctc,json.dumps(x.profile_details or {}),x.job_id,x.stage,now,now)
    )
    con.commit()
    i = cur.lastrowid
    con.close()
    return {"id": i}

@app.patch("/api/candidates/{candidate_id}/stage")
def update_stage(candidate_id: int, x: StageIn):
    if x.stage not in STAGES:
        raise HTTPException(400, "Invalid stage")
    con = db()
    con.execute(
        "UPDATE candidates SET stage=?,updated_at=? WHERE id=?",
        (x.stage, datetime.utcnow().isoformat(), candidate_id)
    )
    con.commit()
    con.close()
    return {"ok": True}

@app.delete("/api/candidates/{candidate_id}")
def delete_candidate(candidate_id: int):
    con = db()
    con.execute("DELETE FROM notes WHERE candidate_id=?", (candidate_id,))
    con.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
    con.commit()
    con.close()
    return {"ok": True}

@app.get("/api/candidates/{candidate_id}/notes")
def get_notes(candidate_id: int):
    con = db()
    rows = [dict(x) for x in con.execute(
        "SELECT * FROM notes WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)
    )]
    con.close()
    return rows

@app.post("/api/candidates/{candidate_id}/notes")
def add_note(candidate_id: int, x: NoteIn):
    if not x.note.strip():
        raise HTTPException(400, "Note is empty")
    con = db()
    con.execute(
        "INSERT INTO notes(candidate_id,note,created_at) VALUES(?,?,?)",
        (candidate_id, x.note.strip(), datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()
    return {"ok": True}

@app.post("/api/candidates/{candidate_id}/evaluate")
def evaluate_candidate(candidate_id: int):
    con = db()
    row = con.execute(
        """SELECT c.*,j.jd job_jd FROM candidates c
           LEFT JOIN jobs j ON j.id=c.job_id WHERE c.id=?""",
        (candidate_id,)
    ).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Candidate not found")
    if not row["resume_text"]:
        con.close()
        raise HTTPException(400, "This candidate has no stored resume text. Re-upload the resume through AI Shortlisting.")
    if not row["job_jd"]:
        con.close()
        raise HTTPException(400, "Assign this candidate to a job before running AI evaluation.")
    sim = semantic_scores(row["job_jd"], [row["resume_text"]])[0]
    result = score_resume(row["job_jd"], row["resume_text"], sim)
    con.execute(
        """UPDATE candidates SET experience=?,skills=?,ai_score=?,rating=?,ai_details=?,updated_at=? WHERE id=?""",
        (result["candidate_years"], ", ".join(find_skills(row["resume_text"])), result["score"],
         result["rating"], json.dumps(result), datetime.utcnow().isoformat(), candidate_id)
    )
    con.commit()
    con.close()
    return result

@app.post("/analyze")
async def analyze(
    jd: str = Form(...),
    resumes: List[UploadFile] = File(...),
    job_id: Optional[int] = Form(None),
    save_to_ats: bool = Form(False)
):
    if len(jd.strip()) < 50:
        raise HTTPException(400, "Please paste a more complete job description.")
    if not resumes:
        raise HTTPException(400, "Upload at least one resume.")
    texts, names, errors = [], [], []
    for f in resumes[:50]:
        data = await f.read()
        try:
            txt = extract_text(f.filename or "resume", data)
            if len(txt.strip()) < 80:
                raise ValueError("Very little readable text was extracted")
            texts.append(txt)
            names.append(f.filename or "resume")
        except Exception as e:
            errors.append(str(e))
    if not texts:
        raise HTTPException(400, "No resumes could be read. " + "; ".join(errors))
    sims = semantic_scores(jd, texts)
    results = []
    duplicates_skipped = []
    now = datetime.utcnow().isoformat()
    con = db() if save_to_ats else None
    for txt, name, sim in zip(texts, names, sims):
        s = score_resume(jd, txt, sim)
        s.update({"candidate": detect_name(txt, name), "file": name})
        results.append(s)
        if con:
            email = detect_email(txt)
            phone = detect_phone(txt)
            duplicate = _candidate_duplicate(con, email, phone)
            if duplicate:
                duplicates_skipped.append({"candidate": s["candidate"], "existing_id": duplicate["id"], "existing_name": duplicate["name"]})
                continue
            skills = ", ".join(find_skills(txt))
            con.execute(
                """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,
                   source,job_id,stage,ai_score,rating,ai_details,profile_details,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s["candidate"], email, phone, s["candidate_years"], skills,
                 txt, name, "Resume upload", job_id, "Sourced", s["score"], s["rating"],
                 json.dumps(s), json.dumps(extract_profile_details(txt, name)), now, now)
            )
    if con:
        con.commit()
        con.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    req = find_skills(jd)
    return {
        "summary": {
            "candidates": len(results),
            "required_skills": req,
            "required_years": parse_required_years(jd),
            "strong": sum(r["rating"] == "Strong" for r in results),
            "average": sum(r["rating"] == "Average" for r in results),
            "weak": sum(r["rating"] == "Weak" for r in results),
            "duplicates_skipped": len(duplicates_skipped),
        },
        "results": results,
        "errors": errors,
        "duplicates_skipped": duplicates_skipped,
        "methodology": "20% calibrated semantic fit + 45% JD skill coverage + 20% experience fit + 15% recent experience evidence. Raw semantic similarity is shown separately. Use as recruiter decision support, not an autonomous hiring decision."
    }


@app.get("/api/export/tracker")
def export_candidate_tracker():
    con = db()
    rows = con.execute("""SELECT c.*,j.title job_title,j.department job_department
                          FROM candidates c LEFT JOIN jobs j ON j.id=c.job_id
                          ORDER BY c.id ASC""").fetchall()
    con.close()
    export_rows = []
    for i, row in enumerate(rows, 1):
        c = dict(row)
        p = _decode_ai_details(c.get("profile_details")) or {}
        a = _decode_ai_details(c.get("ai_details")) or {}
        created = (c.get("created_at") or "")[:10]
        export_rows.append({
            "S No": i,
            "Date": created,
            "Client": p.get("client", ""),
            "Position Worked": c.get("job_title") or p.get("role_name", ""),
            "Tech Stack": c.get("skills") or "",
            "Recruiter": p.get("recruiter_name", ""),
            "Resource Name": c.get("name") or "",
            "Contact Number": c.get("phone") or "",
            "Email": c.get("email") or "",
            "Current Company": p.get("current_organization", ""),
            "Current Designation": p.get("current_designation", ""),
            "Total Experience": c.get("experience") if c.get("experience") is not None else p.get("total_experience", ""),
            "Relevant Experience": p.get("relevant_experience", ""),
            "Current Company Experience": p.get("current_company_experience", ""),
            "Current CTC": c.get("current_ctc") or p.get("current_ctc", ""),
            "Expected CTC": c.get("expected_ctc") or p.get("expected_ctc", ""),
            "Offer in Hand": p.get("holding_offers", ""),
            "Last Appraisal": p.get("last_appraisal", ""),
            "Notice Period": c.get("notice_period") or p.get("notice_period", ""),
            "Native Location": p.get("native_location", ""),
            "Current Location": p.get("current_location", ""),
            "Preferred Location": p.get("preferred_location", ""),
            "UG": p.get("ug", ""),
            "Highest Qualification": p.get("highest_qualification", ""),
            "LinkedIn ID": p.get("linkedin_id", ""),
            "Profile Submission Date": created,
            "Screening Status": p.get("screening_status", ""),
            "Interview Level": p.get("interview_level", ""),
            "Status": c.get("stage") or "",
            "Offer": p.get("offer", ""),
            "DOJ": p.get("tentative_doj", ""),
            "Remarks": p.get("remarks", ""),
            "AI Score": c.get("ai_score") if c.get("ai_score") is not None else a.get("score", ""),
            "AI Rating": c.get("rating") or a.get("rating", ""),
            "Skill Match %": a.get("skill_coverage", ""),
            "Experience Fit %": a.get("experience_fit", ""),
            "Matched Skills": ", ".join(a.get("matched_skills", [])),
            "Missing Skills": ", ".join(a.get("missing_skills", [])),
            "Risks / Points to Verify": " | ".join(a.get("risks", [])),
            "Suggested Screening Questions": " | ".join(a.get("screening_questions", [])),
        })
    out = io.BytesIO()
    df = pd.DataFrame(export_rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "S No","Date","Client","Position Worked","Tech Stack","Recruiter","Resource Name","Contact Number","Email",
            "Current Company","Current Designation","Total Experience","Relevant Experience","Current Company Experience",
            "Current CTC","Expected CTC","Offer in Hand","Last Appraisal","Notice Period","Native Location","Current Location",
            "Preferred Location","UG","Highest Qualification","LinkedIn ID","Profile Submission Date","Screening Status",
            "Interview Level","Status","Offer","DOJ","Remarks","AI Score","AI Rating","Skill Match %","Experience Fit %",
            "Matched Skills","Missing Skills","Risks / Points to Verify","Suggested Screening Questions"
        ])
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Candidate Tracker")
        ws = writer.book["Candidate Tracker"]
        from openpyxl.styles import PatternFill, Font, Alignment
        header_fill = PatternFill("solid", fgColor="000000")
        ai_fill = PatternFill("solid", fgColor="C00000")
        white_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = ai_fill if cell.column >= 33 else header_fill
            cell.font = white_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            letter = col[0].column_letter
            max_len = max(len(str(cell.value or "")) for cell in col[:100])
            ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 38)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment; filename=ShortlistAI_Candidate_Tracker.xlsx"}
    )


@app.post("/export")
def export_excel(payload: ExportPayload):
    rows = []
    for i, r in enumerate(payload.results, 1):
        rows.append({
            "Rank": i,
            "Candidate": r.get("candidate"),
            "Score": r.get("score"),
            "Rating": r.get("rating"),
            "Candidate Years": r.get("candidate_years"),
            "Required Years": r.get("required_years"),
            "Semantic Similarity %": r.get("semantic_similarity"),
            "Calibrated Semantic Fit %": r.get("semantic_fit"),
            "Skill Coverage %": r.get("skill_coverage"),
            "Experience Fit %": r.get("experience_fit"),
            "Recent Evidence %": r.get("recent_evidence"),
            "Matched Skills": ", ".join(r.get("matched_skills", [])),
            "Missing Skills": ", ".join(r.get("missing_skills", [])),
            "Recent Skills": ", ".join(r.get("recent_skills", [])),
            "Risks": " | ".join(r.get("risks", [])),
            "Screening Questions": " | ".join(r.get("screening_questions", [])),
        })
    out = io.BytesIO()
    pd.DataFrame(rows).to_excel(out, index=False)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment; filename=ShortlistAI_results.xlsx"}
    )
