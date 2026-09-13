# PostgreSQL Migration Status

Status: **foundation only — production cutover not enabled**.

Implemented on `backend-postgres-migration`:

- SQLAlchemy database runtime with `DATABASE_URL` PostgreSQL support and SQLite fallback.
- Native workspace-scoped SQLAlchemy schema for ATS/auth tables.
- Alembic baseline migration with reversible upgrade/downgrade coverage.
- PostgreSQL 16 CI schema verification.
- Guarded SQLite-to-PostgreSQL copy command with dry-run default and empty-target enforcement.
- Existing SQLite backend regression suite preserved.
- Cutover and rollback runbook.

Not yet enabled in production:

- Live application reads/writes still use the existing SQLite path.
- Render managed PostgreSQL has not been provisioned or attached.
- Runtime monkey-patch/regex tenant SQL has not yet been replaced with repository-based PostgreSQL access.
- No production data has been copied.

Next engineering step: migrate auth and core ATS repositories to the database abstraction while keeping the SQLite implementation available for compatibility until production cutover verification is complete.
