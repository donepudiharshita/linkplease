import os

from dotenv import load_dotenv


load_dotenv()


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


def validate_settings() -> None:
    if not PSEUDOGRAM_API_KEY:
        raise RuntimeError(
            "PSEUDOGRAM_API_KEY is not configured"
        )