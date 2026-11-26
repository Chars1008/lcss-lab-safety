"""Database engine, session factory, and initialization helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


def create_sqlite_engine(db_path: str | Path) -> Engine:
    """Create a SQLite engine with foreign keys enabled."""
    db_str = str(db_path)
    if db_str != ":memory:":
        Path(db_str).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_str}" if db_str != ":memory:" else "sqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class DatabaseManager:
    """Manages SQLAlchemy engine and session lifecycle."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.engine = create_sqlite_engine(db_path)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def init_db(self) -> None:
        """Create all tables if they do not exist."""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """Return a new SQLAlchemy Session."""
        return self.SessionLocal()


def init_db(db_path: Optional[str | Path] = None) -> DatabaseManager:
    """Convenience helper to initialize database and return manager."""
    manager = DatabaseManager(db_path or ":memory:")
    manager.init_db()
    return manager
