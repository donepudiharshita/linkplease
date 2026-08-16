from app import models


def create_rule(client, keyword="link", message="Here is your link!"):
    response = client.post(
        "/rules",
        json={
            "keyword": keyword,
            "dm_message": message,
        },
    )

    assert response.status_code == 201
    return response


def webhook_payload(
    event_id="test-event-001",
    text="I need the link please",
    user_id="test-user-001",
    comment_id="test-comment-001",
):
    return {
        "event_id": event_id,
        "event_type": "comment.created",
        "sent_at": "2026-08-16T12:00:00Z",
        "data": {
            "comment_id": comment_id,
            "post_id": "test-post-001",
            "text": text,
            "created_at": "2026-08-16T12:00:00Z",
            "from": {
                "user_id": user_id,
                "username": "test_user",
            },
        },
    }


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
    }


def test_home_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "LinkPlease API is running"
    assert data["version"] == "1.0.0"


def test_create_rule(client):
    response = create_rule(
        client,
        keyword="link",
        message="Here is your requested link!",
    )

    data = response.json()

    assert data["rule_id"] == "1"
    assert data["keyword"] == "link"
    assert data["dm_message"] == "Here is your requested link!"


def test_create_rule_rejects_empty_keyword(client):
    response = client.post(
        "/rules",
        json={
            "keyword": "",
            "dm_message": "Here is your link!",
        },
    )

    assert response.status_code == 422


def test_create_rule_rejects_empty_message(client):
    response = client.post(
        "/rules",
        json={
            "keyword": "link",
            "dm_message": "",
        },
    )

    assert response.status_code == 422


def test_webhook_creates_job_when_keyword_matches(
    client,
    db_session,
):
    create_rule(client)

    response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="matching-event-001",
            text="Can you please send me the link?",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "received"
    assert data["matched_rules"] == [1]
    assert data["jobs_created"] == [1]
    assert data["duplicates_blocked"] == 0

    job = db_session.query(models.DmJob).first()

    assert job is not None
    assert job.rule_id == 1
    assert job.user_id == "test-user-001"
    assert job.comment_id == "test-comment-001"
    assert job.message == "Here is your link!"
    assert job.status == "queued"


def test_webhook_is_case_insensitive(
    client,
    db_session,
):
    create_rule(
        client,
        keyword="LINK",
        message="Here is your link!",
    )

    response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="case-event-001",
            text="I NEED THE link PLEASE",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["matched_rules"] == [1]
    assert data["jobs_created"] == [1]

    job = db_session.query(models.DmJob).first()

    assert job is not None


def test_webhook_does_not_create_job_when_keyword_does_not_match(
    client,
    db_session,
):
    create_rule(client)

    response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="no-match-event-001",
            text="Hello, how are you?",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "received"
    assert data["matched_rules"] == []
    assert data["jobs_created"] == []

    job_count = (
        db_session.query(models.DmJob)
        .count()
    )

    assert job_count == 0


def test_duplicate_webhook_event_is_blocked(
    client,
    db_session,
):
    create_rule(client)

    payload = webhook_payload(
        event_id="duplicate-event-001",
        text="I need the link",
    )

    first_response = client.post(
        "/webhook",
        json=payload,
    )

    assert first_response.status_code == 200
    assert first_response.json()["jobs_created"] == [1]

    second_response = client.post(
        "/webhook",
        json=payload,
    )

    assert second_response.status_code == 200
    assert second_response.json() == {
        "status": "duplicate_event",
    }

    event_count = (
        db_session.query(models.ProcessedEvent)
        .filter(
            models.ProcessedEvent.event_id
            == "duplicate-event-001"
        )
        .count()
    )

    job_count = (
        db_session.query(models.DmJob)
        .count()
    )

    assert event_count == 1
    assert job_count == 1


def test_duplicate_user_rule_job_is_blocked(
    client,
    db_session,
):
    create_rule(client)

    first_response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="user-rule-event-001",
            text="send link",
            user_id="same-user-001",
            comment_id="comment-001",
        ),
    )

    assert first_response.status_code == 200
    assert first_response.json()["jobs_created"] == [1]

    second_response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="user-rule-event-002",
            text="send link again",
            user_id="same-user-001",
            comment_id="comment-002",
        ),
    )

    assert second_response.status_code == 200

    data = second_response.json()

    assert data["matched_rules"] == [1]
    assert data["jobs_created"] == []
    assert data["duplicates_blocked"] == 1

    job_count = (
        db_session.query(models.DmJob)
        .count()
    )

    assert job_count == 1


def test_unsupported_event_type_is_ignored(
    client,
    db_session,
):
    response = client.post(
        "/webhook",
        json={
            "event_id": "unsupported-event-001",
            "event_type": "post.created",
            "sent_at": "2026-08-16T12:00:00Z",
            "data": {
                "comment_id": "comment-unsupported",
                "text": "link",
                "from": {
                    "user_id": "unsupported-user",
                },
            },
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "status": "ignored",
    }

    processed_event = (
        db_session.query(models.ProcessedEvent)
        .filter(
            models.ProcessedEvent.event_id
            == "unsupported-event-001"
        )
        .first()
    )

    assert processed_event is not None

    job_count = (
        db_session.query(models.DmJob)
        .count()
    )

    assert job_count == 0


def test_stats_returns_expected_structure(client):
    response = client.get("/stats")

    assert response.status_code == 200

    data = response.json()

    assert "sent" in data
    assert "failed" in data
    assert "queued" in data
    assert "duplicates_blocked" in data

    assert data["sent"] == 0
    assert data["failed"] == 0
    assert data["queued"] == 0
    assert data["duplicates_blocked"] == 0


def test_multiple_rules_can_match_one_comment(
    client,
    db_session,
):
    create_rule(
        client,
        keyword="link",
        message="Here is the link!",
    )

    create_rule(
        client,
        keyword="please",
        message="Thanks for asking!",
    )

    response = client.post(
        "/webhook",
        json=webhook_payload(
            event_id="multi-rule-event-001",
            text="please send me the link",
        ),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["matched_rules"] == [1, 2]
    assert data["jobs_created"] == [1, 2]
    assert data["duplicates_blocked"] == 0

    jobs = (
        db_session.query(models.DmJob)
        .order_by(models.DmJob.id)
        .all()
    )

    assert len(jobs) == 2
    assert jobs[0].message == "Here is the link!"
    assert jobs[1].message == "Thanks for asking!"


def test_webhook_requires_sent_at(client):
    response = client.post(
        "/webhook",
        json={
            "event_id": "missing-sent-at",
            "event_type": "comment.created",
            "data": {
                "comment_id": "comment-001",
                "text": "link",
                "from": {
                    "user_id": "user-001",
                },
            },
        },
    )

    assert response.status_code == 422


def test_webhook_requires_event_id(client):
    response = client.post(
        "/webhook",
        json={
            "event_type": "comment.created",
            "sent_at": "2026-08-16T12:00:00Z",
            "data": {
                "comment_id": "comment-001",
                "text": "link",
                "from": {
                    "user_id": "user-001",
                },
            },
        },
    )

    assert response.status_code == 422
