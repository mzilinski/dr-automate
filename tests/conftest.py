"""Pytest-Setup fuer dr-automate.

Stellt sicher, dass:
  - SECRET_KEY/Encryption-Key gesetzt sind, bevor app.py importiert wird
  - Tests eine frische SQLite-DB nutzen (kein Production-State)
  - Fixtures fuer Gast- und Auth-Modus existieren (``guest_client``, ``auth_client``)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# SECRET_KEY ist seit dem Sicherheits-Hardening Pflicht (ausser in DEBUG_MODE).
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
# Verschluesselungs-Key fuer Tests — fest, damit Daten zwischen Test-Faellen lesbar bleiben.
os.environ.setdefault("DR_AUTOMATE_ENCRYPTION_KEY", "9pX9p1d2Hh9JhKuh3w3FH3UEcXmkz_2g6n_zP38eYBs=")

# Tests immer mit eigener SQLite-Datei in einem tempdir, nicht im Repo.
_TMPDIR = tempfile.mkdtemp(prefix="dr-automate-test-")
os.environ.setdefault("DR_AUTOMATE_DATABASE_URL", f"sqlite:///{_TMPDIR}/test.db")
os.environ.setdefault("DR_AUTOMATE_DATA_DIR", _TMPDIR)

# Projektverzeichnis fuer den Import-Pfad.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _create_schema():
    """Alembic-Migrationen idempotent gegen die Test-DB laufen lassen."""
    from alembic.config import Config

    from alembic import command

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", os.environ["DR_AUTOMATE_DATABASE_URL"])
    command.upgrade(cfg, "head")


_create_schema()


@pytest.fixture
def app_module():
    """Importiert die Flask-App on-demand (nach env-Setup)."""
    import app as app_module

    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    return app_module


@pytest.fixture
def client(app_module):
    """Default-Test-Client (Gast-Modus, kein TRUST_REMOTE_USER_HEADER).

    Wird vom Legacy-Test-Code erwartet — pre-existing tests sind so geschrieben.
    """
    app_module.app.config["TRUST_REMOTE_USER_HEADER"] = False
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def guest_client(app_module):
    """Expliziter Gast-Modus-Client (kein Auth-Header beachtet)."""
    app_module.app.config["TRUST_REMOTE_USER_HEADER"] = False
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def auth_client(app_module):
    """Authentifizierter Client: ``Remote-User``-Header wird respektiert.

    Tests muessen den Header bei jedem Request mitschicken:
        auth_client.get('/dashboard', headers={'Remote-User': 'testuser'})
    """
    app_module.app.config["TRUST_REMOTE_USER_HEADER"] = True
    with app_module.app.test_client() as c:
        yield c
    app_module.app.config["TRUST_REMOTE_USER_HEADER"] = False


@pytest.fixture
def auth_headers():
    """Default-Header fuer Auth-Requests."""
    return {"Remote-User": "testuser", "Remote-Email": "test@example.org", "Remote-Name": "Test User"}
