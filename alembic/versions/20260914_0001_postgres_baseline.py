"""PostgreSQL-ready baseline schema with native workspace isolation.

Revision ID: 20260914_0001
Revises: 
Create Date: 2026-09-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260914_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_salt", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="Workspace Admin"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_login_at", sa.Text()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_workspace", "users", ["workspace_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_sessions_user", "auth_sessions", ["user_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("token_hash", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_password_reset_user", "password_reset_tokens", ["user_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("department", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("jd", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="Open"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_jobs_workspace", "jobs", ["workspace_id"])

    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.String(length=320)),
        sa.Column("phone", sa.Text()),
        sa.Column("experience", sa.Float()),
        sa.Column("skills", sa.Text()),
        sa.Column("resume_text", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("notice_period", sa.Text()),
        sa.Column("current_ctc", sa.Text()),
        sa.Column("expected_ctc", sa.Text()),
        sa.Column("job_id", sa.Integer()),
        sa.Column("stage", sa.Text(), nullable=False, server_default="Sourced"),
        sa.Column("ai_score", sa.Float()),
        sa.Column("rating", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("ai_details", sa.Text()),
        sa.Column("resume_filename", sa.Text()),
        sa.Column("profile_details", sa.Text()),
        sa.Column("talent_pools", sa.Text()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_candidates_workspace", "candidates", ["workspace_id"])
    op.create_index("idx_candidates_workspace_job", "candidates", ["workspace_id", "job_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_notes_workspace", "notes", ["workspace_id"])
    op.create_index("idx_notes_candidate", "notes", ["candidate_id"])

    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_activity_log_workspace", "activity_log", ["workspace_id"])
    op.create_index("idx_activity_log_candidate", "activity_log", ["candidate_id"])

    op.create_table(
        "interviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer()),
        sa.Column("round_name", sa.Text(), nullable=False),
        sa.Column("interviewer_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("interviewer_email", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheduled_at", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("meeting_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="Scheduled"),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="Pending"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_interviews_workspace", "interviews", ["workspace_id"])
    op.create_index("idx_interviews_candidate", "interviews", ["candidate_id"])
    op.create_index("idx_interviews_scheduled", "interviews", ["scheduled_at"])

    op.create_table(
        "security_migrations",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("applied_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("security_migrations")
    op.drop_table("interviews")
    op.drop_table("activity_log")
    op.drop_table("notes")
    op.drop_table("candidates")
    op.drop_table("jobs")
    op.drop_table("password_reset_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("users")
    op.drop_table("workspaces")
