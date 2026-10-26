"""REST-API v1: Keys, Authentifizierung, Fehlerformat (plan-api-v1.md)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def admin():
    """Eigener Admin je Test (die Test-DB ist geteilt, max. 5 Keys pro User)."""
    return {"Remote-User": f"admin_{uuid.uuid4().hex[:8]}", "Remote-Groups": "admins", "Remote-Name": "Api Admin"}


def _key_anlegen(client, headers, scopes=("reisen:read", "reisen:write", "berechnen"), name="Test"):
    r = client.post(
        "/profil/api-keys", data={"name": name, "laufzeit_tage": "365", "scopes": list(scopes)}, headers=headers
    )
    assert r.status_code == 200, r.status_code
    m = re.search(r"dra_[0-9a-f]{12}_[A-Za-z0-9_-]+", r.get_data(as_text=True))
    assert m, "Token wird nach dem Anlegen angezeigt"
    assert r.headers.get("Cache-Control") == "no-store"
    return m.group(0)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def token(auth_client, admin):
    return _key_anlegen(auth_client, admin)


def test_me_mit_key(auth_client, admin, token):
    r = auth_client.get("/api/v1/me", headers=_bearer(token))
    assert r.status_code == 200
    j = r.get_json()
    assert j["user"]["name"] == admin["Remote-User"]
    assert j["key"]["scopes"] == ["reisen:read", "reisen:write", "berechnen"]
    assert j["api_berechtigt_bis"]


@pytest.mark.parametrize(
    "auth", ["", "Bearer ", "Bearer dra_000000000000_falsch-falsch-falsch-falsch", "Basic abc", "Bearer x"]
)
def test_ohne_gueltigen_key_401_problem_json(auth_client, auth):
    r = auth_client.get("/api/v1/me", headers={"Authorization": auth} if auth else {})
    assert r.status_code == 401
    assert r.mimetype == "application/problem+json"
    assert r.get_json()["status"] == 401


def test_falsches_secret_mit_echtem_praefix(auth_client, token):
    kaputt = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    assert auth_client.get("/api/v1/me", headers=_bearer(kaputt)).status_code == 401


def test_remote_user_header_wird_ignoriert(auth_client):
    from db import SessionLocal
    from models_db import User

    r = auth_client.get("/api/v1/me", headers={"Remote-User": "nur_header", "Remote-Groups": "admins"})
    assert r.status_code == 401
    with SessionLocal() as s:
        assert s.query(User).filter(User.remote_user == "nur_header").first() is None


def test_nicht_admin_darf_keine_keys(auth_client):
    h = {"Remote-User": "kein_admin", "Remote-Groups": "dr-automate-users"}
    assert b'id="api"' not in auth_client.get("/profil", headers=h).data
    r = auth_client.post(
        "/profil/api-keys", data={"name": "x", "laufzeit_tage": "30", "scopes": ["berechnen"]}, headers=h
    )
    assert r.status_code == 403


def test_widerrufen(auth_client, admin, token):
    import api_keys
    from db import SessionLocal
    from models_db import ApiKey

    with SessionLocal() as s:
        key = s.query(ApiKey).filter(ApiKey.prefix == api_keys.prefix_of(token)).one()
    r = auth_client.post(f"/profil/api-keys/{key.id}/widerrufen", headers=admin)
    assert r.status_code == 302
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401


def test_fremden_key_nicht_widerrufbar(auth_client, token):
    import api_keys
    from db import SessionLocal
    from models_db import ApiKey

    with SessionLocal() as s:
        key = s.query(ApiKey).filter(ApiKey.prefix == api_keys.prefix_of(token)).one()
    andere = {"Remote-User": "anderer_admin", "Remote-Groups": "admins"}
    auth_client.post(f"/profil/api-keys/{key.id}/widerrufen", headers=andere)
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 200


def test_abgelaufener_key(auth_client, token):
    import api_keys
    from db import SessionLocal
    from models_db import ApiKey

    with SessionLocal() as s:
        key = s.query(ApiKey).filter(ApiKey.prefix == api_keys.prefix_of(token)).one()
        key.expires_at = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401


def test_berechtigung_verfaellt_ohne_web_login(auth_client, admin, token):
    """Aus `admins` gefallen oder in Authelia deaktiviert → Keys laufen mit api_berechtigt_bis aus."""
    from db import SessionLocal
    from models_db import User

    with SessionLocal() as s:
        u = s.query(User).filter(User.remote_user == admin["Remote-User"]).one()
        u.api_berechtigt_bis = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401
    # Web-Login als Nicht-Admin verlängert nicht
    auth_client.get("/dashboard", headers={**admin, "Remote-Groups": "dr-automate-users"})
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401
    # Web-Login als Admin verlängert wieder
    auth_client.get("/dashboard", headers=admin)
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 200


def test_max_aktive_keys(auth_client):
    h = {"Remote-User": "viele_keys", "Remote-Groups": "admins"}
    for i in range(5):
        _key_anlegen(auth_client, headers=h, name=f"k{i}")
    r = auth_client.post(
        "/profil/api-keys", data={"name": "k6", "laufzeit_tage": "30", "scopes": ["berechnen"]}, headers=h
    )
    assert r.status_code == 302  # Fehler per Flash zurück aufs Profil


def test_ungueltige_eingaben_beim_anlegen(auth_client, admin):
    for data in (
        {"name": "", "laufzeit_tage": "30", "scopes": ["berechnen"]},
        {"name": "x", "laufzeit_tage": "999", "scopes": ["berechnen"]},
        {"name": "x", "laufzeit_tage": "30", "scopes": ["admin:alles"]},
    ):
        assert auth_client.post("/profil/api-keys", data=data, headers=admin).status_code == 302


def test_nur_hash_gespeichert(auth_client, token):
    import os
    import sqlite3

    db = os.environ["DR_AUTOMATE_DATABASE_URL"].removeprefix("sqlite:///")
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT prefix, secret_hash FROM api_keys").fetchall()
    conn.close()
    assert all(token not in (p + h) for p, h in rows)
    assert any(token.split("_")[1] == p for p, _ in rows)


def test_token_nicht_im_log(auth_client, admin, caplog):
    caplog.set_level("DEBUG")
    token = _key_anlegen(auth_client, admin, name="log")
    auth_client.get("/api/v1/me", headers=_bearer(token))
    assert token.split("_", 2)[2] not in caplog.text


def test_unbekannter_pfad_problem_json(auth_client):
    r = auth_client.get("/api/v1/gibtsnicht")
    assert r.status_code == 404
    assert r.mimetype == "application/problem+json"


def test_webseiten_behalten_html_fehler(auth_client):
    r = auth_client.get("/gibtsnicht")
    assert r.status_code == 404
    assert r.mimetype == "text/html"


def test_csrf_gilt_nicht_fuer_api(app_module, auth_client, token):
    app_module.app.config["WTF_CSRF_ENABLED"] = True
    try:
        # POST ohne CSRF-Token auf einen API-Pfad: 405 (nur GET) statt CSRF-400
        r = auth_client.post("/api/v1/me", headers=_bearer(token))
        assert r.status_code == 405
        assert r.mimetype == "application/problem+json"
    finally:
        app_module.app.config["WTF_CSRF_ENABLED"] = False


def test_rate_limit_fehlversuche(app_module, auth_client):
    app_module.limiter.enabled = True
    app_module.limiter.reset()
    try:
        codes = [
            auth_client.get("/api/v1/me", headers=_bearer("dra_000000000000_" + "x" * 30)).status_code
            for _ in range(12)
        ]
        assert codes[:10] == [401] * 10
        assert codes[-1] == 429
    finally:
        app_module.limiter.reset()
        app_module.limiter.enabled = False
