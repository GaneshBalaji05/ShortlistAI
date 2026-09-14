# ShortlistAI Neon Clean Cutover

Status: **P0 migration work in progress — do not deploy/cut over yet**

## Product-owner decision

Neon PostgreSQL is the target production database. The current SQLite database is a temporary rollback source only until PostgreSQL production verification is complete.

The authoritative candidate source for the clean Neon load is **Sheet2 (Master Tracker)**.

## Data policy

- Import only genuine candidate records from the approved Sheet2 master tracker.
- Do not import fictional/demo/test candidates.
- Do not migrate historical SQLite candidate rows unless the same candidate is represented in Sheet2.
- Preserve legitimate blanks from Sheet2; do not invent missing values.
- Candidate dedupe is tenant-scoped and uses strong identities such as normalized email/phone (and approved deterministic identity keys).
- Do not pre-populate dummy AI scores, ratings, jobs, notes, interviews, pipeline events, or recruiter activity.
- Keep source provenance and an import audit record without publishing candidate PII in logs.

## Cutover gates

1. Neon schema matches the application-owned production schema and Alembic head.
2. Demo seeding is disabled/removed for production runtime.
3. All live auth/ATS persistence paths use the PostgreSQL repository/database layer; no live route depends on SQLite-specific SQL.
4. Sheet2 is loaded first on an isolated Neon rehearsal branch.
5. Reconcile imported row count, duplicate handling, blank-field preservation, and identity relationships.
6. Validate workspace isolation, foreign keys, Talent Pool Boolean search, candidate profiles, scoring, pipeline, notes, interviews, export, and 500–800 profile ingestion.
7. Run CI and end-to-end production-like regression on PostgreSQL.
8. Only then configure Render `DATABASE_URL` for Neon and run production smoke tests.
9. Retain SQLite rollback evidence through the agreed rollback window.
10. Remove SQLite runtime code/dependencies only after QA marks the Neon production flow verified.

## Explicit non-goals during migration

- No feature expansion.
- No dual-write architecture.
- No automatic copying of old/demo SQLite candidates.
- No direct production cutover from an unverified branch.

## Definition of done

Issue -> root cause -> owner -> fix -> tests -> deploy -> production verification.

The migration is not complete until independent QA verifies the complete production workflow and the Technical PM approves SQLite removal.
