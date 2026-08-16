import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .background_worker import run_worker_once
from .config import (
    RUN_BACKGROUND_WORKER,
)
from .database import get_db
from .schemas import RuleCreate, RuleResponse, WebhookEvent


logger = logging.getLogger(__name__)


async def background_worker_loop() -> None:
    """
    Run the database-backed worker without blocking FastAPI's
    event loop.
    """

    while True:
        await asyncio.to_thread(
            run_worker_once
        )

        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = None

    if RUN_BACKGROUND_WORKER:
        logger.info(
            "Starting embedded background worker"
        )

        worker_task = asyncio.create_task(
            background_worker_loop()
        )

    yield

    if worker_task is not None:
        worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="LinkPlease Assignment",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def home():
    return {
        "message": "LinkPlease API is running",
        "version": "1.0.0",
    }


@app.get("/health")
def health_check(
    db: Session = Depends(get_db),
):
    """
    Readiness/health endpoint.

    Verifies both the API process and database connection.
    """

    try:
        db.execute(text("SELECT 1"))

    except Exception:
        logger.exception(
            "Health check database query failed"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    return {
        "status": "healthy",
    }


@app.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rule(
    rule: RuleCreate,
    db: Session = Depends(get_db),
):
    keyword = rule.keyword.strip()
    dm_message = rule.dm_message.strip()

    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keyword cannot be empty",
        )

    if not dm_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dm_message cannot be empty",
        )

    new_rule = models.Rule(
        keyword=keyword,
        dm_message=dm_message,
    )

    db.add(new_rule)

    try:
        db.commit()
        db.refresh(new_rule)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Could not create rule because "
                "of a database constraint"
            ),
        )

    except Exception:
        db.rollback()
        raise

    return {
        "rule_id": str(new_rule.id),
        "keyword": new_rule.keyword,
        "dm_message": new_rule.dm_message,
    }


@app.post("/webhook")
def receive_webhook(
    event: WebhookEvent,
    db: Session = Depends(get_db),
):
    existing_event = (
        db.query(models.ProcessedEvent)
        .filter(
            models.ProcessedEvent.event_id == event.event_id
        )
        .first()
    )

    if existing_event:
        return {
            "status": "duplicate_event",
        }

    try:
        processed_event = models.ProcessedEvent(
            event_id=event.event_id,
        )

        db.add(processed_event)

        if event.event_type != "comment.created":
            db.commit()

            return {
                "status": "ignored",
            }

        comment_text = (
            event.data.text or ""
        ).strip()

        normalized_comment = comment_text.casefold()

        user_id = event.data.from_.user_id
        comment_id = event.data.comment_id

        rules = (
            db.query(models.Rule)
            .order_by(models.Rule.id)
            .all()
        )

        matched_rules = []
        jobs_created = []
        duplicates_blocked = 0

        for rule in rules:
            normalized_keyword = (
                rule.keyword.strip().casefold()
            )

            if not normalized_keyword:
                continue

            if normalized_keyword not in normalized_comment:
                continue

            matched_rules.append(rule.id)

            existing_job = (
                db.query(models.DmJob)
                .filter(
                    models.DmJob.rule_id == rule.id,
                    models.DmJob.user_id == user_id,
                )
                .first()
            )

            if existing_job:
                duplicates_blocked += 1

                stat = (
                    db.query(models.Stat)
                    .first()
                )

                if stat is None:
                    stat = models.Stat(
                        duplicates_blocked=0,
                    )
                    db.add(stat)

                stat.duplicates_blocked += 1

                continue

            job = models.DmJob(
                rule_id=rule.id,
                comment_id=comment_id,
                user_id=user_id,
                message=rule.dm_message,
                status="queued",
            )

            db.add(job)
            db.flush()

            jobs_created.append(job.id)

        db.commit()

        return {
            "status": "received",
            "matched_rules": matched_rules,
            "jobs_created": jobs_created,
            "duplicates_blocked": duplicates_blocked,
        }

    except IntegrityError:
        db.rollback()

        existing_event = (
            db.query(models.ProcessedEvent)
            .filter(
                models.ProcessedEvent.event_id == event.event_id
            )
            .first()
        )

        if existing_event:
            return {
                "status": "duplicate_event",
            }

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Webhook could not be processed "
                "because of a database conflict"
            ),
        )

    except Exception:
        db.rollback()
        raise


@app.post("/process-jobs")
def process_jobs_endpoint(
    db: Session = Depends(get_db),
):
    """
    Manual worker trigger retained for debugging and testing.
    """

    try:
        from .worker import process_jobs

        process_jobs(db)

    except Exception:
        db.rollback()
        raise

    return {
        "status": "processed",
    }


@app.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
):
    sent = (
        db.query(func.count(models.DmJob.id))
        .filter(
            models.DmJob.status == "sent",
        )
        .scalar()
        or 0
    )

    failed = (
        db.query(func.count(models.DmJob.id))
        .filter(
            models.DmJob.status == "failed",
        )
        .scalar()
        or 0
    )

    queued = (
        db.query(func.count(models.DmJob.id))
        .filter(
            models.DmJob.status.in_(
                [
                    "queued",
                    "processing",
                    "retry",
                    "accepted",
                ]
            ),
        )
        .scalar()
        or 0
    )

    stat = (
        db.query(models.Stat)
        .first()
    )

    duplicates_blocked = (
        stat.duplicates_blocked
        if stat is not None
        else 0
    )

    return {
        "sent": sent,
        "failed": failed,
        "queued": queued,
        "duplicates_blocked": duplicates_blocked,
    }