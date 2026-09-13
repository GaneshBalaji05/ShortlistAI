from __future__ import annotations

import os
import sys
import types
import uuid
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException
from sqlalchemy import delete
from starlette.requests import Request

import auth_runtime
from shortlistai.db.models import Base
from shortlistai.db.runtime import get_engine_for_url, is_postgres_url, normalize_database_url


def endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Missing route {method} {path}")


def reset_request():
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/auth/forgot-password",
        "raw_path": b"/api/auth/forgot-password",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
        "root_path": "",
    })


def main() -> None:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not is_postgres_url(database_url):
        print("SKIP: PostgreSQL auth route regression requires DATABASE_URL")
        return

    suffix = uuid.uuid4().hex[:10]
    email = f"auth-route-{suffix}@example.test"
    workspace = f"Auth Route Workspace {suffix}"
    engine = get_engine_for_url(database_url)
    original_sender = auth_runtime._send_reset_email
    previous_public = os.environ.get("SHORTLISTAI_PUBLIC_URL")
    previous_main = sys.modules.get("main")
    sent = []
    workspace_id = None

    try:
        # tenant_security.install historically imports main to discover the legacy app. Keep
        # this isolated auth regression from importing the whole runtime entrypoint.
        sys.modules["main"] = types.SimpleNamespace()
        os.environ["SHORTLISTAI_PUBLIC_URL"] = "https://shortlistai.example"
        auth_runtime._send_reset_email = lambda recipient, reset_url: sent.append((recipient, reset_url)) or True

        app = FastAPI()
        auth_runtime.install_auth_routes(app)
        register = endpoint(app, "/api/auth/register", "POST")
        login = endpoint(app, "/api/auth/login", "POST")
        forgot = endpoint(app, "/api/auth/forgot-password", "POST")
        reset = endpoint(app, "/api/auth/reset-password", "POST")
        session = endpoint(app, "/api/auth/session", "POST")
        logout = endpoint(app, "/api/auth/logout", "POST")

        created = register(auth_runtime.RegisterIn(
            full_name="Postgres Auth User",
            email=email,
            password="OldPass123",
            confirm_password="OldPass123",
            workspace_name=workspace,
        ))
        assert created["ok"] is True
        workspace_id = int(created["user"]["workspace_id"])
        original_token = created["token"]
        assert session(auth_runtime.TokenIn(token=original_token))["workspace"] == workspace

        try:
            register(auth_runtime.RegisterIn(
                full_name="Duplicate",
                email=email.upper(),
                password="OldPass123",
                confirm_password="OldPass123",
                workspace_name="Duplicate Workspace",
            ))
            raise AssertionError("Case-insensitive duplicate email must be rejected")
        except HTTPException as exc:
            assert exc.status_code == 409

        response = forgot(auth_runtime.ForgotPasswordIn(email=email), reset_request())
        assert response["ok"] is True and len(sent) == 1
        token = parse_qs(urlparse(sent[0][1]).query)["reset_token"][0]
        changed = reset(auth_runtime.ResetPasswordIn(
            token=token,
            password="NewPass456",
            confirm_password="NewPass456",
        ))
        assert changed["ok"] is True

        try:
            session(auth_runtime.TokenIn(token=original_token))
            raise AssertionError("Password reset must revoke prior sessions")
        except HTTPException as exc:
            assert exc.status_code == 401

        try:
            login(auth_runtime.LoginIn(email=email, password="OldPass123", remember=True))
            raise AssertionError("Old password must be rejected")
        except HTTPException as exc:
            assert exc.status_code == 401

        logged = login(auth_runtime.LoginIn(email=email, password="NewPass456", remember=True))
        assert logged["ok"] is True
        assert logged["user"]["email"] == email
        logout(auth_runtime.TokenIn(token=logged["token"]))
        try:
            session(auth_runtime.TokenIn(token=logged["token"]))
            raise AssertionError("Logout must revoke the session")
        except HTTPException as exc:
            assert exc.status_code == 401

        print("PostgreSQL auth route regression OK")
    finally:
        auth_runtime._send_reset_email = original_sender
        if previous_public is None:
            os.environ.pop("SHORTLISTAI_PUBLIC_URL", None)
        else:
            os.environ["SHORTLISTAI_PUBLIC_URL"] = previous_public
        if previous_main is None:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = previous_main
        if workspace_id is not None:
            workspaces = Base.metadata.tables["workspaces"]
            with engine.begin() as connection:
                connection.execute(delete(workspaces).where(workspaces.c.id == workspace_id))


if __name__ == "__main__":
    main()
