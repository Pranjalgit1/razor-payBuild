"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _create_engine() -> Engine:
    connect_args: dict = {}
    if settings.database_url.startswith("sqlite"):
        # FastAPI serves requests from a thread pool; SQLite needs this to
        # allow a connection to be used outside the thread that created it.
        connect_args["check_same_thread"] = False

    engine = create_engine(
        settings.database_url,
        echo=settings.sql_echo,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):
            # SQLite ignores foreign keys unless explicitly told not to, which
            # would let the schema drift from PostgreSQL's behaviour.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
