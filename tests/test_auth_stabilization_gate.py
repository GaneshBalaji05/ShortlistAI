import os
import tempfile
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Response
from starlette.requests import Request

import auth_runtime
import tenant_security


ROOT = Path(__file__).resolve().parents[1]


def endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Missing route {method} {path}")


def request(path, method="GET", cookie=""):
    headers = []
    if cookie:
        headers.append((b"cookie", f"{auth_runtime.SESSION_COOKIE}={cookie}".encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
            "root_path": "",
        }
    )


def cookie_value(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[auth_runtime.SESSION_COOKIE].value


def expect_http(status, fn):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
        return exc
    raise AssertionError(f"Expected HTTP {status}")


def run():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    previous_db = auth_runtime.DB_PATH
    previous_public = os.environ.get("SHORTLISTAI_PUBLIC_URL")
    previous_sender = auth_runtime._send_reset_email
    sent = []

    try:
        auth_runtime.DB_PATH = path
        tenant_security._schema_db = None
        os.environ["SHORTLISTAI_PUBLIC_URL"] = "https://shortlistai.example"
        auth_runtime._send_reset_email = lambda recipient, reset_url: sent.append((recipient, reset_url)) or True

        app = FastAPI()
        auth_runtime.install_auth_routes(app)
        register = endpoint(app, "/api/auth/register", "POST")
        login = endpoint(app, "/api/auth/login", "POST")
        browser_session = endpoint(app, "/api/auth/session", "GET")
        token_session = endpoint(app, "/api/auth/session", "POST")
        forgot = endpoint(app, "/api/auth/forgot-password", "POST")
        reset = endpoint(app, "/api/auth/reset-password", "POST")
        logout = endpoint(app, "/api/auth/logout", "POST")

        # Backend + Full Stack: successful account creation must establish a
        # cookie-backed session and each account must own a distinct workspace.
        response_one = Response()
        account_one = register(
            auth_runtime.RegisterIn(
                full_name="Auth Gate One",
                email="auth-one@example.test",
                password="Secure123",
                confirm_password="Secure123",
                workspace_name="Auth Gate One",
            ),
            response_one,
        )
        cookie_one = cookie_value(response_one)
        assert account_one["ok"] is True
        assert account_one["user"]["workspace_id"]
        assert "httponly" in response_one.headers["set-cookie"].lower()

        response_two = Response()
        account_two = register(
            auth_runtime.RegisterIn(
                full_name="Auth Gate Two",
                email="auth-two@example.test",
                password="Secure123",
                confirm_password="Secure123",
                workspace_name="Auth Gate Two",
            ),
            response_two,
        )
        assert account_two["user"]["workspace_id"] != account_one["user"]["workspace_id"]

        # Invalid credentials must fail without establishing a usable session.
        expect_http(
            401,
            lambda: login(auth_runtime.LoginIn(email="auth-one@example.test", password="Wrong123", remember=True)),
        )

        current = browser_session(request("/api/auth/session", cookie=cookie_one))
        assert current["ok"] is True
        assert current["user"]["email"] == "auth-one@example.test"
        assert current["workspace"] == "Auth Gate One"

        # Logout must revoke server state and clear the cookie.
        logout_response = Response()
        logout(None, logout_response, request("/api/auth/logout", method="POST", cookie=cookie_one))
        assert "max-age=0" in logout_response.headers["set-cookie"].lower()
        expect_http(401, lambda: browser_session(request("/api/auth/session", cookie=cookie_one)))

        # Expired sessions must be rejected and removed rather than looping.
        relogin_response = Response()
        login(auth_runtime.LoginIn(email="auth-one@example.test", password="Secure123", remember=True), relogin_response)
        expiring_cookie = cookie_value(relogin_response)
        con = auth_runtime._connect()
        token_hash = __import__("hashlib").sha256(expiring_cookie.encode()).hexdigest()
        con.execute(
            "UPDATE auth_sessions SET expires_at=? WHERE token_hash=?",
            ((datetime.utcnow() - timedelta(minutes=1)).isoformat(), token_hash),
        )
        con.commit()
        con.close()
        expect_http(401, lambda: browser_session(request("/api/auth/session", cookie=expiring_cookie)))
        con = auth_runtime._connect()
        assert con.execute("SELECT 1 FROM auth_sessions WHERE token_hash=?", (token_hash,)).fetchone() is None
        con.close()

        # Forgot/reset must be one-time, expire correctly, revoke old sessions,
        # and allow the new password immediately afterwards.
        active = login(auth_runtime.LoginIn(email="auth-two@example.test", password="Secure123", remember=True))
        active_token = active["token"]
        forgot_result = forgot(
            auth_runtime.ForgotPasswordIn(email="auth-two@example.test"),
            request("/api/auth/forgot-password", method="POST"),
        )
        assert forgot_result["ok"] is True and len(sent) == 1
        reset_token = parse_qs(urlparse(sent[-1][1]).query)["reset_token"][0]
        reset_hash = __import__("hashlib").sha256(reset_token.encode()).hexdigest()
        con = auth_runtime._connect()
        con.execute(
            "UPDATE password_reset_tokens SET expires_at=? WHERE token_hash=?",
            ((datetime.utcnow() - timedelta(minutes=1)).isoformat(), reset_hash),
        )
        con.commit()
        con.close()
        expect_http(
            400,
            lambda: reset(
                auth_runtime.ResetPasswordIn(
                    token=reset_token,
                    password="Changed456",
                    confirm_password="Changed456",
                )
            ),
        )

        sent.clear()
        forgot(
            auth_runtime.ForgotPasswordIn(email="auth-two@example.test"),
            request("/api/auth/forgot-password", method="POST"),
        )
        reset_token = parse_qs(urlparse(sent[-1][1]).query)["reset_token"][0]
        changed = reset(
            auth_runtime.ResetPasswordIn(
                token=reset_token,
                password="Changed456",
                confirm_password="Changed456",
            )
        )
        assert changed["ok"] is True
        expect_http(401, lambda: token_session(auth_runtime.TokenIn(token=active_token)))
        expect_http(
            401,
            lambda: login(auth_runtime.LoginIn(email="auth-two@example.test", password="Secure123", remember=True)),
        )
        assert login(auth_runtime.LoginIn(email="auth-two@example.test", password="Changed456", remember=True))["ok"] is True
        expect_http(
            400,
            lambda: reset(
                auth_runtime.ResetPasswordIn(
                    token=reset_token,
                    password="Another789",
                    confirm_password="Another789",
                )
            ),
        )

        # Unknown accounts keep the generic response and never dispatch mail.
        sent.clear()
        missing = forgot(
            auth_runtime.ForgotPasswordIn(email="missing@example.test"),
            request("/api/auth/forgot-password", method="POST"),
        )
        assert missing["ok"] is True
        assert sent == []

        # Frontend + Full Stack: one cookie controller, visible recovery/create
        # flows, root-scoped service worker, and network-only auth/API navigation.
        login_html = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
        controller = (ROOT / "static" / "login-controller.js").read_text(encoding="utf-8")
        sw = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
        runtime = (ROOT / "main" / "__init__.py").read_text(encoding="utf-8")

        assert login_html.count("data-login-controller") == 1
        assert 'id="createTab"' in login_html
        assert 'id="forgotPassword"' in login_html
        assert 'id="resetForm"' in login_html
        assert "await robustPost('/api/auth/login'" in controller
        assert "await robustPost('/api/auth/register'" in controller
        assert "await robustPost('/api/auth/forgot-password'" in controller
        assert "await robustPost('/api/auth/reset-password'" in controller
        assert "verifyCookieSession" in controller and "resumeExistingSession" in controller
        assert "serviceWorker.register('/sw.js?v=10', {scope: '/'})" in controller
        assert "url.pathname.startsWith('/api/')" in sw
        assert "request.mode === 'navigate'" in sw and "cache: 'no-store'" in sw
        assert '@app.get("/sw.js")' in runtime
        assert '"Service-Worker-Allowed": "/"' in runtime

        print("P0 auth stabilization gate passed")
    finally:
        auth_runtime._send_reset_email = previous_sender
        auth_runtime.DB_PATH = previous_db
        tenant_security._schema_db = None
        if previous_public is None:
            os.environ.pop("SHORTLISTAI_PUBLIC_URL", None)
        else:
            os.environ["SHORTLISTAI_PUBLIC_URL"] = previous_public
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    run()
