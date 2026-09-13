# ShortlistAI Data Foundation

## Current production state

ShortlistAI production still reads and writes through the existing SQLite runtime. The repository now also contains a PostgreSQL-capable SQLAlchemy/Alembic foundation, but production cutover is intentionally not enabled yet.

The safe strategy is therefore a compatibility bridge: harden the current SQLite path and candidate-ingestion behavior now, while keeping every new data invariant represented in the PostgreSQL schema and migration tooling.

## Data Foundation v1

This phase adds:

- SQLite WAL mode, a 5-second busy timeout, foreign keys and NORMAL synchronous mode for the current ATS/auth connections.
- A tenant-scoped `candidate_identities` table with normalized email, normalized phone and resume-fingerprint keys.
- Merge-on-duplicate candidate saves instead of reject/skip behavior.
- Identity refresh and activity logging after merges.
- Structured bulk candidate ingestion up to 800 records per request.
- Sequential bulk resume ingestion up to 800 files, with chunk commits and per-file error reporting.
- `/api/data-health` for candidate count, identity count and active SQLite safety settings.
- Regression coverage for 800 candidates, Boolean search, duplicate merge, bulk resume merge and workspace isolation.
- PostgreSQL `candidate_identities` model + Alembic migration so duplicate-safety data survives future cutover.
- SQLite-to-PostgreSQL copy support for `candidate_identities`.

## PostgreSQL integration

The existing PostgreSQL foundation provides:

- `DATABASE_URL` resolution with PostgreSQL support and SQLite fallback.
- SQLAlchemy workspace-aware models and repository boundaries.
- Alembic schema migrations.
- A guarded SQLite-to-PostgreSQL migration command.
- PostgreSQL CI/schema validation and a cutover/rollback runbook.

Data Foundation v1 deliberately does **not** change live routes to PostgreSQL. The current auth and ATS runtime still depends on SQLite-specific behavior and tenant-security compatibility code.

## Next engineering step

1. Move auth operations to the SQLAlchemy database abstraction while preserving cookie/session behavior.
2. Move core ATS jobs/candidates/notes/activity/interviews routes to explicit workspace repositories.
3. Implement candidate identity lookup/refresh through the same repository boundary.
4. Run the complete auth, workspace-isolation, Boolean-search, duplicate-merge, scoring, pipeline and 500–800 profile tests against PostgreSQL.
5. Export and verify the current production SQLite source before any copy.
6. Run a migration dry-run and compare row counts, workspace counts, candidate identities and representative search results.
7. Copy into an empty PostgreSQL target and repeat verification.
8. Enable production PostgreSQL only after the verified cutover; keep rollback available until production smoke checks pass.

## Non-negotiable rules

- Never migrate only part of auth or ATS data.
- Never remove explicit `workspace_id` isolation.
- Never mark migration complete from schema creation alone.
- Never silently drop candidates that collide on email, phone or resume fingerprint; merge or surface the conflict.
- Never treat the free web-service filesystem as the final production source of truth.
