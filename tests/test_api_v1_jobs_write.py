import asyncio
import json
import os
import sqlite3
import tempfile
from http.cookies import SimpleCookie

from fastapi import FastAPI, Response

import auth_runtime
import tenant_security
from shortlistai.api.v1 import install_api_v1


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
            department TEXT,
            location TEXT,
            jd TEXT NOT NULL,
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


async def request(app, method, path, *, cookie="", body=None):
    encoded = b""
    headers = []
    if cookie:
        headers.append((b"cookie", f"{tenant_security.SESSION_COOKIE}={cookie}".encode()))
    if body is not None:
        encoded = json.dumps(body).encode()
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(encoded)).encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    sent = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(raw.decode() or "{}") if raw else {}


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
        install_api_v1(app)
        auth_runtime.install_auth_routes(app)

        one, cookie_one = register(app, "Workspace One", "phase2-one@example.com", "Workspace One")
        two, cookie_two = register(app, "Workspace Two", "phase2-two@example.com", "Workspace Two")
        wid_one = int(one["user"]["workspace_id"])
        wid_two = int(two["user"]["workspace_id"])

        create_payload = {
            "title": "Java Engineer",
            "department": "Engineering",
            "location": "Chennai",
            "jd": "Build and maintain Java and Spring Boot services.",
            "status": "Open",
        }

        status, body = asyncio.run(request(app, "POST", "/api/v1/jobs", body=create_payload))
        assert status == 401, (status, body)
        assert "Authentication required" in body["detail"]

        injected = {**create_payload, "workspace_id": wid_two}
        status, body = asyncio.run(
            request(app, "POST", "/api/v1/jobs", cookie=cookie_one, body=injected)
        )
        assert status == 422, (status, body)

        status, body = asyncio.run(
            request(app, "POST", "/api/v1/jobs", cookie=cookie_one, body=create_payload)
        )
        assert status == 201, (status, body)
        first = body["data"]
        job_one = int(first["id"])
        created_at = first["created_at"]
        assert first["title"] == "Java Engineer"
        assert first["department"] == "Engineering"
        assert first["status"] == "Open"
        assert "workspace_id" not in first

        second_payload = {
            "title": "Python Engineer",
            "department": "Platform",
            "location": "Bengaluru",
            "jd": "Build reliable Python and FastAPI services for the platform.",
        }
        status, body = asyncio.run(
            request(app, "POST", "/api/v1/jobs", cookie=cookie_two, body=second_payload)
        )
        assert status == 201, (status, body)
        job_two = int(body["data"]["id"])
        assert body["data"]["status"] == "Open"

        status, body = asyncio.run(request(app, "GET", "/api/v1/jobs", cookie=cookie_one))
        assert status == 200, (status, body)
        assert body["meta"]["total"] == 1
        assert [row["id"] for row in body["data"]] == [job_one]

        status, body = asyncio.run(request(app, "GET", "/api/v1/jobs", cookie=cookie_two))
        assert status == 200, (status, body)
        assert body["meta"]["total"] == 1
        assert [row["id"] for row in body["data"]] == [job_two]

        status, body = asyncio.run(
            request(
                app,
                "PATCH",
                f"/api/v1/jobs/{job_one}",
                cookie=cookie_two,
                body={"status": "Closed"},
            )
        )
        assert status == 404, (status, body)
        assert body["detail"] == "Job not found"

        status, body = asyncio.run(
            request(
                app,
                "PATCH",
                f"/api/v1/jobs/{job_one}",
                cookie=cookie_one,
                body={"title": "Senior Java Engineer", "department": None, "status": "On Hold"},
            )
        )
        assert status == 200, (status, body)
        updated = body["data"]
        assert updated["title"] == "Senior Java Engineer"
        assert updated["department"] is None
        assert updated["status"] == "On Hold"
        assert updated["created_at"] == created_at
        assert "workspace_id" not in updated

        status, body = asyncio.run(
            request(app, "PATCH", f"/api/v1/jobs/{job_one}", cookie=cookie_one, body={})
        )
        assert status == 400, (status, body)
        assert body["detail"] == "Provide at least one job field to update"

        status, body = asyncio.run(
            request(
                app,
                "PATCH",
                f"/api/v1/jobs/{job_one}",
                cookie=cookie_one,
                body={"workspace_id": wid_two},
            )
        )
        assert status == 422, (status, body)

        status, body = asyncio.run(
            request(
                app,
                "PATCH",
                f"/api/v1/jobs/{job_one}",
                cookie=cookie_one,
                body={"title": None},
            )
        )
        assert status == 422, (status, body)

        status, body = asyncio.run(
            request(app, "GET", f"/api/v1/jobs/{job_one}", cookie=cookie_one)
        )
        assert status == 200, (status, body)
        assert body["data"]["title"] == "Senior Java Engineer"
        assert body["data"]["status"] == "On Hold"

        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        row_one = con.execute("SELECT * FROM jobs WHERE id=?", (job_one,)).fetchone()
        row_two = con.execute("SELECT * FROM jobs WHERE id=?", (job_two,)).fetchone()
        con.close()
        assert int(row_one["workspace_id"]) == wid_one
        assert int(row_two["workspace_id"]) == wid_two
        assert row_one["created_at"] == created_at
        assert row_one["status"] == "On Hold"
        assert row_two["status"] == "Open"

        print("API v1 Phase 2A job write isolation and validation tests passed")
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
