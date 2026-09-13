# Database module boundary

`shortlistai.db` is the migration target for new backend persistence code.

Rules for migrated code:

1. Prefer explicit repository queries over `tenant_security.py` SQL rewriting.
2. Every tenant-owned read/write must visibly constrain `workspace_id`.
3. Do not accept a caller-supplied workspace id when the authenticated workspace is already known.
4. Keep schema changes in Alembic migrations.
5. Preserve SQLite compatibility until the PostgreSQL cutover is explicitly approved and verified.

The legacy SQLite runtime remains active for production while routes are migrated incrementally.
