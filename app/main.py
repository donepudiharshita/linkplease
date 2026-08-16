from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .schemas import RuleCreate, RuleResponse, WebhookEvent
from .worker import process_jobs


app = FastAPI(
    title="LinkPlease Assignment",
    version="1.0.0",
)


@app.get("/")
def home():
    return {
        "message": "LinkPlease API is running",
        "version": "1.0.0",
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
    """
    Create a keyword -> DM rule.

    Rules are stored in the database and are later evaluated
    when comment.created webhook events arrive.
    """

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
            detail="Could not create rule because of a database constraint",
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
    """
    Receive and process a PseudoGram webhook event.

    Important guarantees:

    1. Event IDs are idempotent.
    2. Duplicate events are ignored.
    3. Unsupported event types are recorded but ignored.
    4. Matching rules create asynchronous DM jobs.
    5. Database constraints provide the final duplicate protection.
    """

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

        # Record unsupported events as processed so that
        # repeated delivery of the same webhook does not
        # repeatedly execute application logic.
        if event.event_type != "comment.created":
            db.commit()

            return {
                "status": "ignored",
            }

        comment_text = (
            event.data.text or ""
        ).strip()

        user_id = event.data.from_.user_id
        comment_id = event.data.comment_id

        # Load all currently configured rules.
        rules = (
            db.query(models.Rule)
            .order_by(models.Rule.id)
            .all()
        )

        matched_rules = []
        jobs_created = []
        duplicates_blocked = 0

        normalized_comment = comment_text.casefold()

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

            jobs_created.append(rule.id)

        db.commit()

        return {
            "status": "received",
            "matched_rules": matched_rules,
            "jobs_created": jobs_created,
            "duplicates_blocked": duplicates_blocked,
        }

    except IntegrityError:
        """
        Concurrent webhook requests can both observe that an
        event does not exist and then attempt to insert it.

        The database UNIQUE constraint on event_id is the final
        source of truth for idempotency.
        """

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
            detail="Webhook could not be processed because of a database conflict",
        )

    except Exception:
        db.rollback()
        raise


@app.post("/process-jobs")
def process_jobs_endpoint(
    db: Session = Depends(get_db),
):
    """
    Process queued/retry DM jobs and reconcile accepted DMs.

    In a production deployment this operation would normally
    run in a dedicated worker process or scheduler rather than
    being triggered manually through the API.
    """

    try:
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
    """
    Return current DM processing statistics.
    """

    sent = (
        db.query(func.count(models.DmJob.id))
        .filter(
            models.DmJob.status == "sent",
        )
        .scalar()
    )

    failed = (
        db.query(func.count(models.DmJob.id))
        .filter(
            models.DmJob.status == "failed",
        )
        .scalar()
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
        "sent": sent or 0,
        "failed": failed or 0,
        "queued": queued or 0,
        "duplicates_blocked": duplicates_blocked or 0,
    }


@app.get("/health")
def health_check():
    """
    Basic application health endpoint.

    This verifies that the FastAPI application process is
    responding. Database dependency health is intentionally
    kept separate from this lightweight endpoint.
    """

    return {
        "status": "healthy",
    }
