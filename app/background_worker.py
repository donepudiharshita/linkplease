import logging

from sqlalchemy import func

from .config import WORKER_POLL_INTERVAL_SECONDS
from .database import SessionLocal
from . import models
from .worker import process_jobs


logger = logging.getLogger(__name__)


def log_job_status_summary() -> None:
    """
    Log the current database job-status breakdown so deployment
    behavior can be diagnosed without exposing job data through
    the public API.
    """

    db = SessionLocal()

    try:
        rows = (
            db.query(
                models.DmJob.status,
                func.count(models.DmJob.id),
            )
            .group_by(models.DmJob.status)
            .all()
        )

        summary = {
            status: count
            for status, count in rows
        }

        logger.info(
            "Worker job status summary: %s",
            summary,
        )

    except Exception:
        logger.exception(
            "Could not read worker job status summary"
        )

    finally:
        db.close()


def run_worker_once() -> None:
    """
    Process one bounded worker cycle using a fresh database session.
    """

    logger.info("Background worker cycle started")

    db = SessionLocal()

    try:
        process_jobs(db)

    except Exception:
        db.rollback()

        logger.exception(
            "Background worker cycle failed"
        )

    finally:
        db.close()

    log_job_status_summary()

    logger.info("Background worker cycle finished")


def run_worker_forever() -> None:
    """
    Continuously poll the database for pending work.

    The queue itself is stored in the database, so queued/retryable
    jobs survive application restarts.
    """

    logger.info(
        "Background worker started poll_interval=%ss",
        WORKER_POLL_INTERVAL_SECONDS,
    )

    while True:
        run_worker_once()

