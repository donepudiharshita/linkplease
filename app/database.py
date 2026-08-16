from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import sqlalchemy_database_url


DATABASE_URL = sqlalchemy_database_url()


engine_kwargs = {
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
    }
else:
    engine_kwargs.update(
        {
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 30,
        }
    )


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
    """

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()