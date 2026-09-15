"""Add tenant-scoped resumable ingestion batches and items.

Revision ID: 20260914_0003
Revises: 20260914_0002
Create Date: 2026-09-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("merged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_batches"),
    )
    op.create_index("idx_ingestion_batches_workspace", "ingestion_batches", ["workspace_id"])
    op.create_index(
        "idx_ingestion_batches_workspace_status",
        "ingestion_batches",
        ["workspace_id", "status"],
    )

    op.create_table(
        "ingestion_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["ingestion_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_items"),
        sa.UniqueConstraint(
            "workspace_id",
            "batch_id",
            "idempotency_key",
            name="uq_ingestion_items_workspace_batch_key",
        ),
    )
    op.create_index(
        "idx_ingestion_items_workspace_batch",
        "ingestion_items",
        ["workspace_id", "batch_id"],
    )
    op.create_index(
        "idx_ingestion_items_workspace_status",
        "ingestion_items",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_ingestion_items_workspace_status", table_name="ingestion_items")
    op.drop_index("idx_ingestion_items_workspace_batch", table_name="ingestion_items")
    op.drop_table("ingestion_items")
    op.drop_index("idx_ingestion_batches_workspace_status", table_name="ingestion_batches")
    op.drop_index("idx_ingestion_batches_workspace", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")
