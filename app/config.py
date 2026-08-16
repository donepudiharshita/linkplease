import os

from dotenv import load_dotenv


load_dotenv()


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./linkplease.db",
)

PSEUDOGRAM_API_KEY = os.getenv(
    "PSEUDOGRAM_API_KEY",
)

PSEUDOGRAM_BASE_URL = os.getenv(
    "PSEUDOGRAM_BASE_URL",
    "https://pseudogram-api.onrender.com",
).rstrip("/")

PSEUDOGRAM_TIMEOUT_SECONDS = float(
    os.getenv(
        "PSEUDOGRAM_TIMEOUT_SECONDS",
        "10",
    )
)

RUN_BACKGROUND_WORKER = (
    os.getenv(
        "RUN_BACKGROUND_WORKER",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

WORKER_POLL_INTERVAL_SECONDS = float(
    os.getenv(
        "WORKER_POLL_INTERVAL_SECONDS",
        "2",
    )
)


def sqlalchemy_database_url() -> str:
    """
    Normalize Render/Postgres URLs for SQLAlchemy + Psycopg 3.
    """

    url = DATABASE_URL

    if url.startswith("postgres://"):
        return url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return url


def validate_settings() -> None:
    if not PSEUDOGRAM_API_KEY:
        raise RuntimeError(
            "PSEUDOGRAM_API_KEY is not configured"
        )