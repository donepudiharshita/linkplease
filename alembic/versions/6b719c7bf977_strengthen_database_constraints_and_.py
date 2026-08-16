"""strengthen database constraints and indexes

Revision ID: 6b719c7bf977
Revises:
Create Date: 2026-08-16 17:12:25.464660
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b719c7bf977"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Apply database improvements safely.

    Existing application data is preserved.
    """

    # ---------------------------------------------------------
    # DM JOBS
    # ---------------------------------------------------------

    with op.batch_alter_table("dm_jobs") as batch_op:

        batch_op.create_index(
            "idx_dm_jobs_comment_id",
            ["comment_id"],
            unique=False,
        )

        batch_op.create_index(
            "idx_dm_jobs_dm_id",
            ["dm_id"],
            unique=False,
        )

        batch_op.create_index(
            "idx_dm_jobs_rule_user",
            ["rule_id", "user_id"],
            unique=False,
        )

        batch_op.create_index(
            "idx_dm_jobs_status_retry",
            ["status", "next_retry_at"],
            unique=False,
        )

        batch_op.create_index(
            "idx_dm_jobs_user_id",
            ["user_id"],
            unique=False,
        )

        # Preserve the existing uniqueness rule.
        #
        # The database already has:
        #
        # unique_rule_user(rule_id, user_id)
        #
        # so we intentionally do not drop/recreate it.


    # ---------------------------------------------------------
    # PROCESSED EVENTS
    # ---------------------------------------------------------

    with op.batch_alter_table("processed_events") as batch_op:

        batch_op.create_index(
            "idx_processed_events_created_at",
            ["created_at"],
            unique=False,
        )


    # ---------------------------------------------------------
    # RULES
    # ---------------------------------------------------------

    with op.batch_alter_table("rules") as batch_op:

        batch_op.create_index(
            "ix_rules_keyword",
            ["keyword"],
            unique=False,
        )


def downgrade() -> None:
    """
    Remove indexes created by this migration.

    Existing application data is preserved.
    """

    # ---------------------------------------------------------
    # RULES
    # ---------------------------------------------------------

    with op.batch_alter_table("rules") as batch_op:

        batch_op.drop_index(
            "ix_rules_keyword",
        )


    # ---------------------------------------------------------
    # PROCESSED EVENTS
    # ---------------------------------------------------------

    with op.batch_alter_table("processed_events") as batch_op:

        batch_op.drop_index(
            "idx_processed_events_created_at",
        )


    # ---------------------------------------------------------
    # DM JOBS
    # ---------------------------------------------------------

    with op.batch_alter_table("dm_jobs") as batch_op:

        batch_op.drop_index(
            "idx_dm_jobs_user_id",
        )

        batch_op.drop_index(
            "idx_dm_jobs_status_retry",
        )

        batch_op.drop_index(
            "idx_dm_jobs_rule_user",
        )

        batch_op.drop_index(
            "idx_dm_jobs_dm_id",
        )

        batch_op.drop_index(
            "idx_dm_jobs_comment_id",
        )
