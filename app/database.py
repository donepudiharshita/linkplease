import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv()


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./linkplease.db",
)


engine_kwargs = {
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
    }

engine = create_engine(
    DATABASE_URL,
    **engine_kwargs,
)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


Base = declarative_base()


def get_db():
    """
    Provide one SQLAlchemy session per request.

    The session is always closed after the request,
    including when an exception occurs.
    """

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()