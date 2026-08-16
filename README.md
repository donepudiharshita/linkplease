````markdown
# LinkPlease

A webhook-driven DM automation service built with FastAPI, SQLAlchemy, PostgreSQL/SQLite, and the PseudoGram API.

The service receives `comment.created` webhook events, matches configured keyword rules, creates database-backed DM jobs, sends DMs through PseudoGram, retries temporary failures, and reconciles accepted DMs until delivery is confirmed.

## Architecture

```text
                    PseudoGram Webhook
                           |
                           v
                    FastAPI /webhook
                           |
              +------------+------------+
              |                         |
              v                         v
       Idempotency check          Rule matching
              |                         |
              +------------+------------+
                           |
                           v
                    PostgreSQL / SQLite
                           |
                           v
                         DmJob
                           |
                           v
                 Embedded background worker
                           |
                           v
                    PseudoGram API
                           |
                +----------+----------+
                |                     |
              retry                accepted
                |                     |
                |                     v
                |               Delivery check
                |                     |
                |              +------+------+
                |              |             |
                |           queued       delivered
                |                            |
                |                            v
                |                           sent
                |
                +----> retry / failed
````

For local development, SQLite can be used.

For deployment, PostgreSQL is recommended and configured through `DATABASE_URL`.

## Features

* FastAPI REST API
* `comment.created` webhook processing
* Keyword-based automation rules
* Database-backed DM job queue
* Webhook idempotency using unique event IDs
* Duplicate-job protection
* PseudoGram API integration
* Deterministic external idempotency keys
* Exponential retry backoff
* HTTP `429 Retry-After` handling
* HTTP 5xx retry handling
* Network failure retry handling
* Maximum retry attempts
* Accepted vs delivered state separation
* Delivery-status reconciliation
* Batch worker processing
* Embedded background worker for deployment
* Health/readiness endpoint
* PostgreSQL support
* SQLite support for local development
* Alembic migrations
* Environment-based configuration
* Automated API tests
* Automated worker/retry tests

## Project Structure

```text
linkplease/
├── app/
│   ├── __init__.py
│   ├── background_worker.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── mock_api.py
│   ├── models.py
│   ├── schemas.py
│   └── worker.py
├── alembic/
│   ├── versions/
│   │   └── 6b719c7bf977_strengthen_database_constraints_and_.py
│   ├── env.py
│   ├── README
│   └── script.py.mako
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   └── test_worker.py
├── .env
├── .env.example
├── .gitignore
├── alembic.ini
├── FAILURES.md
├── README.md
├── render.yaml
└── requirements.txt
```

## Requirements

* Python 3.14+
* A PseudoGram API key
* PostgreSQL for deployed environments
* SQLite for local development/testing

## Local Setup

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

RUN_BACKGROUND_WORKER=false
WORKER_POLL_INTERVAL_SECONDS=2
```

Never commit `.env`.

Use `.env.example` as the safe configuration template.

## Database

### Local development

SQLite is used by default:

```text
sqlite:///./linkplease.db
```

### Deployment

Set:

```text
DATABASE_URL=<PostgreSQL connection string>
```

The application normalizes standard `postgres://` and `postgresql://` URLs to the SQLAlchemy Psycopg driver format.

## Database Migrations

Alembic manages the application schema.

Check the current revision:

```powershell
alembic current
```

Check whether model metadata and the migration state match:

```powershell
alembic check
```

Apply migrations:

```powershell
alembic upgrade head
```

Create a new migration during development:

```powershell
alembic revision --autogenerate -m "describe schema change"
```

The deployed application runs migrations before starting the FastAPI server.

## Running Locally

Start the API:

```powershell
uvicorn app.main:app --reload
```

The API is available at:

```text
http://127.0.0.1:8000
```

Interactive Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

## Running the Background Worker Locally

The embedded background worker is disabled during normal local development by default.

To enable it:

```text
RUN_BACKGROUND_WORKER=true
```

The worker polls the database for pending work and processes jobs automatically.

The manual endpoint remains available for development/testing:

```text
POST /process-jobs
```

## API Endpoints

### `GET /`

Returns basic application information.

Example:

```json
{
  "message": "LinkPlease API is running",
  "version": "1.0.0"
}
```

### `GET /health`

Checks that the application can reach its database.

Example:

```json
{
  "status": "healthy"
}
```

If the database is unavailable, the endpoint returns `503 Service Unavailable`.

### `POST /rules`

Creates a keyword-triggered DM rule.

Example:

```json
{
  "keyword": "link",
  "dm_message": "Here is the link you requested!"
}
```

### `POST /webhook`

Receives a PseudoGram webhook event.

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

1. Validates the payload.
2. Checks whether `event_id` has already been processed.
3. Records the event.
4. Matches configured keyword rules.
5. Prevents duplicate jobs for the same rule and user.
6. Stores matching DM jobs in the database.
7. Returns without waiting for the external DM delivery.

### `POST /process-jobs`

Manually triggers one worker cycle.

Example response:

```json
{
  "status": "processed"
}
```

This endpoint is retained for development and verification. In deployment, the embedded worker normally processes jobs automatically.

### `GET /stats`

Returns the current processing counters.

Example:

```json
{
  "sent": 6,
  "failed": 0,
  "queued": 0,
  "duplicates_blocked": 2
}
```

`queued` includes jobs currently in:

```text
queued
processing
retry
accepted
```

## Job Lifecycle

A DM job follows this lifecycle:

```text
queued
   |
   v
processing
   |
   +-----> retry --------+
   |                     |
   |                     v
   |                processing
   |
   +-----> accepted
               |
               v
       delivery reconciliation
               |
          +----+----+
          |         |
        queued   delivered
                     |
                     v
                    sent
```

Permanent errors move the job to:

```text
failed
```

## Retry Strategy

Temporary failures use bounded exponential backoff.

Typical retry delays:

```text
attempt 1 -> 2 seconds
attempt 2 -> 4 seconds
attempt 3 -> 8 seconds
attempt 4 -> 16 seconds
attempt 5 -> 32 seconds
```

The worker caps retry delay.

### HTTP 429

The `Retry-After` response header is used when available.

### HTTP 5xx

Server failures are retried using exponential backoff until the maximum attempt count is reached.

### Network errors

Network-level failures are considered retryable.

### Permanent 4xx errors

Client errors other than `429` are treated as permanent failures.

## Idempotency

The application uses multiple layers of duplicate protection.

### Webhook idempotency

`ProcessedEvent.event_id` is unique.

Sending the same event again returns:

```json
{
  "status": "duplicate_event"
}
```

### Duplicate DM job protection

A unique `(rule_id, user_id)` constraint prevents multiple jobs for the same user/rule combination.

### External DM idempotency

Each job uses:

```text
dm-job-{job_id}
```

as its PseudoGram idempotency key.

This protects the external send operation when an application retry occurs after a request may already have reached PseudoGram.

## Delivery Reconciliation

A successful PseudoGram send means the external service accepted the DM request.

It does not necessarily mean the DM was delivered.

Therefore:

```text
accepted != sent
```

The worker periodically checks the delivery endpoint.

Only when PseudoGram reports:

```text
delivered
```

does the local job become:

```text
sent
```

This prevents the application from treating API acceptance as confirmed delivery.

## Database Design

### `rules`

Stores keyword-triggered DM rules.

### `processed_events`

Stores webhook event IDs used for idempotency.

### `dm_jobs`

Stores asynchronous DM work, including:

* rule ID
* comment ID
* user ID
* message
* status
* attempt count
* retry time
* external DM ID
* last error
* creation time

### `stats`

Stores duplicate-protection statistics.

Indexes are included for common worker, reconciliation, user, comment, and status lookups.

## Testing

The project contains automated API and worker tests.

Run:

```powershell
pytest -q
```

The current suite contains **28 passing tests** covering:

* health/readiness behavior
* home endpoint
* rule creation
* rule validation
* webhook validation
* keyword matching
* case-insensitive matching
* multiple matching rules
* non-matching comments
* duplicate webhook events
* duplicate user/rule jobs
* unsupported event types
* statistics
* successful DM acceptance
* HTTP 500 retry
* HTTP 429 `Retry-After`
* network failures
* maximum retry attempts
* permanent 4xx failures
* delivery reconciliation
* accepted/queued delivery status
* delivery failures
* delivery network errors
* malformed API responses
* missing `dm_id`
* unknown delivery states

The current local verification result is:

```text
28 passed
```

## Deployment

The repository includes `render.yaml` for Render deployment.

The intended deployment architecture is:

```text
Render Web Service
        |
        +---- FastAPI application
        |
        +---- Embedded background worker
        |
        v
Render PostgreSQL
        |
        v
PseudoGram API
```

The deployment uses:

```text
DATABASE_URL
PSEUDOGRAM_API_KEY
PSEUDOGRAM_BASE_URL
PSEUDOGRAM_TIMEOUT_SECONDS
RUN_BACKGROUND_WORKER
WORKER_POLL_INTERVAL_SECONDS
```

The real PseudoGram API key is supplied through Render environment variables and is never committed to Git.

The deployed service runs:

```text
alembic upgrade head
```

before starting Uvicorn.

The application binds to:

```text
0.0.0.0:$PORT
```

for the hosting environment.

## Render Environment

For the deployed service:

```text
PSEUDOGRAM_API_KEY=<secret>
PSEUDOGRAM_BASE_URL=https://pseudogram-api.onrender.com
PSEUDOGRAM_TIMEOUT_SECONDS=10

DATABASE_URL=<Render PostgreSQL connection string>

RUN_BACKGROUND_WORKER=true
WORKER_POLL_INTERVAL_SECONDS=2
```

The health check endpoint is:

```text
/health
```

## Failure Transparency

The repository includes:

```text
FAILURES.md
```

This documents known failure modes instead of claiming that the system handles every possible edge case.

Known limitations include worker concurrency, multiple web replicas, external acceptance followed by local database failure, transient statistics during active processing, prolonged delivery reconciliation failures, and the limitations of SQLite for production concurrency.

## Security

Secrets are loaded through environment variables.

The repository intentionally does not contain:

* the real PseudoGram API key
* local SQLite databases
* database backups
* virtual environments

`.env.example` contains placeholders only.

## Development Verification

The implementation has been manually verified through the complete flow:

```text
Webhook received
    ↓
Rule matched
    ↓
DM job created
    ↓
Worker processes job
    ↓
PseudoGram accepts DM
    ↓
Delivery reconciliation
    ↓
Job marked sent
```

Duplicate webhook delivery was also verified and correctly returned:

```json
{
  "status": "duplicate_event"
}
```

A previously completed verification produced:

```json
{
  "sent": 6,
  "failed": 0,
  "queued": 0,
  "duplicates_blocked": 2
}
```

## Current Validation

The project is considered locally verified when all of the following are true:

```text
pytest -q
28 passed

alembic current
6b719c7bf977 (head)

alembic check
No new upgrade operations detected.

git status
working tree clean
```

```
```
