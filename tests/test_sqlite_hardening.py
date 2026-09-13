from __future__ import annotations

import os
import sqlite3
import tempfile

import auth_runtime
import tenant_security


def _assert_hardened(con: sqlite3.Connection) -> None:
    assert int(con.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    assert int(con.execute("PRAGMA busy_timeout").fetchone()[0]) >= tenant_security.SQLITE_BUSY_TIMEOUT_MS
    assert str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(con.execute("PRAGMA synchronous").fetchone()[0]) == 1  # NORMAL


def run() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    original_path = auth_runtime.DB_PATH
    token = None
    try:
        auth_runtime.DB_PATH = path
        tenant_security._schema_db = None

        raw = tenant_security._raw()
        try:
            _assert_hardened(raw)
        finally:
            raw.close()

        auth_runtime._ensure_auth_schema()
        tenant_security.ensure_schema(force=True)
        con = sqlite3.connect(path)
        try:
            workspace_id = con.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1").fetchone()[0]
        finally:
            con.close()

        token = tenant_security._workspace.set(int(workspace_id))
        scoped = tenant_security.workspace_db()
        try:
            _assert_hardened(scoped)
        finally:
            scoped.close()

        print("SQLite durability/concurrency hardening tests passed")
    finally:
        if token is not None:
            tenant_security._workspace.reset(token)
        tenant_security._schema_db = None
        auth_runtime.DB_PATH = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
