# PostgreSQL Migration Status

Status: **engineering stabilization in progress — production cutover blocked**.

The PostgreSQL foundation is merged in `main`; stabilization work is continuing in draft PR #38 (`engineering-stabilization-v2`). Production remains on SQLite and no live data has been copied.

## Completed and verified

- SQLAlchemy runtime supports PostgreSQL through `DATABASE_URL` and keeps SQLite fallback/rollback support.
- Native SQLAlchemy models cover workspaces, users, auth sessions, password reset tokens, jobs, candidates, candidate identities, notes, activity logs, interviews and security migrations.
- Alembic baseline migration has reversible upgrade/downgrade coverage.
- `AuthRepository` now owns auth/users/workspaces/session/password-reset persistence used by auth routes.
- `WorkspaceRepository` explicitly scopes ATS reads/writes by `workspace_id` and rejects cross-workspace candidate/job/interview/note/activity references.
- Candidate identity repository operations enforce workspace ownership and identity conflicts.
- Package-owned dashboard/interview persistence is repository-backed.
- SQLite backup tooling performs integrity validation, consistent backup, row-count comparison, SHA-256 and manifest generation.
- SQLite/PostgreSQL parity tooling compares all migration-table counts, workspace ownership, candidate IDs and representative Boolean-search results.
- CI runs migration verification on PostgreSQL 18, matching the Render database major version.
- PostgreSQL auth-route regression covers register, session, forgot/reset password, prior-session revocation, login and logout.
- Existing SQLite auth, tenant, Boolean search, Talent Pool and final-review regressions remain green.
- Render managed PostgreSQL (`shortlistai-db`) exists in Singapore but is intentionally not attached to the web service yet.

## Still blocking PostgreSQL cutover

- Remaining legacy jobs/candidates/notes/activity/search/evaluation/export persistence in `main.py` still uses SQLite-style SQL.
- `data_foundation.py` candidate merge, candidate identities, bulk candidate/profile ingestion and saved AI shortlist persistence still use the SQLite compatibility connection.
- `tenant_security.py` still contains request-time SQLite tenant views, regex SQL rewriting and the `legacy.db` compatibility patch for those unmigrated routes.
- Full PostgreSQL end-to-end regression still needs duplicate merge, deterministic scoring persistence, role/pipeline counts, tracker export and 500–800 profile ingestion against PostgreSQL.
- The production SQLite file has not yet been captured outside the Render service. The current Render connector exposes service/deploy/database management but not a shell/file-copy action, so this remains an explicit operational blocker.
- Render PostgreSQL read-query access through the connector currently fails its SSL/TLS connection requirement; CI PostgreSQL validation is green, but this is not a substitute for the final production-target rehearsal.

## Cutover rule

Do not attach `DATABASE_URL` to the production service until every item in `shortlistai/db/CUTOVER_CHECKLIST.md` passes. SQLite must remain intact throughout the rollback window, and any failed production smoke test must return the application to the last verified SQLite configuration before writes reopen.
