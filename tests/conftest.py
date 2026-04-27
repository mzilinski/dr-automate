"""Pytest-Setup: stellt sicher, dass kritische Env-Vars vor dem App-Import gesetzt sind."""

import os

# SECRET_KEY ist seit dem Sicherheits-Hardening Pflicht (außer in DEBUG_MODE).
# Tests laufen ohne DEBUG_MODE → wir setzen einen festen Test-Key, bevor app.py importiert wird.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
