# LinkPlease

A webhook-driven DM automation service built with FastAPI, SQLAlchemy, PseudoGram, and Alembic.

The service receives comment webhooks, matches configured keywords, creates asynchronous DM jobs, sends DMs through PseudoGram, retries temporary failures, and reconciles accepted DMs until delivery is confirmed.

## Architecture

```text
PseudoGram Webhook
        |
        v
   FastAPI /webhook
        |
        +----> Idempotency check
        |
        +----> Rule matching
        |
        +----> Duplicate-job protection
        |
        v
      SQLite
        |
        v
     DmJob
        |
        v
POST /process-jobs
        |
        +----> Send DM to PseudoGram
        |
        +----> Retry 429 / 5xx / network failures
        |
        v
     accepted
        |
        v
Delivery reconciliation
        |
   +----+----+
   |         |
queued   delivered
             |
             v
            sent
```

## Features

* FastAPI REST API
* Webhook processing for `comment.created`
* Keyword-based rule matching
* Database-backed DM job queue
* Webhook idempotency using unique event IDs
* Database-level duplicate job protection
* PseudoGram API integration
* Idempotency keys for DM sends
* Exponential backoff for temporary server/network failures
* `429 Retry-After` support
* Maximum retry attempts
* Accepted vs delivered state separation
* Delivery status reconciliation
* Batch job processing
* Health endpoint
* SQLite database for local development
* Alembic database migrations
* Environment-based configuration
* Automated API and worker tests

## Project Structure

```text
linkplease-assignment/
├── app/
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── mock_api.py
│   ├── models.py
│   ├── schemas.py
│   └── worker.py
├── alembic/
│   ├── versions/
│   └── env.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   └── test_worker.py
├── .env
├── .env.example
├── .gitignore
├── alembic.ini
├── requirements.txt
└── README.md
```

## Requirements

* Python 3.14+
* PseudoGram API credentials

## Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Environment Configuration

Create a `.env` file in the project root.

Example:

```text
PSEUDOGRAM_API_KEY=your_real_api_key
PSEUDOGRAM_BASE_URL=https://pseudogram-api.onrender.com
PSEUDOGRAM_TIMEOUT_SECONDS=10
DATABASE_URL=sqlite:///./linkplease.db
```

Do not commit `.env`.

Use `.env.example` as the safe configuration template.

## Database

The application uses SQLite by default:

```text
sqlite:///./linkplease.db
```

Database schema changes are managed with Alembic.

Apply migrations with:

```powershell
alembic upgrade head
```

Check the current migration revision:

```powershell
alembic current
```

## Running the Application

Start the API:

```powershell
uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
GET /health
```

## API Endpoints

### `GET /`

Basic application information.

### `GET /health`

Lightweight health endpoint.

Example response:

```json
{
  "status": "healthy"
}
```

### `POST /rules`

Create a keyword-triggered DM rule.

Example:

```json
{
  "keyword": "link",
  "dm_message": "Here is the link you requested!"
}
```

### `POST /webhook`

Accept a webhook event from PseudoGram.

Example:

```json
{
  "event_id": "event-001",
  "event_type": "comment.created",
  "sent_at": "2026-08-16T06:00:00Z",
  "data": {
    "comment_id": "comment-001",
    "post_id": "post-001",
    "text": "I would like a link please",
    "created_at": "2026-08-16T06:00:00Z",
    "from": {
      "user_id": "user-001",
      "username": "test_user"
    }
  }
}
```

The webhook:

1. Validates the event.
2. Checks whether the event was already processed.
3. Stores the event inside the same transaction as job creation.
4. Matches configured rules.
5. Prevents duplicate jobs for the same rule and user.
6. Returns immediately without sending the DM synchronously.

### `POST /process-jobs`

Processes queued/retry jobs and reconciles accepted DMs.

Example response:

```json
{
  "status": "processed"
}
```

### `GET /stats`

Returns current processing statistics.

Example:

```json
{
  "sent": 6,
  "failed": 0,
  "queued": 0,
  "duplicates_blocked": 2
}
```

## Job Lifecycle

A DM job follows this lifecycle:

```text
queued
   |
   v
processing
   |
   +----> retry ----+
   |                |
   |                v
   |           processing
   |
   +----> accepted
             |
             v
       reconciliation
             |
        +----+----+
        |         |
     queued    delivered
                  |
                  v
                 sent
```

A permanent error moves the job to:

```text
failed
```

## Retry Strategy

Temporary failures are retried with bounded exponential backoff.

Current retry delays are approximately:

```text
attempt 1 -> 2 seconds
attempt 2 -> 4 seconds
attempt 3 -> 8 seconds
attempt 4 -> 16 seconds
attempt 5 -> 32 seconds
```

The retry delay is capped.

### HTTP 429

The worker reads the `Retry-After` header when available and schedules the next attempt accordingly.

### HTTP 5xx

Server failures use exponential backoff until the maximum attempt count is reached.

### Network errors

Network failures are treated as retryable.

### Permanent 4xx errors

Client-side errors other than `429` are treated as permanent failures.

## Idempotency

Two layers protect against duplicate processing.

### Webhook idempotency

`ProcessedEvent.event_id` is unique in the database.

This means repeated delivery of the same webhook event does not create another processing operation.

### DM job idempotency

`DmJob` has a unique `(rule_id, user_id)` constraint.

Additionally, each job is sent to PseudoGram using a deterministic idempotency key:

```text
dm-job-{job_id}
```

This protects the external send operation when the application retries after a network failure.

## Delivery Reconciliation

A successful PseudoGram send response means the request was accepted, not necessarily delivered.

Therefore:

```text
accepted != sent
```

Accepted jobs are checked again through the PseudoGram delivery-status API.

Only when PseudoGram reports:

```text
delivered
```

does the job transition to:

```text
sent
```

## Database Design

The main tables are:

### `rules`

Stores keyword-triggered DM rules.

### `processed_events`

Stores webhook event IDs to provide idempotency.

### `dm_jobs`

Stores asynchronous DM work, including:

* rule
* user
* comment
* message
* status
* attempts
* retry time
* PseudoGram DM ID
* last error
* creation time

### `stats`

Stores the duplicate-event/job reporting counter.

The database also uses indexes for common worker and reconciliation lookups.

## Testing

The test suite covers both API behavior and worker reliability.

Run:

```powershell
pytest -q
```

The current suite covers:

* health endpoint
* rule creation
* rule validation
* webhook validation
* keyword matching
* case-insensitive matching
* multiple rule matches
* duplicate webhook events
* duplicate user/rule jobs
* unsupported event types
* statistics
* successful DM acceptance
* `500` retry behavior
* `429 Retry-After`
* network failures
* maximum attempts
* permanent `4xx` failures
* delivery reconciliation
* delivery failures
* malformed API responses
* missing `dm_id`
* unknown delivery states

## Configuration and Security

Secrets are loaded from environment variables.

The real `.env` file is excluded from Git.

The repository should contain `.env.example`, but never a real API key.

The local SQLite database is also excluded from Git.

## Production Considerations

The project is intentionally small and assignment-friendly while using production-oriented reliability patterns.

Important design decisions include:

* database-backed idempotency
* transaction-safe webhook processing
* bounded retries
* rate-limit handling
* external API timeouts
* delivery reconciliation
* database indexes
* database migrations
* environment-based configuration
* automated tests

For higher-scale deployments, the database can be moved from SQLite to PostgreSQL by changing `DATABASE_URL` and applying the appropriate migrations. A dedicated worker/queue system could also replace the manual `/process-jobs` trigger.

## Development Verification

The application has been manually verified through the following flows:

```text
Webhook received
    -> rule matched
    -> DM job created
    -> worker processed job
    -> PseudoGram accepted DM
    -> delivery reconciled
    -> job marked sent
```

Duplicate webhook delivery was also verified and returned:

```json
{
  "status": "duplicate_event"
}
```

## License

This repository was created as a take-home assignment submission.

```
```
