# ShortlistAI PostgreSQL Migration Runbook

This runbook is intentionally conservative. Production remains on SQLite until every gate below is completed.

## Production target

- Production PostgreSQL provider: **Neon**.
- Preferred region: **Singapore**, matching the Render web service region where available.
- Use a Neon pooled connection string for the application and require SSL/TLS.
- Do **not** set Render `DATABASE_URL` until all live auth/ATS persistence paths are PostgreSQL-capable and the rehearsal copy passes validation.
- The existing expiring Render PostgreSQL instance may be used only for disposable rehearsal/testing; it must not become the production source of truth.

## Current migration architecture

- `DATABASE_URL` selects PostgreSQL when configured.
- `SQLITE_PATH` remains the fallback during the transition.
- Alembic owns the new PostgreSQL schema.
- Core ATS tables have native, non-null `workspace_id` foreign keys.
- `scripts/migrate_sqlite_to_postgres.py` performs a guarded one-time copy from SQLite into an empty PostgreSQL schema.

## Pre-cutover gates

1. Hardening PR must be merged first.
2. PostgreSQL migration CI must be green.
3. Provision the Neon PostgreSQL database in Singapore where available and record both pooled application and direct migration connection strings securely.
4. Confirm SSL/TLS is required and connectivity succeeds from a production-like environment.
5. Take a point-in-time copy/backup of the production SQLite database.
6. Run the migration script without `--apply`; verify every source table count and tenant-isolation validation.
7. Run `alembic upgrade head` against the new PostgreSQL database using the direct migration connection.
8. Confirm the PostgreSQL target is empty before data copy.
9. Run the migration with `--apply` using the production SQLite snapshot, not a changing live file.
10. Verify row counts, foreign keys, workspace isolation, authentication records, jobs, candidates, notes, activity, and interviews.
11. Run a production-like smoke test against PostgreSQL before switching the live service.
12. Confirm no live auth/ATS route still depends on direct SQLite persistence when `DATABASE_URL` is enabled.

## Cutover

1. Put writes into a short maintenance/freeze window so SQLite stops changing during the final copy.
2. Capture the final SQLite snapshot.
3. Recreate/clear the target PostgreSQL database if a rehearsal copy was used.
4. Run `alembic upgrade head` using the direct Neon connection.
5. Run `python scripts/migrate_sqlite_to_postgres.py --sqlite-path <snapshot> --database-url <postgres-url> --apply`.
6. Verify data counts, foreign keys and tenant isolation.
7. Configure Render `DATABASE_URL` with the Neon pooled application connection string.
8. Deploy the PostgreSQL-capable application release.
9. Run login, Create Account, Talent Pool, Boolean search, candidate CRUD, dashboard, interview, and password-recovery smoke tests.
10. Keep the final SQLite snapshot untouched through the rollback window.

## Rollback

Do not destroy or modify the SQLite source during the migration window.

If PostgreSQL verification fails before writes are accepted in PostgreSQL:

1. Remove/disable `DATABASE_URL` from the app.
2. Restore the previous SQLite-backed release/environment.
3. Redeploy and run the normal backend smoke tests.

If PostgreSQL has already accepted new writes, do not blindly roll back to the old SQLite database because that would lose newer data. Stop writes and reconcile the delta first.

## Safety properties of the migration tool

The copy command deliberately refuses to proceed when:

- the target is not PostgreSQL;
- source tenant tables are missing `workspace_id` or contain null workspace ownership;
- the target PostgreSQL schema is incomplete;
- the target PostgreSQL database already contains application data.

Without `--apply`, the command is validation-only and does not modify the target.
