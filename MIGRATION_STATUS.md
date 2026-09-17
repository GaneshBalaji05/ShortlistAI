# PostgreSQL Migration Status

Status: **foundation only — production cutover not enabled**.

Production target decision: **Neon PostgreSQL**, preferably Singapore to stay close to the Render Singapore web service. Production must remain on SQLite until the runtime migration and zero-loss cutover gates are complete.

Foundation prerequisite PR #27 is merged into `main`. This migration work targets the current `main` foundation directly.

Implemented on `main` / the PostgreSQL foundation:

- SQLAlchemy database runtime with `DATABASE_URL` PostgreSQL support and SQLite fallback.
- Native workspace-scoped SQLAlchemy schema for ATS/auth tables.
- Alembic baseline migration with reversible upgrade/downgrade coverage.
- PostgreSQL 16 CI schema verification.
- Guarded SQLite-to-PostgreSQL copy command with dry-run default and empty-target enforcement.
- Existing SQLite backend regression suite preserved.
- Cutover and rollback runbook.
- API v1 candidate/job reads use the repository/database abstraction.
- API v1 job create/update uses workspace-scoped repository writes.

Not yet enabled in production:

- Live application still contains legacy SQLite-specific ATS/auth/interview persistence paths.
- Neon has not yet been provisioned/connected to this ChatGPT workspace.
- Render `DATABASE_URL` has not been changed.
- No production data has been copied.
- Runtime monkey-patch/legacy SQLite persistence has not yet been fully replaced with repository-based PostgreSQL access.

Current safety rule:

**Do not set production `DATABASE_URL` until no live auth/ATS route depends on direct SQLite persistence, PostgreSQL CI/isolation tests pass, and a snapshot-to-Neon rehearsal copy matches all critical table counts.**

Next engineering step: continue migrating auth, candidate writes, dashboard/interview persistence and remaining ATS routes onto explicit workspace-scoped repositories while preserving SQLite rollback compatibility. After that, provision Neon, rehearse the copy, validate, then perform the controlled Render cutover.
