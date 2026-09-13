import asyncio
import json
import os
import sqlite3
import tempfile
from http.cookies import SimpleCookie

from fastapi import FastAPI, HTTPException, Response

import auth_runtime
import tenant_security


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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE activity_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO jobs(title,status,created_at) VALUES('Legacy Demo Role','Open','2026-09-13');
        INSERT INTO candidates(name,email,job_id,source,created_at,updated_at)
        VALUES('Legacy Demo Candidate','legacy@example.test',1,'Legacy','2026-09-13','2026-09-13');
        """
    )
    con.commit()
    con.close()


def cookie_value(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[tenant_security.SESSION_COOKIE].value


async def request(middleware, path, cookie="", headers=None):
    headers = headers or {}
    raw_headers = [(key.lower().encode(), str(value).encode()) for key, value in headers.items()]
    if cookie:
        raw_headers.append((b"cookie", f"{tenant_security.SESSION_COOKIE}={cookie}".encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}") if body else {}


def run():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        legacy_schema(path)
        auth_runtime.DB_PATH = path
        tenant_security._schema_db = None

        auth_app = FastAPI()
        auth_runtime.install_auth_routes(auth_app)
        register = endpoint(auth_app, "/api/auth/register", "POST")
        login = endpoint(auth_app, "/api/auth/login", "POST")
        logout = endpoint(auth_app, "/api/auth/logout", "POST")

        first_response = Response()
        first = register(
            auth_runtime.RegisterIn(
                full_name="Workspace One",
                email="one@example.com",
                password="Secure123",
                confirm_password="Secure123",
                workspace_name="Workspace One",
            ),
            first_response,
        )
        assert first["ok"] is True
        assert "token" not in first
        assert "httponly" in first_response.headers["set-cookie"].lower()
        cookie_one = cookie_value(first_response)

        second_response = Response()
        second = register(
            auth_runtime.RegisterIn(
                full_name="Workspace Two",
                email="two@example.com",
                password="Secure123",
                confirm_password="Secure123",
                workspace_name="Workspace Two",
            ),
            second_response,
        )
        assert second["ok"] is True
        cookie_two = cookie_value(second_response)

        demo_response = Response()
        demo = login(auth_runtime.LoginIn(email="demo@shortlist.ai", password="shortlist123", remember=True), demo_response)
        assert demo.get("demo") is True
        cookie_demo = cookie_value(demo_response)

        async def downstream(scope, receive, send):
            path_value = scope["path"]
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            status = 200
            payload = {}
            con = tenant_security.workspace_db()
            try:
                if path_value == "/api/test/jobs":
                    payload = {"titles": [r["title"] for r in con.execute("SELECT title FROM jobs ORDER BY id")]}
                elif path_value == "/api/test/jobs/create":
                    cur = con.execute(
                        "INSERT INTO jobs(title,status,created_at) VALUES(?,?,?)",
                        (headers.get("x-title", "Untitled"), "Open", "2026-09-13"),
                    )
                    con.commit()
                    payload = {"id": int(cur.lastrowid)}
                elif path_value == "/api/test/candidates":
                    payload = {"names": [r["name"] for r in con.execute("SELECT name FROM candidates ORDER BY id")]}
                elif path_value == "/api/test/candidates/create":
                    try:
                        cur = con.execute(
                            "INSERT INTO candidates(name,email,job_id,source,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                            (
                                headers.get("x-name", "Candidate"),
                                headers.get("x-email", ""),
                                int(headers.get("x-job-id", "0")),
                                "Test",
                                "2026-09-13",
                                "2026-09-13",
                            ),
                        )
                        con.commit()
                        payload = {"id": int(cur.lastrowid)}
                    except HTTPException as exc:
                        con.rollback()
                        status = exc.status_code
                        payload = {"detail": exc.detail}
                else:
                    payload = {"ok": True}
            finally:
                con.close()
            body = json.dumps(payload).encode()
            await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})

        middleware = tenant_security.SessionTenantMiddleware(downstream)

        status, _ = asyncio.run(request(middleware, "/api/test/jobs"))
        assert status == 401
        status, _ = asyncio.run(request(middleware, "/app"))
        assert status == 303

        status, data = asyncio.run(request(middleware, "/api/test/jobs", cookie_one))
        assert status == 200 and data["titles"] == []
        status, data = asyncio.run(request(middleware, "/api/test/jobs", cookie_demo))
        assert status == 200 and data["titles"] == ["Legacy Demo Role"]

        status, one_job = asyncio.run(request(middleware, "/api/test/jobs/create", cookie_one, {"x-title": "Java Engineer"}))
        assert status == 200
        status, data = asyncio.run(request(middleware, "/api/test/jobs", cookie_two))
        assert data["titles"] == []

        status, cross = asyncio.run(
            request(
                middleware,
                "/api/test/candidates/create",
                cookie_two,
                {"x-name": "Cross Tenant", "x-email": "cross@example.test", "x-job-id": one_job["id"]},
            )
        )
        assert status == 404
        assert "workspace" in cross["detail"].lower()

        status, two_job = asyncio.run(request(middleware, "/api/test/jobs/create", cookie_two, {"x-title": "Python Engineer"}))
        assert status == 200
        status, _ = asyncio.run(
            request(
                middleware,
                "/api/test/candidates/create",
                cookie_two,
                {"x-name": "Bob", "x-email": "bob@example.test", "x-job-id": two_job["id"]},
            )
        )
        assert status == 200
        status, data = asyncio.run(request(middleware, "/api/test/candidates", cookie_two))
        assert data["names"] == ["Bob"]
        status, data = asyncio.run(request(middleware, "/api/test/candidates", cookie_one))
        assert data["names"] == []

        logout_response = Response()
        logout(auth_runtime.TokenIn(token=cookie_one), logout_response, None)
        status, _ = asyncio.run(request(middleware, "/api/test/jobs", cookie_one))
        assert status == 401

        print("Tenant session/isolation tests passed")
    finally:
        tenant_security._schema_db = None
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    run()
