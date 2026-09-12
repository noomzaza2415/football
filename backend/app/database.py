"""SQLAlchemy engine, session factory and the declarative base."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_engine_kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Without a timeout, pointing DATABASE_URL at a PostgreSQL that is not
        # running leaves a script hanging with no output instead of failing.
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables.

    Fine for local development and the demo seed. A real deployment should use
    Alembic migrations instead, see the README.
    """
    from app import models  # noqa: F401  (registers the mappers)

    Base.metadata.create_all(bind=engine)
