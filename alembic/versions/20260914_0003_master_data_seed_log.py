"""Add private Sheet2 seed metadata to PostgreSQL migration schema.

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
        "master_data_seed_log",
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("seeded_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "dataset_version",
            name="pk_master_data_seed_log",
        ),
    )


def downgrade() -> None:
    op.drop_table("master_data_seed_log")
