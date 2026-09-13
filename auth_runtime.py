from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "shortlistai.db"))
PBKDF2_ROUNDS = 260_000
SESSION_DAYS = 30
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


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _ensure_auth_schema() -> None:
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id)")
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


def _new_session(con: sqlite3.Connection, user_id: int, remember: bool = True) -> str:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    lifetime = timedelta(days=SESSION_DAYS if remember else 1)
    con.execute(
        "INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
        (token_hash, user_id, now.isoformat(), (now + lifetime).isoformat()),
    )
    return raw


def _public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "workspace_id": row["workspace_id"],
    }


def install_auth_routes(app) -> None:
    _ensure_auth_schema()

    @app.post("/api/auth/register")
    def register(payload: RegisterIn):
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

        con = _connect()
        try:
            existing = con.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
            if existing:
                raise HTTPException(409, "An account with this email already exists.")
            now = datetime.utcnow().isoformat()
            cur = con.cursor()
            cur.execute("INSERT INTO workspaces(name,created_at) VALUES(?,?)", (workspace, now))
            workspace_id = cur.lastrowid
            pw_hash, pw_salt = _hash_password(payload.password)
            cur.execute(
                """INSERT INTO users(workspace_id,full_name,email,password_hash,password_salt,role,created_at,last_login_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (workspace_id, full_name, email, pw_hash, pw_salt, "Workspace Admin", now, now),
            )
            user_id = cur.lastrowid
            token = _new_session(con, user_id, True)
            con.commit()
            user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return {"ok": True, "token": token, "user": _public_user(user), "workspace": workspace}
        except HTTPException:
            con.rollback()
            raise
        except sqlite3.IntegrityError:
            con.rollback()
            raise HTTPException(409, "An account with this email already exists.")
        finally:
            con.close()

    @app.post("/api/auth/login")
    def login(payload: LoginIn):
        email = payload.email.strip().lower()
        if email == "demo@shortlist.ai" and payload.password == "shortlist123":
            return {
                "ok": True,
                "token": "demo-preview-session",
                "user": {"id": 0, "full_name": "Demo User", "email": email, "role": "Demo", "workspace_id": 0},
                "workspace": "ShortlistAI Demo",
                "demo": True,
            }

        con = _connect()
        try:
            row = con.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
            if not row or not _verify_password(payload.password, row["password_hash"], row["password_salt"]):
                raise HTTPException(401, "Invalid email or password.")
            now = datetime.utcnow().isoformat()
            con.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
            token = _new_session(con, row["id"], payload.remember)
            con.commit()
            workspace = con.execute("SELECT name FROM workspaces WHERE id=?", (row["workspace_id"],)).fetchone()
            return {"ok": True, "token": token, "user": _public_user(row), "workspace": workspace["name"] if workspace else ""}
        finally:
            con.close()

    @app.post("/api/auth/session")
    def session(payload: TokenIn):
        if payload.token == "demo-preview-session":
            return {"ok": True, "user": {"id": 0, "full_name": "Demo User", "email": "demo@shortlist.ai", "role": "Demo", "workspace_id": 0}, "workspace": "ShortlistAI Demo", "demo": True}
        token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
        con = _connect()
        try:
            row = con.execute(
                """SELECT s.expires_at,u.*,w.name workspace_name
                   FROM auth_sessions s JOIN users u ON u.id=s.user_id
                   LEFT JOIN workspaces w ON w.id=u.workspace_id
                   WHERE s.token_hash=?""",
                (token_hash,),
            ).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.utcnow():
                if row:
                    con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
                    con.commit()
                raise HTTPException(401, "Session expired. Please sign in again.")
            return {"ok": True, "user": _public_user(row), "workspace": row["workspace_name"] or ""}
        finally:
            con.close()

    @app.post("/api/auth/logout")
    def logout(payload: TokenIn):
        if payload.token != "demo-preview-session":
            token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
            con = _connect()
            con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
            con.commit()
            con.close()
        return {"ok": True}


def schedule_main_auth_patch(delay_seconds: float = 0.15) -> None:
    import threading
    import time

    def worker():
        for _ in range(100):
            try:
                import main
                app = getattr(main, "app", None)
                if app is not None:
                    paths = {getattr(r, "path", "") for r in app.routes}
                    if "/api/auth/register" not in paths:
                        install_auth_routes(app)
                    return
            except Exception:
                pass
            time.sleep(delay_seconds)

    threading.Thread(target=worker, daemon=True, name="shortlistai-auth-patch").start()
