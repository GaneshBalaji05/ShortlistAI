# ShortlistAI PostgreSQL cutover checklist

Cutover is blocked until every required gate below is checked with evidence from the exact release commit.

## Code and regression gates

- [x] PostgreSQL/Alembic foundation exists.
- [x] Candidate identities are represented in both SQLite and PostgreSQL schemas.
- [x] Explicit workspace repository rejects cross-workspace references.
- [x] Package-owned dashboard/interview persistence is repository-backed.
- [x] Auth/users/workspaces/session/password-reset persistence is repository-backed.
- [ ] Jobs/candidates/notes/activity/export/search/scoring/ingestion legacy data paths are repository-backed.
- [ ] Runtime regex SQL rewriting is no longer required by migrated routes.
- [ ] Runtime route replacement/monkey-patching is reduced to documented compatibility shims only.
- [ ] Full SQLite regression suite passes on the exact release commit.
- [ ] Full PostgreSQL 18 regression suite passes on the exact release commit, including auth, tenant isolation, Boolean search, duplicate merge, scoring, pipeline counts, interviews, exports, and 500–800 profile ingestion.

## Source backup and migration rehearsal

- [x] Verified SQLite backup tooling exists (`scripts/backup_sqlite.py`).
- [x] SQLite/PostgreSQL parity tooling exists (`scripts/verify_sqlite_postgres_parity.py`).
- [ ] Production SQLite file location is confirmed.
- [ ] Production SQLite integrity check returns `ok`.
- [ ] Production SQLite snapshot is captured before migration.
- [ ] Backup manifest, SHA-256, size, and row counts are stored outside the web-service ephemeral filesystem.
- [ ] Source tenant isolation validation passes with no null `workspace_id` values.
- [ ] Migration dry run records row counts for workspaces, users, auth sessions, reset tokens, jobs, candidates, candidate identities, notes, activity logs, interviews, and security migrations.
- [ ] Empty PostgreSQL 18 target is upgraded with `alembic upgrade head`.
- [ ] Rehearsal copy completes into an empty PostgreSQL target.
- [ ] SQLite/PostgreSQL row counts match for every migrated table.
- [ ] Workspace ownership/null checks match.
- [ ] Candidate primary keys and identity ownership match.
- [ ] Representative Boolean-search results match between SQLite and PostgreSQL.
- [ ] Rehearsal login/session/reset, candidate search, scoring, pipeline, interview and export smoke tests pass.

## Production cutover

- [ ] Render workspace/service/database IDs are re-confirmed immediately before cutover.
- [ ] Maintenance/write-freeze window is active so SQLite cannot change during final copy.
- [ ] A final verified SQLite backup is captured after the write freeze starts.
- [ ] Final SQLite dry-run counts are recorded.
- [ ] PostgreSQL target is confirmed empty (or explicitly reset from the verified rehearsal procedure).
- [ ] Final migration copy completes successfully.
- [ ] Final parity report passes before application configuration changes.
- [ ] `DATABASE_URL` is attached only after all prior gates pass.
- [ ] New deployment becomes healthy and `/api/auth/session` works against PostgreSQL.
- [ ] Production smoke tests pass for login, workspace isolation, jobs, candidates, Boolean search, duplicate merge, scoring, pipeline counts, interviews, exports, and representative profile ingestion.

## Rollback gate

- [ ] Pre-cutover SQLite database remains untouched and retained for the rollback window.
- [ ] Previous Render application configuration/commit is recorded.
- [ ] Rollback procedure has been rehearsed against non-production data.
- [ ] If any production smoke test fails, remove/restore `DATABASE_URL`, redeploy the last SQLite release, and verify auth + ATS reads before reopening writes.
- [ ] PostgreSQL is treated as provisional until smoke verification is complete; no irreversible SQLite deletion or cleanup occurs during this window.
- [ ] Rollback window is closed only after production verification is explicitly recorded as successful.
