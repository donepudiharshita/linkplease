from datetime import timedelta
from unittest.mock import MagicMock

import httpx

from app import models
from app import worker


def make_response(
    status_code,
    json_data=None,
    headers=None,
):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = headers or {}
    response.text = str(json_data or "")

    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError("invalid json")

    return response


def create_job(
    db_session,
    status="queued",
    attempts=0,
):
    rule = models.Rule(
        keyword="link",
        dm_message="Here is your link!",
    )

    db_session.add(rule)
    db_session.flush()

    job = models.DmJob(
        rule_id=rule.id,
        comment_id="comment-worker-test",
        user_id="worker-test-user",
        message="Here is your link!",
        status=status,
        attempts=attempts,
    )

    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    return job


def test_successful_dm_moves_job_to_accepted(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    response = make_response(
        202,
        {
            "dm_id": "dm_test_001",
            "status": "accepted",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "accepted"
    assert job.dm_id == "dm_test_001"
    assert job.attempts == 1
    assert job.last_error is None
    assert job.next_retry_at is not None


def test_server_error_schedules_retry(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    response = make_response(
        500,
        {
            "detail": "internal_error",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.attempts == 1
    assert job.next_retry_at is not None
    assert job.last_error is not None


def test_rate_limit_uses_retry_after(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    before = worker.utc_now()

    response = make_response(
        429,
        {
            "detail": "rate_limited",
        },
        headers={
            "Retry-After": "30",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    after = worker.utc_now()

    assert job.status == "retry"
    assert job.last_error == "rate_limited"
    assert job.next_retry_at is not None

    expected_lower = before + timedelta(seconds=29)
    expected_upper = after + timedelta(seconds=31)

    assert expected_lower <= job.next_retry_at <= expected_upper


def test_network_error_schedules_retry(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    def raise_network_error(**kwargs):
        raise httpx.ConnectError(
            "connection failed",
        )

    monkeypatch.setattr(
        worker,
        "send_dm",
        raise_network_error,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.attempts == 1
    assert job.next_retry_at is not None
    assert "Network error" in job.last_error


def test_max_attempts_permanently_fails_server_error(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        attempts=worker.MAX_ATTEMPTS - 1,
    )

    response = make_response(
        500,
        {
            "detail": "internal_error",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "failed"
    assert job.attempts == worker.MAX_ATTEMPTS
    assert job.next_retry_at is None
    assert "Server error" in job.last_error


def test_permanent_4xx_failure(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    response = make_response(
        400,
        {
            "detail": "invalid_request",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "failed"
    assert job.next_retry_at is None
    assert "Permanent PseudoGram error" in job.last_error


def test_accepted_job_becomes_sent_when_delivered(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        status="accepted",
    )

    job.dm_id = "dm_delivery_001"
    job.next_retry_at = worker.utc_now()
    db_session.commit()

    response = make_response(
        200,
        {
            "dm_id": "dm_delivery_001",
            "status": "delivered",
        },
    )

    monkeypatch.setattr(
        worker,
        "get_dm_status",
        lambda dm_id: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "sent"
    assert job.last_error is None
    assert job.next_retry_at is None


def test_accepted_job_stays_accepted_when_queued(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        status="accepted",
    )

    job.dm_id = "dm_delivery_queued"
    job.next_retry_at = worker.utc_now()
    db_session.commit()

    response = make_response(
        200,
        {
            "dm_id": "dm_delivery_queued",
            "status": "queued",
        },
    )

    monkeypatch.setattr(
        worker,
        "get_dm_status",
        lambda dm_id: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "accepted"
    assert job.next_retry_at is not None
    assert job.last_error is None


def test_delivery_failure_schedules_retry(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        status="accepted",
    )

    job.dm_id = "dm_delivery_failed"
    job.next_retry_at = worker.utc_now()
    db_session.commit()

    response = make_response(
        200,
        {
            "dm_id": "dm_delivery_failed",
            "status": "failed",
        },
    )

    monkeypatch.setattr(
        worker,
        "get_dm_status",
        lambda dm_id: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.next_retry_at is not None
    assert "delivery failure" in job.last_error.lower()


def test_delivery_network_error_is_retried(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        status="accepted",
    )

    job.dm_id = "dm_network_error"
    job.next_retry_at = worker.utc_now()
    db_session.commit()

    def raise_network_error(dm_id):
        raise httpx.ConnectError(
            "delivery check failed",
        )

    monkeypatch.setattr(
        worker,
        "get_dm_status",
        raise_network_error,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.next_retry_at is not None
    assert "Network error during reconciliation" in job.last_error


def test_malformed_success_response_is_retried(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    response = make_response(
        202,
        None,
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.next_retry_at is not None
    assert "Invalid PseudoGram success response" in job.last_error


def test_success_without_dm_id_is_retried(
    db_session,
    monkeypatch,
):
    job = create_job(db_session)

    response = make_response(
        202,
        {
            "status": "accepted",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_dm",
        lambda **kwargs: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.next_retry_at is not None
    assert "did not contain dm_id" in job.last_error


def test_unknown_delivery_status_is_retried(
    db_session,
    monkeypatch,
):
    job = create_job(
        db_session,
        status="accepted",
    )

    job.dm_id = "dm_unknown_status"
    job.next_retry_at = worker.utc_now()
    db_session.commit()

    response = make_response(
        200,
        {
            "dm_id": "dm_unknown_status",
            "status": "processing",
        },
    )

    monkeypatch.setattr(
        worker,
        "get_dm_status",
        lambda dm_id: response,
    )

    worker.process_jobs(db_session)

    db_session.refresh(job)

    assert job.status == "retry"
    assert job.next_retry_at is not None
    assert "Unknown PseudoGram delivery status" in job.last_error
