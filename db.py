"""
SQLAlchemy-Engine + Session-Factory fuer dr-automate.

Schema-Definition siehe ``models_db.py``. Migrationen via Alembic
(``alembic upgrade head`` beim Container-Start).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DR_AUTOMATE_DATA_DIR", "data"))
DEFAULT_DB_PATH = DATA_DIR / "dr-automate.db"
DATABASE_URL = os.environ.get("DR_AUTOMATE_DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"


class Base(DeclarativeBase):
    pass


def _ensure_data_dir() -> None:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_data_dir()

engine: Engine = create_engine(
    DATABASE_URL,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-Manager mit auto-commit/rollback. Fuer Skripte und Hintergrund-Jobs."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Session:
    """Pro-Request-Session. Vom Caller schliessen (oder Flask teardown nutzen)."""
    return SessionLocal()
