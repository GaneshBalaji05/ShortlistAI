"""ShortlistAI runtime entrypoint.

Render currently starts the service with ``uvicorn main:app``. This package intentionally
shadows the legacy ``main.py`` module, loads that application unchanged, and then adds the
new branded login/workspace routing around it. This lets the UI evolve without disturbing
the ATS API implementation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.responses import HTMLResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_MAIN = PROJECT_ROOT / "main.py"

spec = importlib.util.spec_from_file_location("shortlistai_legacy_main", LEGACY_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load ShortlistAI application")
legacy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = legacy
spec.loader.exec_module(legacy)

app = legacy.app
BASE_DIR = legacy.BASE_DIR


def __getattr__(name: str):
    """Keep imports from the old single-file module working while the UI entrypoint evolves."""
    return getattr(legacy, name)


# Remove the legacy root page while preserving all APIs, static files and startup hooks.
app.router.routes = [
    route for route in app.router.routes
    if not (getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", set()) or set()))
]


@app.get("/", response_class=HTMLResponse)
def login_page():
    return (BASE_DIR / "static" / "login.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def ats_workspace():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("</head>", '<link rel="stylesheet" href="/static/theme-v2.css?v=1"/>\n</head>')
    html = html.replace("</body>", '<script src="/static/theme-v2.js?v=1"></script>\n</body>')
    return html
