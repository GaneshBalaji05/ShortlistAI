# Deploy ShortlistAI on Render

## Files Render needs
- `main.py` — FastAPI backend
- `requirements.txt` — Python packages
- `static/` — mobile/PWA interface
- `render.yaml` — Render deployment configuration

## Recommended GitHub repository layout
Upload the CONTENTS of this folder to the root of a GitHub repository. Do not upload them inside another nested folder.

## Render settings (manual route)
- Service type: Web Service
- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/`
- Plan for testing: Free

Once Render finishes deployment, open the generated `https://<service-name>.onrender.com` URL on Android Chrome. The PWA install option should then be available.
