import logging
import time

from .config import WORKER_POLL_INTERVAL_SECONDS
from .database import SessionLocal
from .worker import process_jobs


logger = logging.getLogger(__name__)


def run_worker_once() -> None:
    """
    Process one bounded worker cycle using a fresh database session.
    """

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


def run_worker_forever() -> None:
    """
    Continuously poll the database for pending work.

    The queue itself is the database, so a process restart does
    not lose queued or retryable jobs.
    """

    logger.info(
        "Background worker started poll_interval=%ss",
        WORKER_POLL_INTERVAL_SECONDS,
    )

    while True:
        started_at = time.monotonic()

        run_worker_once()

        elapsed = time.monotonic() - started_at
        sleep_seconds = max(
            0,
            WORKER_POLL_INTERVAL_SECONDS - elapsed,
        )

        time.sleep(sleep_seconds)