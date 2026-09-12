# ShortlistAI — Deployable MVP

ShortlistAI ranks resumes against a pasted job description and provides recruiter decision support.

## Core features
- Upload multiple PDF/DOCX/TXT/MD resumes
- 0–100 fit score
- Strong / Average / Weak grouping
- Skill coverage and missing skill analysis
- Current/recent skill evidence heuristic
- Experience fit
- Candidate-specific screening questions
- Excel export
- Android-installable PWA interface after HTTPS deployment

## Local run
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000

## Render deployment
See `DEPLOY_RENDER.md`.

## Important
This is recruiter decision-support software. Resume scoring is heuristic and should not make autonomous hiring decisions. Recruiters should review evidence and validate candidates manually.
