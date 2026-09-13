# ShortlistAI Data Foundation

## Current production reality

ShortlistAI currently uses a local SQLite database selected by `SQLITE_PATH`. The live Render web service is on a free web-service plan, so a local SQLite file must not be treated as the long-term production durability layer unless it is explicitly placed on durable storage.

This stabilization phase deliberately does **not** flip the live application to PostgreSQL yet. The existing application, auth runtime, tenant security layer, SQL rewriting, views, tests and runtime patches are SQLite-specific. Changing only `DATABASE_URL` or replacing `sqlite3.connect()` would risk authentication, workspace isolation and candidate data integrity.

## Data Foundation v1

The v1 layer adds the safeguards needed before a database migration:

- SQLite WAL mode, a 5-second busy timeout, foreign keys and NORMAL synchronous mode on ATS/auth connections.
- A tenant-scoped `candidate_identities` table with strong identity keys for normalized email, normalized phone and resume fingerprint.
- Merge-on-duplicate candidate saves rather than reject/skip behavior.
- Identity refresh and activity logging after merges.
- Structured bulk candidate ingestion up to 800 records per request.
- Sequential bulk resume ingestion up to 800 files, with chunk commits and per-file error reporting.
- `/api/data-health` for candidate count, identity count and active SQLite safety settings.
- Regression coverage for 800 candidates, Boolean search, duplicate merge, bulk resume merge and workspace isolation.

## PostgreSQL migration path

1. Keep the SQLite runtime stable and fully covered by regression tests.
2. Introduce a storage adapter/repository layer that exposes candidate, job, interview, notes, activity and auth operations without relying on SQLite SQL rewriting.
3. Implement a PostgreSQL adapter using explicit `workspace_id` predicates and database constraints.
4. Build a read-only migration verifier that compares row counts, workspace counts, candidate identities and representative search results between SQLite and PostgreSQL.
5. Take an export/backup of the live SQLite data and migrate into PostgreSQL.
6. Run verification before changing the production storage selector.
7. Cut over production only after auth, tenant isolation, 500–800 profile ingestion, duplicate merge, Boolean search, scoring and pipeline regression tests pass against PostgreSQL.
8. Keep a rollback path until production verification is complete.

## Non-negotiable migration rules

- Never migrate only part of auth or ATS data.
- Never remove `workspace_id` isolation during migration.
- Never mark migration complete from schema creation alone; production behavior must be verified.
- Never silently drop candidates that collide on email, phone or resume fingerprint; merge or surface the conflict.
- Never use the free web-service filesystem as the final source of truth for production candidate data.
