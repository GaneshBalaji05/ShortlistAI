from fastapi.responses import HTMLResponse

from main import app, BASE_DIR

# Replace the existing root route from main.py with the branded login page,
# while keeping the ATS workspace available at /app.
app.router.routes = [
    route for route in app.router.routes
    if not (getattr(route, "path", None) == "/" and "GET" in getattr(route, "methods", set()))
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
