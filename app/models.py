from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Rule(Base):
    __tablename__ = "rules"

    id = Column(
        Integer,
        primary_key=True,
    )

    keyword = Column(
        String(100),
        nullable=False,
        index=True,
    )

    dm_message = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    jobs = relationship(
        "DmJob",
        back_populates="rule",
    )


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    id = Column(
        Integer,
        primary_key=True,
    )

    event_id = Column(
        String(255),
        nullable=False,
        unique=True,
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_processed_events_created_at",
            "created_at",
        ),
    )


class DmJob(Base):
    __tablename__ = "dm_jobs"

    id = Column(
        Integer,
        primary_key=True,
    )

    rule_id = Column(
        Integer,
        ForeignKey(
            "rules.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    comment_id = Column(
        String(255),
        nullable=False,
    )

    user_id = Column(
        String(255),
        nullable=False,
    )

    message = Column(
        Text,
        nullable=False,
    )

    status = Column(
        String(50),
        nullable=False,
        default="queued",
    )

    dm_id = Column(
        String(255),
        nullable=True,
    )

    attempts = Column(
        Integer,
        nullable=False,
        default=0,
    )

    next_retry_at = Column(
        DateTime,
        nullable=True,
    )

    last_error = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    rule = relationship(
        "Rule",
        back_populates="jobs",
    )

    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "user_id",
            name="uq_dm_jobs_rule_user",
        ),

        Index(
            "idx_dm_jobs_status_retry",
            "status",
            "next_retry_at",
        ),

        Index(
            "idx_dm_jobs_rule_user",
            "rule_id",
            "user_id",
        ),

        Index(
            "idx_dm_jobs_user_id",
            "user_id",
        ),

        Index(
            "idx_dm_jobs_comment_id",
            "comment_id",
        ),

        Index(
            "idx_dm_jobs_dm_id",
            "dm_id",
        ),

        CheckConstraint(
            "attempts >= 0",
            name="ck_dm_jobs_attempts_nonnegative",
        ),

        CheckConstraint(
            "status IN "
            "('queued', 'processing', 'accepted', "
            "'retry', 'sent', 'failed')",
            name="ck_dm_jobs_status",
        ),
    )


class Stat(Base):
    __tablename__ = "stats"

    id = Column(
        Integer,
        primary_key=True,
    )

    duplicates_blocked = Column(
        Integer,
        nullable=False,
        default=0,
    )

    __table_args__ = (
        CheckConstraint(
            "duplicates_blocked >= 0",
            name="ck_stats_duplicates_nonnegative",
        ),
    )
