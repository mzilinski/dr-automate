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
    """Datenverzeichnis mit restriktiven Permissions (0700) anlegen + bestehende
    Files/Dirs darunter einmalig auf 0700/0600 ziehen.

    Doku verspricht 0700/0600 (docs/security.md). Wir erzwingen das hier explizit,
    auch wenn umask 022 sonst 0755 setzen wuerde — und reparieren alte Datenstaende
    aus Zeiten, wo dieser Code noch nicht existierte.
    """
    import os

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        base = db_path.parent
        base.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        # One-shot Tightening fuer alle bereits liegenden Files unter data/.
        try:
            for root, dirs, files in os.walk(base):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o700)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o600)
                    except OSError:
                        pass
        except OSError:
            pass


_ensure_data_dir()


def _harden_sqlite_file_perms(dbapi_connection=None, _connection_record=None):
    """Setzt 0600 auf der SQLite-Datei, sobald sie existiert.

    Wird auf zwei Wegen aufgerufen:
    - SQLAlchemy connect-event (fuer DBs, die spaeter im Lifecycle entstehen)
    - eager beim Module-Load (fuer schon existierende DBs nach Migration)
    """
    if not DATABASE_URL.startswith("sqlite:///"):
        return
    import os

    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if db_path.exists():
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass


# Eager: chmod gleich beim Import, falls die DB schon nach Migration existiert.
_harden_sqlite_file_perms()

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
