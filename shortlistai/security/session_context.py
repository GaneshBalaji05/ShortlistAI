from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware import Middleware

import auth_runtime
import tenant_security
from shortlistai.db.runtime import is_postgres_url

SESSION_COOKIE = "shortlistai_session"


def _protected(path: str) -> bool:
    return (
        path == "/app"
        or (path.startswith("/api/") and not path.startswith("/api/auth/"))
        or path in {"/analyze", "/export"}
    )


class RepositorySessionTenantMiddleware:
    """Resolve sessions through AuthRepository while sharing the existing request context.

    The old tenant SQL-rewrite layer remains available only for routes that have not yet
    migrated. Repository-backed routes consume the same workspace/user ContextVars, so the
    middleware can move first without rewriting the whole application at once.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not _protected(scope.get("path") or "/"):
            return await self.app(scope, receive, send)

        if not is_postgres_url(auth_runtime._auth_database_url()):
            tenant_security.ensure_schema()

        request = Request(scope, receive=receive)
        row = auth_runtime._session_row(request.cookies.get(SESSION_COOKIE, ""))
        if row is None:
            response = (
                RedirectResponse("/", status_code=303)
                if scope.get("path") == "/app"
                else JSONResponse({"detail": "Authentication required"}, status_code=401)
            )
            return await response(scope, receive, send)

        workspace_token = tenant_security._workspace.set(int(row["workspace_id"]))
        user_token = tenant_security._user.set(int(row["id"]))
        try:
            return await self.app(scope, receive, send)
        finally:
            tenant_security._workspace.reset(workspace_token)
            tenant_security._user.reset(user_token)


def _blocked_postgres_legacy_db():
    raise RuntimeError(
        "Legacy SQLite route reached while PostgreSQL is configured. "
        "Migrate this route to WorkspaceRepository before production cutover."
    )


def install(app) -> None:
    """Install one repository-backed authentication/workspace middleware."""
    try:
        import main

        legacy = getattr(main, "legacy", None)
        if legacy is not None:
            legacy.db = (
                _blocked_postgres_legacy_db
                if is_postgres_url(auth_runtime._auth_database_url())
                else tenant_security.workspace_db
            )
    except Exception:
        pass

    if getattr(app.state, "shortlistai_repository_session_security", False):
        return

    # Remove only the old ShortlistAI tenant middleware if it was installed earlier. Other
    # application/user middleware remains untouched.
    app.user_middleware = [
        item
        for item in app.user_middleware
        if getattr(item, "cls", None) is not tenant_security.SessionTenantMiddleware
    ]
    app.user_middleware.insert(0, Middleware(RepositorySessionTenantMiddleware))
    app.middleware_stack = app.build_middleware_stack()
    app.state.shortlistai_repository_session_security = True
    app.state.shortlistai_tenant_security = True
