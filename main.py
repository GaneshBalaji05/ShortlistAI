from __future__ import annotations
import io, re, json, math
from pathlib import Path
from typing import List, Dict, Any

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
app = FastAPI(title="ShortlistAI MVP", version="0.1.0")
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
    "product management","jira","figma","agile","scrum","stakeholder management","roadmap","analytics"
]

ALIASES = {
    "react.js": "react", "reactjs": "react", "nodejs": "node.js", "node": "node.js",
    "gen ai": "genai", "generative artificial intelligence": "generative ai", "large language model": "llm", "large language models": "llm",
    "amazon web services": "aws", "google cloud": "gcp", "k8s": "kubernetes", "postgres": "postgresql",
    "restful api": "rest api", "restful apis": "rest api", "continuous integration": "ci/cd", "continuous delivery": "ci/cd"
}

STOP = set("a an the and or of in on to for with from by as is are be been being this that these those you we our your will would should can may must role job candidate experience years year work working knowledge strong good excellent hands hand responsibilities requirements required preferred plus team teams ability skills skill using use used development developer engineer engineering design build building maintain maintaining".split())


def normalize(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-")
    for src, dst in sorted(ALIASES.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"(?<![a-z0-9])" + re.escape(src) + r"(?![a-z0-9])", dst, text)
    text = re.sub(r"[^a-z0-9+#./\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        if ext == ".docx":
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        if ext in {".txt", ".md"}:
            return data.decode("utf-8", errors="ignore")
    except Exception as e:
        raise ValueError(f"Could not read {filename}: {e}")
    raise ValueError(f"Unsupported format for {filename}. Use PDF, DOCX, TXT or MD.")


def find_skills(text: str) -> List[str]:
    n = f" {normalize(text)} "
    found = []
    for skill in SKILLS:
        s = normalize(skill)
        if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", n):
            canonical = ALIASES.get(s, s)
            if canonical not in found:
                found.append(canonical)
    return found


def jd_keywords(text: str, limit: int = 18) -> List[str]:
    n = normalize(text)
    words = [w for w in re.findall(r"[a-z][a-z0-9+#./-]{2,}", n) if w not in STOP and not w.isdigit()]
    freq: Dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return [w for w,_ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:limit]]


def parse_required_years(jd: str) -> float | None:
    n = normalize(jd)
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*years?",
        r"(?:minimum|min|at least)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?",
        r"(\d+(?:\.\d+)?)\s*\+\s*years?",
        r"(\d+(?:\.\d+)?)\s*years?\s*(?:of)?\s*experience"
    ]
    for i,p in enumerate(patterns):
        m = re.search(p, n)
        if m:
            if i == 0:
                return float(m.group(1))
            return float(m.group(1))
    return None


def parse_candidate_years(resume: str) -> float | None:
    n = normalize(resume)
    vals = []
    for pat in [r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s*(?:of)?\s*(?:overall|total|professional|relevant)?\s*experience", r"experience\s*(?:of|:)\s*(\d+(?:\.\d+)?)\s*\+?\s*years?"]:
        vals += [float(x) for x in re.findall(pat, n)]
    vals = [v for v in vals if 0 <= v <= 50]
    return max(vals) if vals else None


def recent_skill_evidence(resume: str, required_skills: List[str]) -> Dict[str, bool]:
    n = normalize(resume)
    # Recent/current evidence heuristic: last 45% + any section containing current/present/latest.
    tail = n[int(len(n)*0.55):] if n else ""
    current_chunks = " ".join(re.findall(r".{0,250}(?:present|current|currently|latest).{0,450}", n))
    recent_zone = tail + " " + current_chunks
    out = {}
    for skill in required_skills:
        s = normalize(skill)
        out[skill] = bool(re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", recent_zone))
    return out


def semantic_scores(jd: str, resumes: List[str]) -> List[float]:
    docs = [normalize(jd)] + [normalize(r) for r in resumes]
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1,2), min_df=1, max_features=12000)
        mat = vec.fit_transform(docs)
        sims = cosine_similarity(mat[0:1], mat[1:]).flatten()
        return [float(x) for x in sims]
    except Exception:
        return [0.0] * len(resumes)


def rating(score: float) -> str:
    if score >= 75: return "Strong"
    if score >= 55: return "Average"
    return "Weak"


def build_questions(missing: List[str], matched: List[str], jd: str) -> List[str]:
    qs = []
    focus = missing[:3] + [s for s in matched[:3] if s not in missing]
    templates = {
        "react": "Describe a production React feature you owned end-to-end. What trade-offs did you make around state, rendering and performance?",
        "python": "Walk me through a production Python service you designed. How did you structure it for reliability, testing and maintainability?",
        "fastapi": "How have you designed FastAPI services for validation, async workloads, error handling and production observability?",
        "agentic ai": "Describe an agentic AI workflow you built. How did you handle tool use, state, guardrails and failure recovery?",
        "genai": "Give an example of a GenAI feature you shipped. How did you evaluate output quality, latency, cost and safety?",
        "generative ai": "Give an example of a Generative AI feature you shipped. How did you evaluate output quality, latency, cost and safety?",
        "aws": "Which AWS services have you used hands-on, and describe one architecture decision you personally made?",
        "kubernetes": "Describe how you have deployed and troubleshot a production workload on Kubernetes.",
        "cybersecurity": "Describe a security incident, threat-modeling exercise, or security control you personally handled and what changed as a result."
    }
    for s in focus:
        if s in templates:
            qs.append(templates[s])
        else:
            qs.append(f"Describe your most recent hands-on work with {s}. What did you personally build or own, and what was the outcome?")
    if not qs:
        qs.append("Walk me through the project in your current or most recent role that is most relevant to this position. What did you personally own?")
    return qs[:5]


def analyze_one(jd: str, resume: str, filename: str, sim: float, required_skills: List[str], required_years: float | None) -> Dict[str, Any]:
    rskills = find_skills(resume)
    matched = [s for s in required_skills if s in rskills]
    missing = [s for s in required_skills if s not in rskills]
    skill_cov = (len(matched) / len(required_skills)) if required_skills else 0.5
    recent = recent_skill_evidence(resume, required_skills)
    recent_matched = [s for s in matched if recent.get(s)]
    recent_score = (len(recent_matched) / len(matched)) if matched else 0.0
    cand_years = parse_candidate_years(resume)
    if required_years is None:
        exp_score = 0.75 if cand_years is not None else 0.55
    elif cand_years is None:
        exp_score = 0.45
    else:
        exp_score = min(cand_years / max(required_years, 1), 1.0)
    total = 45*sim + 35*skill_cov + 10*exp_score + 10*recent_score
    total = round(max(0, min(total, 100)), 1)

    risks = []
    if missing:
        risks.append("Missing/unclear JD skills: " + ", ".join(missing[:6]))
    if matched and recent_score < 0.45:
        risks.append("Several matched skills are not clearly evidenced in recent/current work.")
    if required_years is not None and cand_years is not None and cand_years < required_years:
        risks.append(f"Resume states ~{cand_years:g} years vs JD minimum ~{required_years:g} years.")
    if cand_years is None:
        risks.append("Total years of experience could not be reliably extracted; verify manually.")
    if not risks:
        risks.append("No major resume-level gap detected; validate depth during screening.")

    evidence = []
    if matched:
        evidence.append(f"Matched {len(matched)}/{len(required_skills) or len(matched)} detected JD skills.")
    if recent_matched:
        evidence.append("Recent/current evidence: " + ", ".join(recent_matched[:6]))
    if cand_years is not None:
        evidence.append(f"Resume states approximately {cand_years:g} years of experience.")

    return {
        "candidate": Path(filename).stem,
        "file": filename,
        "score": total,
        "rating": rating(total),
        "semantic_similarity": round(sim*100, 1),
        "skill_coverage": round(skill_cov*100, 1),
        "experience_fit": round(exp_score*100, 1),
        "recent_evidence": round(recent_score*100, 1),
        "candidate_years": cand_years,
        "required_years": required_years,
        "matched_skills": matched,
        "missing_skills": missing,
        "recent_skills": recent_matched,
        "risks": risks,
        "evidence": evidence,
        "screening_questions": build_questions(missing, matched, jd),
    }


@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/analyze")
async def analyze(jd: str = Form(...), resumes: List[UploadFile] = File(...)):
    if len(jd.strip()) < 50:
        raise HTTPException(status_code=400, detail="Please paste a more complete job description.")
    if not resumes:
        raise HTTPException(status_code=400, detail="Upload at least one resume.")
    if len(resumes) > 50:
        raise HTTPException(status_code=400, detail="MVP limit: 50 resumes per batch.")

    texts, names, errors = [], [], []
    for f in resumes:
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
        raise HTTPException(status_code=400, detail="No resumes could be read. " + "; ".join(errors))

    req_skills = find_skills(jd)
    req_years = parse_required_years(jd)
    sims = semantic_scores(jd, texts)
    results = [analyze_one(jd, txt, name, sim, req_skills, req_years) for txt,name,sim in zip(texts,names,sims)]
    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "summary": {
            "candidates": len(results),
            "required_skills": req_skills,
            "required_years": req_years,
            "jd_keywords": jd_keywords(jd),
            "strong": sum(r["rating"] == "Strong" for r in results),
            "average": sum(r["rating"] == "Average" for r in results),
            "weak": sum(r["rating"] == "Weak" for r in results),
        },
        "results": results,
        "errors": errors,
        "methodology": "45% semantic similarity + 35% JD skill coverage + 10% experience fit + 10% recent/current skill evidence. Use as recruiter decision support, not as an autonomous hiring decision."
    }


class ExportPayload(BaseModel):
    results: List[Dict[str, Any]]

@app.post("/export")
def export_excel(payload: ExportPayload):
    rows = []
    for r in payload.results:
        rows.append({
            "Rank": len(rows)+1,
            "Candidate": r.get("candidate"),
            "Score": r.get("score"),
            "Rating": r.get("rating"),
            "Candidate Years": r.get("candidate_years"),
            "Required Years": r.get("required_years"),
            "Semantic Similarity %": r.get("semantic_similarity"),
            "Skill Coverage %": r.get("skill_coverage"),
            "Recent Evidence %": r.get("recent_evidence"),
            "Matched Skills": ", ".join(r.get("matched_skills", [])),
            "Missing Skills": ", ".join(r.get("missing_skills", [])),
            "Recent Skills": ", ".join(r.get("recent_skills", [])),
            "Risks": " | ".join(r.get("risks", [])),
            "Screening Questions": " | ".join(r.get("screening_questions", [])),
        })
    df = pd.DataFrame(rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Shortlist")
        ws = writer.book["Shortlist"]
        ws.freeze_panes = "A2"
        for col in ws.columns:
            max_len = min(max((len(str(c.value or "")) for c in col), default=10) + 2, 55)
            ws.column_dimensions[col[0].column_letter].width = max(10, max_len)
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(vertical="top", wrap_text=True)
    out.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="ShortlistAI_results.xlsx"'}
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
