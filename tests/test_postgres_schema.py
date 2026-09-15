from __future__ import annotations

import os

from sqlalchemy import inspect, text

from shortlistai.db.runtime import create_database_engine, is_postgres_url, resolve_database_url

EXPECTED_TABLES = {
    "workspaces",
    "users",
    "auth_sessions",
    "password_reset_tokens",
    "jobs",
    "candidates",
    "candidate_identities",
    "ingestion_batches",
    "ingestion_items",
    "notes",
    "activity_log",
    "interviews",
    "security_migrations",
    "alembic_version",
}
WORKSPACE_TABLES = {
    "jobs",
    "candidates",
    "candidate_identities",
    "ingestion_batches",
    "ingestion_items",
    "notes",
    "activity_log",
    "interviews",
}
REQUIRED_INDEXES = {
    "jobs": {"idx_jobs_workspace"},
    "candidates": {"idx_candidates_workspace", "idx_candidates_workspace_job"},
    "candidate_identities": {"idx_candidate_identities_candidate"},
    "ingestion_batches": {"idx_ingestion_batches_workspace", "idx_ingestion_batches_workspace_status"},
    "ingestion_items": {"idx_ingestion_items_workspace_batch", "idx_ingestion_items_workspace_status"},
    "notes": {"idx_notes_workspace", "idx_notes_candidate"},
    "activity_log": {"idx_activity_log_workspace", "idx_activity_log_candidate"},
    "interviews": {"idx_interviews_workspace", "idx_interviews_candidate", "idx_interviews_scheduled"},
}


def main() -> None:
    url = resolve_database_url()
    if not is_postgres_url(url):
        print("SKIP: PostgreSQL schema contract requires DATABASE_URL")
        return

    engine = create_database_engine(url)
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing PostgreSQL tables: {sorted(missing)}"

    for table_name in WORKSPACE_TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert "workspace_id" in columns, f"{table_name}.workspace_id is missing"
        assert columns["workspace_id"]["nullable"] is False, f"{table_name}.workspace_id must be NOT NULL"

        fks = inspector.get_foreign_keys(table_name)
        assert any(
            fk.get("constrained_columns") == ["workspace_id"]
            and fk.get("referred_table") == "workspaces"
            for fk in fks
        ), f"{table_name}.workspace_id must reference workspaces.id"

        indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        required = REQUIRED_INDEXES.get(table_name, set())
        assert required.issubset(indexes), f"{table_name} missing indexes: {sorted(required - indexes)}"

    identity_fks = inspector.get_foreign_keys("candidate_identities")
    assert any(
        fk.get("constrained_columns") == ["candidate_id"]
        and fk.get("referred_table") == "candidates"
        for fk in identity_fks
    ), "candidate_identities.candidate_id must reference candidates.id"

    ingestion_batch_fks = inspector.get_foreign_keys("ingestion_batches")
    assert any(
        fk.get("constrained_columns") == ["created_by"]
        and fk.get("referred_table") == "users"
        for fk in ingestion_batch_fks
    ), "ingestion_batches.created_by must reference users.id"
    ingestion_item_fks = inspector.get_foreign_keys("ingestion_items")
    assert any(
        fk.get("constrained_columns") == ["batch_id"]
        and fk.get("referred_table") == "ingestion_batches"
        for fk in ingestion_item_fks
    ), "ingestion_items.batch_id must reference ingestion_batches.id"
    assert any(
        fk.get("constrained_columns") == ["candidate_id"]
        and fk.get("referred_table") == "candidates"
        for fk in ingestion_item_fks
    ), "ingestion_items.candidate_id must reference candidates.id"

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            workspace_id = connection.execute(
                text("INSERT INTO workspaces(name, created_at) VALUES(:name, :created_at) RETURNING id"),
                {"name": "Postgres CI Workspace", "created_at": "2026-09-14T00:00:00Z"},
            ).scalar_one()
            user_id = connection.execute(
                text(
                    "INSERT INTO users(workspace_id,full_name,email,password_hash,password_salt,role,created_at) "
                    "VALUES(:workspace_id,:full_name,:email,:password_hash,:password_salt,:role,:created_at) RETURNING id"
                ),
                {
                    "workspace_id": workspace_id,
                    "full_name": "Postgres CI Admin",
                    "email": "postgres-ci@example.test",
                    "password_hash": "hash",
                    "password_salt": "salt",
                    "role": "Workspace Admin",
                    "created_at": "2026-09-14T00:00:00Z",
                },
            ).scalar_one()
            job_id = connection.execute(
                text(
                    "INSERT INTO jobs(workspace_id,title,jd,status,created_at) "
                    "VALUES(:workspace_id,:title,:jd,:status,:created_at) RETURNING id"
                ),
                {
                    "workspace_id": workspace_id,
                    "title": "Postgres CI Role",
                    "jd": "Python and FastAPI",
                    "status": "Open",
                    "created_at": "2026-09-14T00:00:00Z",
                },
            ).scalar_one()
            candidate_id = connection.execute(
                text(
                    "INSERT INTO candidates(workspace_id,name,job_id,stage,created_at,updated_at) "
                    "VALUES(:workspace_id,:name,:job_id,:stage,:created_at,:updated_at) RETURNING id"
                ),
                {
                    "workspace_id": workspace_id,
                    "name": "Postgres CI Candidate",
                    "job_id": job_id,
                    "stage": "Sourced",
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO candidate_identities(workspace_id,identity_type,identity_value,candidate_id,created_at) "
                    "VALUES(:workspace_id,'email','candidate@example.test',:candidate_id,:created_at)"
                ),
                {
                    "workspace_id": workspace_id,
                    "candidate_id": candidate_id,
                    "created_at": "2026-09-14T00:00:00Z",
                },
            )
            batch_id = connection.execute(
                text(
                    "INSERT INTO ingestion_batches(workspace_id,created_by,job_id,source,status,total_count,processed_count,created_count,merged_count,failed_count,created_at,updated_at) "
                    "VALUES(:workspace_id,:created_by,:job_id,'Postgres CI','pending',1,0,0,0,0,:created_at,:updated_at) RETURNING id"
                ),
                {
                    "workspace_id": workspace_id,
                    "created_by": user_id,
                    "job_id": job_id,
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO ingestion_items(workspace_id,batch_id,idempotency_key,source_filename,status,attempts,created_at) "
                    "VALUES(:workspace_id,:batch_id,'item-1','profile.txt','pending',0,:created_at)"
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    "created_at": "2026-09-14T00:00:00Z",
                },
            )
            saved = connection.execute(
                text("SELECT workspace_id,job_id FROM candidates WHERE id=:id"),
                {"id": candidate_id},
            ).mappings().one()
            assert saved["workspace_id"] == workspace_id
            assert saved["job_id"] == job_id
            identity = connection.execute(
                text("SELECT candidate_id FROM candidate_identities WHERE workspace_id=:workspace_id"),
                {"workspace_id": workspace_id},
            ).mappings().one()
            assert identity["candidate_id"] == candidate_id
            ingestion = connection.execute(
                text("SELECT workspace_id,total_count FROM ingestion_batches WHERE id=:id"),
                {"id": batch_id},
            ).mappings().one()
            assert ingestion["workspace_id"] == workspace_id
            assert ingestion["total_count"] == 1
        finally:
            transaction.rollback()

    engine.dispose()
    print("PostgreSQL schema contract OK")


if __name__ == "__main__":
    main()
