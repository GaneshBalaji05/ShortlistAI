"""Add tenant-scoped candidate identity keys for duplicate-safe ingestion.

Revision ID: 20260914_0002
Revises: 20260914_0001
Create Date: 2026-09-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260914_0002"
down_revision = "20260914_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_identities",
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("identity_value", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "identity_type",
            "identity_value",
            name="pk_candidate_identities",
        ),
    )
    op.create_index(
        "idx_candidate_identities_candidate",
        "candidate_identities",
        ["workspace_id", "candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_candidate_identities_candidate", table_name="candidate_identities")
    op.drop_table("candidate_identities")
