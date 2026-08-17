from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging

import httpx
from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .mock_api import get_dm_status, send_dm


logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
BATCH_SIZE = 50
WORKER_CONCURRENCY = 5

RECONCILE_DELAY_SECONDS = 10
MAX_RETRY_DELAY_SECONDS = 60
MAX_RATE_LIMIT_DELAY_SECONDS = 3600


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(tzinfo=None)


def calculate_retry_delay(
    attempts: int,
) -> int:
    """
    Bounded exponential backoff.

    attempt 1 -> 2s
    attempt 2 -> 4s
    attempt 3 -> 8s
    attempt 4 -> 16s
    attempt 5 -> 32s
    """

    return min(
        2 ** attempts,
        MAX_RETRY_DELAY_SECONDS,
    )


def schedule_retry(
    job: models.DmJob,
    *,
    error: str,
    delay: int,
) -> None:
    job.status = "retry"
    job.next_retry_at = (
        utc_now()
        + timedelta(seconds=delay)
    )
    job.last_error = error


def mark_failed(
    job: models.DmJob,
    error: str,
) -> None:
    job.status = "failed"
    job.next_retry_at = None
    job.last_error = error


def reconcile_accepted_jobs(
    db: Session,
) -> None:
    """
    Reconcile DMs previously accepted by PseudoGram.

    Accepted does not necessarily mean delivered.
    """

    now = utc_now()

    jobs = (
        db.query(models.DmJob)
        .filter(
            models.DmJob.status == "accepted",
            models.DmJob.dm_id.isnot(None),
            (
                models.DmJob.next_retry_at.is_(None)
                | (
                    models.DmJob.next_retry_at
                    <= now
                )
            ),
        )
        .order_by(models.DmJob.id)
        .limit(BATCH_SIZE)
        .all()
    )

    for job in jobs:
        try:
            logger.info(
                "Checking delivery job_id=%s dm_id=%s",
                job.id,
                job.dm_id,
            )

            response = get_dm_status(
                job.dm_id
            )

            logger.info(
                "Delivery status job_id=%s status_code=%s",
                job.id,
                response.status_code,
            )

            if response.status_code != 200:
                schedule_retry(
                    job,
                    error=(
                        "Delivery status check failed: "
                        f"HTTP {response.status_code}"
                    ),
                    delay=RECONCILE_DELAY_SECONDS,
                )

                db.commit()
                continue

            try:
                data = response.json()

            except ValueError as exc:
                schedule_retry(
                    job,
                    error=(
                        "Invalid delivery response: "
                        f"{exc}"
                    ),
                    delay=RECONCILE_DELAY_SECONDS,
                )

                db.commit()
                continue

            dm_status = data.get("status")

            if dm_status == "delivered":
                job.status = "sent"
                job.last_error = None
                job.next_retry_at = None

                db.commit()

                logger.info(
                    "DM delivered job_id=%s dm_id=%s",
                    job.id,
                    job.dm_id,
                )

            elif dm_status == "queued":
                job.next_retry_at = (
                    utc_now()
                    + timedelta(
                        seconds=RECONCILE_DELAY_SECONDS
                    )
                )
                job.last_error = None

                db.commit()

            elif dm_status == "failed":
                if job.attempts >= MAX_ATTEMPTS:
                    mark_failed(
                        job,
                        (
                            "PseudoGram reported delivery "
                            "failure after maximum attempts"
                        ),
                    )

                    db.commit()

                    logger.error(
                        "DM permanently failed "
                        "job_id=%s",
                        job.id,
                    )

                else:
                    delay = calculate_retry_delay(
                        job.attempts
                    )

                    schedule_retry(
                        job,
                        error=(
                            "PseudoGram reported delivery "
                            "failure"
                        ),
                        delay=delay,
                    )

                    db.commit()

                    logger.warning(
                        "DM delivery failed "
                        "job_id=%s retry_in=%ss",
                        job.id,
                        delay,
                    )

            else:
                schedule_retry(
                    job,
                    error=(
                        "Unknown PseudoGram delivery status: "
                        f"{dm_status}"
                    ),
                    delay=RECONCILE_DELAY_SECONDS,
                )

                db.commit()

                logger.warning(
                    "Unknown delivery status "
                    "job_id=%s status=%s",
                    job.id,
                    dm_status,
                )

        except httpx.RequestError as exc:
            db.rollback()

            try:
                schedule_retry(
                    job,
                    error=(
                        "Network error during reconciliation: "
                        f"{exc}"
                    ),
                    delay=RECONCILE_DELAY_SECONDS,
                )

                db.commit()

            except Exception:
                db.rollback()

                logger.exception(
                    "Could not persist reconciliation retry "
                    "job_id=%s",
                    job.id,
                )

        except Exception:
            db.rollback()

            logger.exception(
                "Unexpected reconciliation error "
                "job_id=%s",
                job.id,
            )


def get_pending_jobs(
    db: Session,
):
    """
    Fetch a bounded batch of jobs ready for processing.
    """

    now = utc_now()

    return (
        db.query(models.DmJob)
        .filter(
            models.DmJob.status.in_(
                ["queued", "retry"]
            ),
            (
                models.DmJob.next_retry_at.is_(None)
                | (
                    models.DmJob.next_retry_at
                    <= now
                )
            ),
            models.DmJob.attempts < MAX_ATTEMPTS,
        )
        .order_by(models.DmJob.id)
        .limit(BATCH_SIZE)
        .all()
    )


def process_single_job(
    db: Session,
    job: models.DmJob,
) -> None:
    """
    Process one DM job using the supplied SQLAlchemy session.
    """

    logger.info(
        "Processing DM job_id=%s attempt=%s/%s",
        job.id,
        job.attempts,
        MAX_ATTEMPTS,
    )

    job.status = "processing"
    job.attempts += 1

    db.commit()

    try:
        response = send_dm(
            recipient_user_id=job.user_id,
            message=job.message,
            comment_id=job.comment_id,
            idempotency_key=f"dm-job-{job.id}",
        )

        logger.info(
            "PseudoGram send job_id=%s status_code=%s",
            job.id,
            response.status_code,
        )

        if response.status_code in (200, 202):
            try:
                data = response.json()

            except ValueError as exc:
                error = (
                    "Invalid PseudoGram success response: "
                    f"{exc}"
                )

                if job.attempts >= MAX_ATTEMPTS:
                    mark_failed(
                        job,
                        error,
                    )

                else:
                    schedule_retry(
                        job,
                        error=error,
                        delay=calculate_retry_delay(
                            job.attempts
                        ),
                    )

                db.commit()
                return

            dm_id = data.get("dm_id")

            if not dm_id:
                error = (
                    "PseudoGram success response "
                    "did not contain dm_id"
                )

                if job.attempts >= MAX_ATTEMPTS:
                    mark_failed(
                        job,
                        error,
                    )

                else:
                    schedule_retry(
                        job,
                        error=error,
                        delay=calculate_retry_delay(
                            job.attempts
                        ),
                    )

                db.commit()
                return

            job.dm_id = dm_id
            job.status = "accepted"
            job.last_error = None
            job.next_retry_at = (
                utc_now()
                + timedelta(
                    seconds=RECONCILE_DELAY_SECONDS
                )
            )

            db.commit()

            logger.info(
                "DM accepted job_id=%s dm_id=%s",
                job.id,
                dm_id,
            )

            return

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After",
                "60",
            )

            try:
                retry_seconds = int(
                    retry_after
                )

            except (
                TypeError,
                ValueError,
            ):
                retry_seconds = 60

            retry_seconds = max(
                1,
                min(
                    retry_seconds,
                    MAX_RATE_LIMIT_DELAY_SECONDS,
                ),
            )

            schedule_retry(
                job,
                error="rate_limited",
                delay=retry_seconds,
            )

            db.commit()

            logger.warning(
                "DM rate limited "
                "job_id=%s retry_in=%ss",
                job.id,
                retry_seconds,
            )

            return

        if response.status_code >= 500:
            error = (
                "Server error from PseudoGram: "
                f"HTTP {response.status_code}: "
                f"{response.text}"
            )

            if job.attempts >= MAX_ATTEMPTS:
                mark_failed(
                    job,
                    error,
                )

                db.commit()

                logger.error(
                    "DM permanently failed "
                    "job_id=%s attempts=%s",
                    job.id,
                    job.attempts,
                )

            else:
                delay = calculate_retry_delay(
                    job.attempts
                )

                schedule_retry(
                    job,
                    error=error,
                    delay=delay,
                )

                db.commit()

                logger.warning(
                    "DM server error "
                    "job_id=%s retry_in=%ss",
                    job.id,
                    delay,
                )

            return

        error = (
            "Permanent PseudoGram error: "
            f"HTTP {response.status_code}: "
            f"{response.text}"
        )

        mark_failed(
            job,
            error,
        )

        db.commit()

        logger.error(
            "DM permanently failed "
            "job_id=%s status_code=%s",
            job.id,
            response.status_code,
        )

    except httpx.RequestError as exc:
        db.rollback()

        error = (
            f"Network error while sending DM: {exc}"
        )

        try:
            if job.attempts >= MAX_ATTEMPTS:
                mark_failed(
                    job,
                    error,
                )

            else:
                schedule_retry(
                    job,
                    error=error,
                    delay=calculate_retry_delay(
                        job.attempts
                    ),
                )

            db.commit()

        except Exception:
            db.rollback()

            logger.exception(
                "Could not persist network-error state "
                "job_id=%s",
                job.id,
            )

    except Exception:
        db.rollback()

        logger.exception(
            "Unexpected error processing job_id=%s",
            job.id,
        )


def process_single_job_by_id(
    job_id: int,
) -> None:
    """
    Process one job using an isolated database session.

    A separate session is required because SQLAlchemy sessions
    must not be shared between worker threads.
    """

    db = SessionLocal()

    try:
        job = (
            db.query(models.DmJob)
            .filter(
                models.DmJob.id == job_id,
            )
            .first()
        )

        if job is None:
            logger.warning(
                "Worker job disappeared before processing "
                "job_id=%s",
                job_id,
            )
            return

        if job.status not in (
            "queued",
            "retry",
        ):
            logger.info(
                "Skipping job_id=%s status=%s",
                job_id,
                job.status,
            )
            return

        now = utc_now()

        if (
            job.next_retry_at is not None
            and job.next_retry_at > now
        ):
            return

        if job.attempts >= MAX_ATTEMPTS:
            return

        process_single_job(
            db,
            job,
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Worker task failed job_id=%s",
            job_id,
        )

    finally:
        db.close()


def process_jobs(
    db: Session,
) -> None:
    """
    Reconcile accepted DMs and process pending jobs.

    Pending jobs are processed concurrently with a bounded
    worker pool. Each job gets its own database session.
    """

    reconcile_accepted_jobs(db)

    jobs = get_pending_jobs(db)

    job_ids = [
        job.id
        for job in jobs
    ]

    if not job_ids:
        return

    logger.info(
        "Dispatching %s jobs with concurrency=%s",
        len(job_ids),
        WORKER_CONCURRENCY,
    )

    with ThreadPoolExecutor(
        max_workers=WORKER_CONCURRENCY,
        thread_name_prefix="dm-worker",
    ) as executor:
        futures = [
            executor.submit(
                process_single_job_by_id,
                job_id,
            )
            for job_id in job_ids
        ]

        for future in futures:
            try:
                future.result()

            except Exception:
                logger.exception(
                    "Unexpected worker future failure"
                )

