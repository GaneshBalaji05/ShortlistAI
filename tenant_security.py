from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from contextvars import ContextVar
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware import Middleware

SESSION_COOKIE = "shortlistai_session"
TABLES = ("candidates", "jobs", "notes", "activity_log", "interviews")
VIEWS = {name: f"tenant_{name}" for name in TABLES}
_workspace: ContextVar[Optional[int]] = ContextVar("shortlistai_workspace", default=None)
_user: ContextVar[Optional[int]] = ContextVar("shortlistai_user", default=None)
_schema_lock = threading.Lock()
_schema_db: Optional[str] = None
SQLITE_BUSY_TIMEOUT_MS = 5000


def _auth():
    import auth_runtime
    return auth_runtime


def _configure_sqlite_connection(con: sqlite3.Connection) -> sqlite3.Connection:
    """Apply safe defaults for concurrent ATS reads/writes on the current SQLite store."""
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        # Some special/read-only SQLite targets cannot change journal mode. Keep the
        # connection usable while still retaining foreign-key and timeout hardening.
        pass
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _raw() -> sqlite3.Connection:
    con = sqlite3.connect(_auth().DB_PATH, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    return _configure_sqlite_connection(con)


def _table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _column(con: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _schema_is_current(key: str) -> bool:
    """Do not trust only the cached DB path; legacy ATS tables can be created after auth startup."""
    if _schema_db != key:
        return False
    con = _raw()
    try:
        for table in TABLES:
            if not _table(con, table):
                continue
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            if "workspace_id" not in cols:
                return False
        return True
    finally:
        con.close()


def ensure_schema(force: bool = False) -> None:
    global _schema_db
    ar = _auth()
    key = os.path.abspath(ar.DB_PATH)
    if not force and _schema_is_current(key):
        return
    with _schema_lock:
        if not force and _schema_is_current(key):
            return
        ar._ensure_auth_schema()
        con = _raw()
        try:
            _, demo_workspace = ar._ensure_demo_account(con)
            for table in TABLES:
                if _table(con, table):
                    _column(con, table, "workspace_id", "INTEGER")
            if _table(con, "jobs"):
                con.execute("UPDATE jobs SET workspace_id=? WHERE workspace_id IS NULL", (demo_workspace,))
                con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON jobs(workspace_id)")
            if _table(con, "candidates"):
                con.execute("UPDATE candidates SET workspace_id=? WHERE workspace_id IS NULL", (demo_workspace,))
                con.execute("CREATE INDEX IF NOT EXISTS idx_candidates_workspace ON candidates(workspace_id)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_candidates_workspace_job ON candidates(workspace_id,job_id)")
            for table in ("notes", "activity_log", "interviews"):
                if _table(con, table) and _table(con, "candidates"):
                    con.execute(f"UPDATE {table} SET workspace_id=(SELECT c.workspace_id FROM candidates c WHERE c.id={table}.candidate_id) WHERE workspace_id IS NULL")
                    con.execute(f"UPDATE {table} SET workspace_id=? WHERE workspace_id IS NULL", (demo_workspace,))
                    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_workspace ON {table}(workspace_id)")
            con.execute("CREATE TABLE IF NOT EXISTS security_migrations(name TEXT PRIMARY KEY,applied_at TEXT NOT NULL)")
            if not con.execute("SELECT 1 FROM security_migrations WHERE name='http_only_sessions_v1'").fetchone():
                con.execute("DELETE FROM auth_sessions")
                con.execute("INSERT INTO security_migrations VALUES(?,?)", ("http_only_sessions_v1", datetime.utcnow().isoformat()))
            for table, view in VIEWS.items():
                if _table(con, table):
                    con.execute(f"DROP VIEW IF EXISTS {view}")
                    con.execute(f"CREATE VIEW {view} AS SELECT * FROM {table} WHERE workspace_id=current_workspace()")
            con.commit()
            _schema_db = key
        finally:
            con.close()


def current_workspace() -> int:
    value = _workspace.get()
    if value is None:
        raise HTTPException(401, "Authentication required")
    return int(value)


def current_user() -> int:
    value = _user.get()
    if value is None:
        raise HTTPException(401, "Authentication required")
    return int(value)


def _read_sql(sql: str) -> str:
    for table, view in VIEWS.items():
        sql = re.sub(rf"(?i)\b{re.escape(table)}\b", view, sql)
    return sql


def _guard(sql: str, marker: str) -> str:
    semi = sql.rstrip().endswith(";")
    sql = sql.rstrip().rstrip(";").rstrip()
    sql += (" AND " if re.search(r"(?i)\bWHERE\b", sql) else " WHERE ") + f"workspace_id={marker}"
    return sql + (";" if semi else "")


def _rewrite(sql: str, params, wid: int):
    head = sql.lstrip().upper()
    if head.startswith("SELECT") or head.startswith("WITH"):
        return _read_sql(sql), params
    m = re.match(r"(?is)^(\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)(candidates|jobs|notes|activity_log|interviews)(\s*\()([^)]*)(\)\s*VALUES\s*\()([^)]*)(\).*)$", sql)
    if m and not re.search(r"(?i)(?:^|,)\s*workspace_id\s*(?:,|$)", m.group(4)):
        if isinstance(params, dict):
            p = dict(params); p["__wid"] = wid; marker = ":__wid"
        else:
            p = (wid, *tuple(params or ())); marker = "?"
        return m.group(1)+m.group(2)+m.group(3)+"workspace_id,"+m.group(4)+m.group(5)+marker+","+m.group(6)+m.group(7), p
    if re.match(r"(?is)^\s*(?:UPDATE\s+|DELETE\s+FROM\s+)(candidates|jobs|notes|activity_log|interviews)\b", sql):
        if isinstance(params, dict):
            p = dict(params); p["__wid"] = wid; return _guard(sql, ":__wid"), p
        return _guard(sql, "?"), (*tuple(params or ()), wid)
    return sql, params


def _split_csv(text: str) -> list[str]:
    out, start, depth, quote = [], 0, 0, ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote: quote = ""
            continue
        if ch in "\"'": quote = ch
        elif ch == "(": depth += 1
        elif ch == ")": depth = max(0, depth-1)
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip()); start = i+1
    out.append(text[start:].strip())
    return out


def _reference(con: sqlite3.Connection, table: str, value, wid: int) -> None:
    if value in (None, ""):
        return
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Invalid {table[:-1]} reference")
    row = sqlite3.Connection.execute(con, f"SELECT 1 FROM {table} WHERE id=? AND workspace_id=?", (value, wid)).fetchone()
    if row is None:
        raise HTTPException(404, f"{table[:-1].title()} not found in this workspace")


def _validate(con: sqlite3.Connection, sql: str, params, wid: int) -> None:
    if isinstance(params, dict):
        return
    values = tuple(params or ())
    m = re.match(r"(?is)^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(candidates|notes|activity_log|interviews)\s*\(([^)]*)\)\s*VALUES", sql)
    if m:
        cols = [x.strip().lower() for x in _split_csv(m.group(2))]
        data = dict(zip(cols, values))
        if m.group(1).lower() in {"candidates", "interviews"} and "job_id" in data:
            _reference(con, "jobs", data["job_id"], wid)
        if m.group(1).lower() in {"notes", "activity_log", "interviews"} and "candidate_id" in data:
            _reference(con, "candidates", data["candidate_id"], wid)
        return
    m = re.match(r"(?is)^\s*UPDATE\s+(candidates|interviews|notes|activity_log)\s+SET\s+(.*?)(?:\s+WHERE\b|$)", sql)
    if not m:
        return
    pos = 0
    for assignment in _split_csv(m.group(2)):
        n = assignment.count("?")
        cm = re.match(r"(?i)^\s*([a-z_][a-z0-9_]*)\s*=", assignment)
        col = cm.group(1).lower() if cm else ""
        if n == 1 and pos < len(values):
            if col == "job_id" and m.group(1).lower() in {"candidates", "interviews"}:
                _reference(con, "jobs", values[pos], wid)
            if col == "candidate_id" and m.group(1).lower() in {"notes", "activity_log", "interviews"}:
                _reference(con, "candidates", values[pos], wid)
        pos += n


class TenantCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        wid = int(self.connection.workspace_id)
        _validate(self.connection, sql, parameters, wid)
        sql, parameters = _rewrite(sql, parameters, wid)
        return super().execute(sql, parameters)


class TenantConnection(sqlite3.Connection):
    workspace_id: int

    def cursor(self, factory=None):
        return super().cursor(factory or TenantCursor)

    def execute(self, sql, parameters=(), /):
        _validate(self, sql, parameters, int(self.workspace_id))
        sql, parameters = _rewrite(sql, parameters, int(self.workspace_id))
        return super().execute(sql, parameters)


def workspace_db() -> sqlite3.Connection:
    value = _workspace.get()
    if value is None:
        return _raw()
    wid = int(value)
    ensure_schema()
    con = sqlite3.connect(
        _auth().DB_PATH,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        factory=TenantConnection,
    )
    con.workspace_id = wid
    _configure_sqlite_connection(con)
    con.create_function("current_workspace", 0, lambda: wid)
    return con


def _session(raw: str):
    if not raw:
        return None
    con = _raw()
    try:
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        row = con.execute("""SELECT s.expires_at,u.*,w.name workspace_name FROM auth_sessions s JOIN users u ON u.id=s.user_id LEFT JOIN workspaces w ON w.id=u.workspace_id WHERE s.token_hash=?""", (token_hash,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.utcnow():
            con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
            con.commit()
            return None
        return row
    finally:
        con.close()


def _protected(path: str) -> bool:
    return path == "/app" or (path.startswith("/api/") and not path.startswith("/api/auth/")) or path in {"/analyze", "/export"}


class SessionTenantMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not _protected(scope.get("path") or "/"):
            return await self.app(scope, receive, send)
        ensure_schema()
        request = Request(scope, receive=receive)
        row = _session(request.cookies.get(SESSION_COOKIE, ""))
        if row is None:
            response = RedirectResponse("/", status_code=303) if scope.get("path") == "/app" else JSONResponse({"detail": "Authentication required"}, status_code=401)
            return await response(scope, receive, send)
        wt = _workspace.set(int(row["workspace_id"]))
        ut = _user.set(int(row["id"]))
        try:
            return await self.app(scope, receive, send)
        finally:
            _workspace.reset(wt)
            _user.reset(ut)


def install(app) -> None:
    try:
        import main
        legacy = getattr(main, "legacy", None)
        if legacy is not None:
            legacy.db = workspace_db
    except Exception:
        pass
    if getattr(app.state, "shortlistai_tenant_security", False):
        return
    app.user_middleware.insert(0, Middleware(SessionTenantMiddleware))
    app.middleware_stack = app.build_middleware_stack()
    app.state.shortlistai_tenant_security = True
