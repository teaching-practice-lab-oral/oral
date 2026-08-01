"""Add v2.0.3 upload and export admission data.

Revision ID: 002
Revises: 001
Create Date: 2026-08-01

The retired prompt-template tables and assignment columns are intentionally
left in place. Oral upgrades may contain historical template data, while the
v2.0.3 application no longer exposes or consumes those settings.
"""

from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "costly_action_usage_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("units_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("called_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "action IN ('audio_upload', 'photo_upload', 'student_result_export')",
            name="ck_costly_action_usage_logs_action",
        ),
        sa.CheckConstraint(
            "units_bytes >= 0",
            name="ck_costly_action_usage_logs_units_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_costly_action_user_action_called",
        "costly_action_usage_logs",
        ["user_id", "action", "called_at"],
        unique=False,
    )
    op.create_index(
        "ix_costly_action_action_resource_called",
        "costly_action_usage_logs",
        ["action", "resource_id", "called_at"],
        unique=False,
    )
    op.add_column(
        "submission_reflections",
        sa.Column("photo_validation_version", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_submission_reflections_photo_validation_version",
        "submission_reflections",
        "photo_validation_version IS NULL OR photo_validation_version = 1",
    )


def downgrade():
    op.drop_constraint(
        "ck_submission_reflections_photo_validation_version",
        "submission_reflections",
        type_="check",
    )
    op.drop_column("submission_reflections", "photo_validation_version")
    op.drop_index(
        "ix_costly_action_action_resource_called",
        table_name="costly_action_usage_logs",
    )
    op.drop_index(
        "ix_costly_action_user_action_called",
        table_name="costly_action_usage_logs",
    )
    op.drop_table("costly_action_usage_logs")
