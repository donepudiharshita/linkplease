"""bootstrap complete application schema

Revision ID: 6b719c7bf977
Revises:
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b719c7bf977"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "keyword",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "dm_message",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_rules_keyword",
        "rules",
        ["keyword"],
        unique=False,
    )

    op.create_table(
        "processed_events",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "event_id",
            name="uq_processed_events_event_id",
        ),
    )

    op.create_index(
        "idx_processed_events_created_at",
        "processed_events",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "dm_jobs",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "dm_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["rules.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "rule_id",
            "user_id",
            name="uq_dm_jobs_rule_user",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_dm_jobs_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN "
            "('queued', 'processing', 'accepted', "
            "'retry', 'sent', 'failed')",
            name="ck_dm_jobs_status",
        ),
    )

    op.create_index(
        "idx_dm_jobs_status_retry",
        "dm_jobs",
        ["status", "next_retry_at"],
        unique=False,
    )

    op.create_index(
        "idx_dm_jobs_rule_user",
        "dm_jobs",
        ["rule_id", "user_id"],
        unique=False,
    )

    op.create_index(
        "idx_dm_jobs_user_id",
        "dm_jobs",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "idx_dm_jobs_comment_id",
        "dm_jobs",
        ["comment_id"],
        unique=False,
    )

    op.create_index(
        "idx_dm_jobs_dm_id",
        "dm_jobs",
        ["dm_id"],
        unique=False,
    )

    op.create_table(
        "stats",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "duplicates_blocked",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "duplicates_blocked >= 0",
            name="ck_stats_duplicates_nonnegative",
        ),
    )


def downgrade() -> None:
    op.drop_table("stats")

    op.drop_index(
        "idx_dm_jobs_dm_id",
        table_name="dm_jobs",
    )
    op.drop_index(
        "idx_dm_jobs_comment_id",
        table_name="dm_jobs",
    )
    op.drop_index(
        "idx_dm_jobs_user_id",
        table_name="dm_jobs",
    )
    op.drop_index(
        "idx_dm_jobs_rule_user",
        table_name="dm_jobs",
    )
    op.drop_index(
        "idx_dm_jobs_status_retry",
        table_name="dm_jobs",
    )

    op.drop_table("dm_jobs")

    op.drop_index(
        "idx_processed_events_created_at",
        table_name="processed_events",
    )

    op.drop_table("processed_events")

    op.drop_index(
        "ix_rules_keyword",
        table_name="rules",
    )

    op.drop_table("rules")