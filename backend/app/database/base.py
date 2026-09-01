"""SQLAlchemy declarative base and shared column conventions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.types import TypeDecorator

# Explicit naming convention so Alembic can autogenerate stable constraint
# names instead of database-generated ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Used instead of ``datetime.utcnow`` (deprecated) and instead of a database
    default, so timestamps are consistent across PostgreSQL and SQLite.
    """
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A DateTime that always round-trips as timezone-aware UTC.

    SQLite discards tzinfo, so values read back would otherwise be naive on
    SQLite and aware on PostgreSQL. This normalises both directions.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Map bare ``dict`` / ``list`` annotations onto JSON columns. SQLAlchemy's
    # JSON type resolves to JSONB-compatible storage on PostgreSQL and to TEXT
    # on SQLite, so audit-trail payloads work identically on both.
    type_annotation_map = {dict: JSON, list: JSON}


def timestamp_column(**kwargs):
    """A UTC timestamp column defaulting to now."""
    return mapped_column(UTCDateTime, default=utcnow, **kwargs)
