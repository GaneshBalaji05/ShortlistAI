from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Mapping, Optional

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

from shortlistai.db.repositories import AuthRepository, RepositoryConflict
from shortlistai.db.runtime import get_engine_for_url, is_postgres_url, normalize_database_url

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "shortlistai.db"))
PBKDF2_ROUNDS = 260_000
SESSION_DAYS = 30
SESSION_COOKIE = "shortlistai_session"
RESET_MINUTES = 30
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RegisterIn(BaseModel):
    full_name: str
    email: str
    password: str
    confirm_password: str
    workspace_name: str


class LoginIn(BaseModel):
    email: str
    password: str
    remember: bool = True


class TokenIn(BaseModel):
    token: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str
    confirm_password: str


def _auth_database_url() -> str:
    configured = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if configured:
        return configured
    return f"sqlite:///{Path(DB_PATH).resolve()}"


def _repository() -> AuthRepository:
    return AuthRepository(get_engine_for_url(_auth_database_url()))


def _connect() -> sqlite3.Connection:
    """Legacy SQLite compatibility connection.

    Remaining legacy ATS/tenant migration code still calls this helper. Auth API routes no
    longer depend on it. It can be removed after the final SQLite-only paths are migrated.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _ensure_auth_schema() -> None:
    """Maintain the rollback SQLite auth schema; PostgreSQL schema is owned by Alembic."""
    if is_postgres_url(_auth_database_url()):
        return
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS workspaces(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Workspace Admin',
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS auth_sessions(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS password_reset_tokens(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )"""
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id)")
    con.commit()
    con.close()


def _hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return digest.hex(), salt.hex()


def _verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    try:
        digest, _ = _hash_password(password, bytes.fromhex(stored_salt))
        return hmac.compare_digest(digest, stored_hash)
    except Exception:
        return False


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(400, "Password must include at least one letter and one number.")


def _new_session(repo: AuthRepository, user_id: int, remember: bool = True) -> str:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    lifetime = timedelta(days=SESSION_DAYS if remember else 1)
    repo.create_session(
        token_hash=token_hash,
        user_id=int(user_id),
        created_at=now.isoformat(),
        expires_at=(now + lifetime).isoformat(),
    )
    return raw


def _public_user(row: Mapping) -> dict:
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "workspace_id": row["workspace_id"],
    }


def _ensure_demo_account(con: sqlite3.Connection) -> tuple[int, int]:
    """Legacy SQLite helper retained for tenant-schema migration compatibility."""
    row = con.execute("SELECT * FROM users WHERE lower(email)=?", ("demo@shortlist.ai",)).fetchone()
    if row:
        return int(row["id"]), int(row["workspace_id"])
    now = datetime.utcnow().isoformat()
    workspace = con.execute("SELECT id FROM workspaces WHERE name=? ORDER BY id LIMIT 1", ("ShortlistAI Demo",)).fetchone()
    if workspace:
        workspace_id = int(workspace["id"])
    else:
        cur = con.execute("INSERT INTO workspaces(name,created_at) VALUES(?,?)", ("ShortlistAI Demo", now))
        workspace_id = int(cur.lastrowid)
    pw_hash, pw_salt = _hash_password("shortlist123")
    cur = con.execute(
        """INSERT INTO users(workspace_id,full_name,email,password_hash,password_salt,role,created_at,last_login_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (workspace_id, "Demo User", "demo@shortlist.ai", pw_hash, pw_salt, "Demo", now, now),
    )
    return int(cur.lastrowid), workspace_id


def _ensure_demo_repository(repo: AuthRepository) -> tuple[int, int]:
    row = repo.get_user_by_email("demo@shortlist.ai")
    if row:
        return int(row["id"]), int(row["workspace_id"])
    now = datetime.utcnow().isoformat()
    workspace = repo.get_workspace_by_name("ShortlistAI Demo")
    workspace_id = int(workspace["id"]) if workspace else repo.create_workspace(
        name="ShortlistAI Demo", created_at=now
    )
    pw_hash, pw_salt = _hash_password("shortlist123")
    try:
        user_id = repo.create_user(
            workspace_id=workspace_id,
            full_name="Demo User",
            email="demo@shortlist.ai",
            password_hash=pw_hash,
            password_salt=pw_salt,
            role="Demo",
            created_at=now,
            last_login_at=now,
        )
    except RepositoryConflict:
        existing = repo.get_user_by_email("demo@shortlist.ai")
        if not existing:
            raise
        return int(existing["id"]), int(existing["workspace_id"])
    return user_id, workspace_id


def _session_row(raw_token: str):
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    repo = _repository()
    row = repo.get_session_user(token_hash)
    if not row:
        return None
    if datetime.fromisoformat(str(row["expires_at"])) <= datetime.utcnow():
        repo.delete_session(token_hash)
        return None
    return row


def _set_cookie(response: Optional[Response], token: str, remember: bool) -> None:
    if response is None:
        return
    secure = os.getenv("RENDER", "").lower() == "true" or os.getenv("SHORTLISTAI_SECURE_COOKIES", "").lower() in {"1", "true", "yes"}
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=SESSION_DAYS * 86400 if remember else None,
    )


def _send_reset_email(recipient: str, reset_url: str) -> bool:
    host = os.getenv("SHORTLISTAI_SMTP_HOST", "").strip()
    username = os.getenv("SHORTLISTAI_SMTP_USERNAME", "").strip()
    password = os.getenv("SHORTLISTAI_SMTP_PASSWORD", "")
    sender = os.getenv("SHORTLISTAI_SMTP_FROM", username).strip()
    if not host or not sender:
        return False
    try:
        port = int(os.getenv("SHORTLISTAI_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    use_tls = os.getenv("SHORTLISTAI_SMTP_STARTTLS", "true").lower() not in {"0", "false", "no"}
    msg = EmailMessage()
    msg["Subject"] = "Reset your ShortlistAI password"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(
        "We received a request to reset your ShortlistAI password.\n\n"
        f"Open this link to choose a new password (valid for {RESET_MINUTES} minutes):\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def install_auth_routes(app) -> None:
    _ensure_auth_schema()

    @app.post("/api/auth/register")
    def register(payload: RegisterIn, response: Response = None):
        if not is_postgres_url(_auth_database_url()):
            from tenant_security import ensure_schema
            ensure_schema()
        full_name = payload.full_name.strip()
        email = payload.email.strip().lower()
        workspace = payload.workspace_name.strip()
        if len(full_name) < 2:
            raise HTTPException(400, "Enter your full name.")
        if not EMAIL_RE.match(email):
            raise HTTPException(400, "Enter a valid work email.")
        if len(workspace) < 2:
            raise HTTPException(400, "Enter your company or workspace name.")
        if payload.password != payload.confirm_password:
            raise HTTPException(400, "Passwords do not match.")
        _validate_password(payload.password)

        repo = _repository()
        if repo.get_user_by_email(email):
            raise HTTPException(409, "An account with this email already exists.")
        now = datetime.utcnow().isoformat()
        pw_hash, pw_salt = _hash_password(payload.password)
        try:
            workspace_id, user_id = repo.create_workspace_user(
                workspace_name=workspace,
                full_name=full_name,
                email=email,
                password_hash=pw_hash,
                password_salt=pw_salt,
                role="Workspace Admin",
                created_at=now,
                last_login_at=now,
            )
        except RepositoryConflict:
            raise HTTPException(409, "An account with this email already exists.")
        token = _new_session(repo, user_id, True)
        user = repo.get_user(user_id)
        _set_cookie(response, token, True)
        out = {"ok": True, "user": _public_user(user), "workspace": workspace}
        if response is None:
            out["token"] = token
        return out

    @app.post("/api/auth/login")
    def login(payload: LoginIn, response: Response = None):
        if not is_postgres_url(_auth_database_url()):
            from tenant_security import ensure_schema
            ensure_schema()
        email = payload.email.strip().lower()
        repo = _repository()
        if email == "demo@shortlist.ai" and payload.password == "shortlist123":
            user_id, _ = _ensure_demo_repository(repo)
            now = datetime.utcnow().isoformat()
            repo.update_last_login(user_id, now)
            row = repo.get_user(user_id)
            token = _new_session(repo, user_id, payload.remember)
            _set_cookie(response, token, payload.remember)
            out = {"ok": True, "user": _public_user(row), "workspace": "ShortlistAI Demo", "demo": True}
            if response is None:
                out["token"] = token
            return out

        row = repo.get_user_by_email(email)
        if not row or not _verify_password(payload.password, row["password_hash"], row["password_salt"]):
            raise HTTPException(401, "Invalid email or password.")
        now = datetime.utcnow().isoformat()
        repo.update_last_login(int(row["id"]), now)
        token = _new_session(repo, int(row["id"]), payload.remember)
        workspace = repo.get_workspace(int(row["workspace_id"]))
        refreshed = repo.get_user(int(row["id"])) or row
        _set_cookie(response, token, payload.remember)
        out = {"ok": True, "user": _public_user(refreshed), "workspace": workspace["name"] if workspace else ""}
        if response is None:
            out["token"] = token
        return out

    @app.post("/api/auth/forgot-password")
    def forgot_password(payload: ForgotPasswordIn, request: Request):
        email = payload.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(400, "Enter a valid work email.")
        generic = {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}
        if email == "demo@shortlist.ai":
            return generic
        repo = _repository()
        row = repo.get_user_by_email(email)
        if not row:
            return generic
        now = datetime.utcnow()
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        repo.replace_password_reset(
            user_id=int(row["id"]),
            token_hash=token_hash,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=RESET_MINUTES)).isoformat(),
        )
        configured_base = os.getenv("SHORTLISTAI_PUBLIC_URL", "").strip().rstrip("/")
        base = configured_base or str(request.base_url).rstrip("/")
        reset_url = f"{base}/?reset_token={raw}"
        try:
            sent = _send_reset_email(row["email"], reset_url)
        except (smtplib.SMTPException, OSError):
            sent = False
        if not sent and os.getenv("SHORTLISTAI_EXPOSE_RESET_LINK", "").lower() in {"1", "true", "yes"}:
            generic["reset_url"] = reset_url
        return generic

    @app.post("/api/auth/reset-password")
    def reset_password(payload: ResetPasswordIn):
        token = payload.token.strip()
        if not token:
            raise HTTPException(400, "Reset link is invalid.")
        if payload.password != payload.confirm_password:
            raise HTTPException(400, "Passwords do not match.")
        _validate_password(payload.password)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        repo = _repository()
        row = repo.get_password_reset(token_hash)
        if not row or row["used_at"] or datetime.fromisoformat(str(row["expires_at"])) <= datetime.utcnow():
            raise HTTPException(400, "This reset link is invalid or has expired.")
        if str(row["email"]).lower() == "demo@shortlist.ai":
            raise HTTPException(400, "The demo account password cannot be changed.")
        pw_hash, pw_salt = _hash_password(payload.password)
        now = datetime.utcnow().isoformat()
        repo.reset_password(
            token_hash=token_hash,
            user_id=int(row["user_id"]),
            password_hash=pw_hash,
            password_salt=pw_salt,
            used_at=now,
        )
        return {"ok": True, "message": "Password updated. You can sign in with your new password."}

    @app.get("/api/auth/session")
    def browser_session(request: Request):
        row = _session_row(request.cookies.get(SESSION_COOKIE, ""))
        if row is None:
            raise HTTPException(401, "Session expired. Please sign in again.")
        return {"ok": True, "user": _public_user(row), "workspace": row["workspace_name"] or "", "demo": row["email"].lower() == "demo@shortlist.ai"}

    @app.post("/api/auth/session")
    def session(payload: TokenIn):
        row = _session_row(payload.token)
        if row is None:
            raise HTTPException(401, "Session expired. Please sign in again.")
        return {"ok": True, "user": _public_user(row), "workspace": row["workspace_name"] or "", "demo": row["email"].lower() == "demo@shortlist.ai"}

    @app.post("/api/auth/logout")
    def logout(payload: Optional[TokenIn] = None, response: Response = None, request: Request = None):
        raw = request.cookies.get(SESSION_COOKIE, "") if request is not None else ""
        if not raw and payload is not None:
            raw = payload.token
        if raw:
            _repository().delete_session(hashlib.sha256(raw.encode("utf-8")).hexdigest())
        if response is not None:
            response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    from tenant_security import install
    install(app)


def schedule_main_auth_patch(delay_seconds: float = 0.05) -> None:
    """Legacy compatibility shim; retained until runtime route patching is removed."""
    import threading
    import time

    def worker():
        for _ in range(200):
            try:
                import main
                app = getattr(main, "app", None)
                if app is not None:
                    paths = {getattr(r, "path", "") for r in app.routes}
                    if "/app" not in paths:
                        time.sleep(delay_seconds)
                        continue
                    if "/api/auth/register" not in paths:
                        install_auth_routes(app)
                    else:
                        from tenant_security import install
                        install(app)
                    return
            except Exception:
                pass
            time.sleep(delay_seconds)

    threading.Thread(target=worker, daemon=True, name="shortlistai-auth-patch").start()
