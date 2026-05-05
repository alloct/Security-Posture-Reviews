"""Database session and engine configuration.

A single SQLite database file is used. The location can be overridden via the
DATABASE_URL environment variable, which is helpful for Docker deployments where
the database lives on a mounted volume at /app/data/app.db.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Resolve a sensible default database location. When running outside Docker we
# place the SQLite file in <project-root>/data/app.db.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT_DB_PATH = _DEFAULT_DATA_DIR / "app.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}")

# SQLite needs check_same_thread disabled when used with FastAPI's threadpool.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    future=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base used by all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Used as a fallback if Alembic has not been run."""
    # Importing here ensures models are registered against Base.metadata.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
