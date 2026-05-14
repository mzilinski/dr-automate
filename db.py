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
    """Datenverzeichnis mit restriktiven Permissions (0700) anlegen.
    Doku verspricht 0700 (docs/security.md). Wir erzwingen das hier explizit,
    auch wenn umask 022 sonst 0755 setzen wuerde.
    """
    import os

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(db_path.parent, 0o700)
        except OSError:
            pass  # nicht alle FS unterstuetzen chmod; gemounted Volumes sind ok


_ensure_data_dir()


def _harden_sqlite_file_perms(dbapi_connection, _connection_record):
    """Setzt 0600 auf der SQLite-Datei, sobald sie existiert."""
    if not DATABASE_URL.startswith("sqlite:///"):
        return
    import os

    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if db_path.exists():
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass

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
    _harden_sqlite_file_perms(dbapi_connection, _connection_record)


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
