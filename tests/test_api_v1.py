import asyncio
import json
import os
import sqlite3
import tempfile
import urllib.parse
from http.cookies import SimpleCookie

from fastapi import FastAPI, Response

import auth_runtime
import tenant_security
from shortlistai.api.v1 import install_api_v1, resolved_route_paths


def endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Missing route {method} {path}")


def legacy_schema(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE candidates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            job_id INTEGER,
            source TEXT,
            stage TEXT DEFAULT 'Sourced',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    con.commit()
    con.close()


def cookie_value(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[tenant_security.SESSION_COOKIE].value


async def request(app, path, cookie="", query=None):
    query_string = urllib.parse.urlencode(query or {}).encode()
    headers = []
    if cookie:
        headers.append((b"cookie", f"{tenant_security.SESSION_COOKIE}={cookie}".encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}") if body else {}


def register(app, name, email, workspace):
    response = Response()
    payload = auth_runtime.RegisterIn(
        full_name=name,
        email=email,
        password="Secure123",
        confirm_password="Secure123",
        workspace_name=workspace,
    )
    result = endpoint(app, "/api/auth/register", "POST")(payload, response)
    return result, cookie_value(response)


def run():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    previous_path = auth_runtime.DB_PATH
    previous_env = os.environ.get("SQLITE_PATH")
    try:
        legacy_schema(path)
        auth_runtime.DB_PATH = path
        os.environ["SQLITE_PATH"] = path
        tenant_security._schema_db = None

        app = FastAPI()
        # Application composition is explicit: versioned routes first, then auth/security.
        # This keeps router registration independent from legacy import side effects while
        # the middleware still protects every /api/v1 path.
        install_api_v1(app)
        auth_runtime.install_auth_routes(app)

        required_v1 = {
            "/api/v1/health",
            "/api/v1/me",
            "/api/v1/candidates",
            "/api/v1/candidates/{candidate_id}",
            "/api/v1/jobs",
            "/api/v1/jobs/{job_id}",
        }
        route_paths = resolved_route_paths(app.routes)
        assert required_v1 <= route_paths, f"Missing API v1 routes: {sorted(required_v1 - route_paths)}"

        # Independently prove that the actual uvicorn main:app runtime receives the same
        # complete v1 surface. This prevents the isolated test composition from masking a
        # production registration defect.
        import main as runtime_main
        production_paths = resolved_route_paths(runtime_main.app.routes)
        assert required_v1 <= production_paths, (
            f"Production runtime missing API v1 routes: {sorted(required_v1 - production_paths)}"
        )

        one, cookie_one = register(app, "Workspace One", "one-api@example.com", "Workspace One")
        two, cookie_two = register(app, "Workspace Two", "two-api@example.com", "Workspace Two")
        wid_one = int(one["user"]["workspace_id"])
        wid_two = int(two["user"]["workspace_id"])

        con = sqlite3.connect(path)
        now = "2026-09-14T10:00:00"
        job_one = con.execute(
            "INSERT INTO jobs(title,status,created_at,workspace_id) VALUES(?,?,?,?)",
            ("Java Engineer", "Open", now, wid_one),
        ).lastrowid
        job_two = con.execute(
            "INSERT INTO jobs(title,status,created_at,workspace_id) VALUES(?,?,?,?)",
            ("Python Engineer", "Open", now, wid_two),
        ).lastrowid
        candidate_one = con.execute(
            """INSERT INTO candidates(name,email,job_id,source,stage,created_at,updated_at,workspace_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            ("Alice", "alice@example.com", job_one, "Naukri", "Screened", now, now, wid_one),
        ).lastrowid
        candidate_two = con.execute(
            """INSERT INTO candidates(name,email,job_id,source,stage,created_at,updated_at,workspace_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            ("Bob", "bob@example.com", job_two, "LinkedIn", "Sourced", now, now, wid_two),
        ).lastrowid
        con.commit()
        con.close()

        status, body = asyncio.run(request(app, "/api/v1/candidates"))
        assert status == 401
        assert "Authentication required" in body["detail"]

        status, body = asyncio.run(request(app, "/api/v1/me", cookie_one))
        assert status == 200
        assert body["data"]["workspace_id"] == wid_one
        assert body["data"]["user_id"] == one["user"]["id"]

        status, body = asyncio.run(request(app, "/api/v1/candidates", cookie_one))
        assert status == 200
        assert body["meta"] == {"total": 1, "limit": 50, "offset": 0}
        assert [row["name"] for row in body["data"]] == ["Alice"]
        assert "workspace_id" not in body["data"][0]
        assert "resume_text" not in body["data"][0]

        status, body = asyncio.run(request(app, "/api/v1/candidates", cookie_two))
        assert status == 200
        assert [row["name"] for row in body["data"]] == ["Bob"]

        status, body = asyncio.run(request(app, f"/api/v1/candidates/{candidate_one}", cookie_two))
        assert status == 404
        assert body["detail"] == "Candidate not found"

        status, body = asyncio.run(request(app, f"/api/v1/candidates/{candidate_two}", cookie_two))
        assert status == 200
        assert body["data"]["name"] == "Bob"

        status, body = asyncio.run(request(app, "/api/v1/jobs", cookie_one, {"limit": 1, "offset": 0}))
        assert status == 200
        assert body["meta"] == {"total": 1, "limit": 1, "offset": 0}
        assert [row["title"] for row in body["data"]] == ["Java Engineer"]

        status, body = asyncio.run(request(app, f"/api/v1/jobs/{job_two}", cookie_one))
        assert status == 404
        assert body["detail"] == "Job not found"

        status, body = asyncio.run(request(app, "/api/v1/health", cookie_one))
        assert status == 200
        assert body["data"]["status"] == "ok"
        assert body["data"]["api_version"] == "v1"
        assert body["data"]["workspace_id"] == wid_one

        # Existing auth contract remains available while v1 is introduced.
        assert "/api/auth/session" in route_paths
        print("API v1 auth/workspace/read isolation tests passed")
    finally:
        auth_runtime.DB_PATH = previous_path
        if previous_env is None:
            os.environ.pop("SQLITE_PATH", None)
        else:
            os.environ["SQLITE_PATH"] = previous_env
        tenant_security._schema_db = None
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    run()
