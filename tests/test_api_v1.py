"""REST-API v1: Keys, Authentifizierung, Fehlerformat (plan-api-v1.md)."""

from __future__ import annotations

import json
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


# ---------- Phase 2: Schema, Prompt, zustandslose Endpunkte ----------

PROFIL = {
    "vorname": "Erika",
    "nachname": "Muster",
    "abteilung": "BBS Lingen",
    "telefon": "0591 123456",
    "adresse_privat": "Am Weg 1, 49808 Lingen",
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
    "abrechnende_dienststelle": "NLBV Aurich",
    "anordnende_dienststelle": "RLSB Osnabrück",
}


def antrag_v1():
    with open("example_input.json") as f:
        d = json.load(f)
    return {
        "reise_details": d["reise_details"],
        "befoerderung": {
            "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "III"},
            "rueckreise": {"typ": "PKW", "paragraph_5_nrkvo": "III"},
            "begruendung": "Materialtransport",
        },
        "bemerkungen": "Fähre 08:30",
        "angaben": {"anspruch_trennungsgeld": False},
    }


def abrechnung_v1():
    a = antrag_v1()
    return {
        "reise_details": a["reise_details"],
        "befoerderung": {"hinreise": {"typ": "PKW"}, "rueckreise": {"typ": "PKW"}},
        "uebernachtungen": {"beleg_naechte": 2, "beleg_kosten_eur": 180},
        "wegstrecke": {"km_hinreise": 120, "km_rueckreise": 120},
    }


@pytest.fixture
def mit_profil(auth_client, admin, token):
    auth_client.post("/profil", data=PROFIL, headers=admin)
    return token


def test_schema_endpunkte(auth_client, token):
    s = auth_client.get("/api/v1/schema/antrag", headers=_bearer(token)).get_json()
    assert "reise_details" in s["properties"] and "antragsteller" not in s["properties"]
    s = auth_client.get("/api/v1/schema/abrechnung", headers=_bearer(token)).get_json()
    assert "uebernachtungen" in s["properties"] and "stammdaten" not in s["properties"]


def test_prompt_mit_kontext(auth_client, mit_profil):
    j = auth_client.get("/api/v1/prompt", headers=_bearer(mit_profil)).get_json()
    assert "reise_details" in j["system_prompt"]
    assert "49808 Lingen" in j["kontext"] and "Am Weg" not in j["kontext"]


def test_antrag_pdf(auth_client, mit_profil):
    r = auth_client.post("/api/v1/antrag/pdf", json=antrag_v1(), headers=_bearer(mit_profil))
    assert r.status_code == 200, r.get_json()
    assert r.mimetype == "application/pdf"
    from io import BytesIO

    from pypdf import PdfReader

    fields = PdfReader(BytesIO(r.data)).get_fields()
    assert fields["Person.Name1"]["/V"] == "Erika Muster"  # aus dem Profil


def test_antragsteller_im_body_wird_abgelehnt(auth_client, mit_profil):
    body = {**antrag_v1(), "antragsteller": {"name": "Fremd"}}
    r = auth_client.post("/api/v1/antrag/pdf", json=body, headers=_bearer(mit_profil))
    assert r.status_code == 422
    assert r.get_json()["errors"][0]["loc"] == ["antragsteller"]


def test_validierungsfehler_mit_ort(auth_client, mit_profil):
    body = antrag_v1()
    body["reise_details"]["start_datum"] = "32.13.2026"
    r = auth_client.post("/api/v1/antrag/pdf", json=body, headers=_bearer(mit_profil))
    assert r.status_code == 422
    assert ["reise_details", "start_datum"] in [e["loc"] for e in r.get_json()["errors"]]
    assert "32.13.2026" not in json.dumps(r.get_json()["errors"][0].get("input", ""))


def test_profil_unvollstaendig(auth_client, token):
    r = auth_client.post("/api/v1/antrag/pdf", json=antrag_v1(), headers=_bearer(token))
    assert r.status_code == 422
    assert "Profil unvollständig" in r.get_json()["detail"]


def test_scope_fehlt(auth_client, admin):
    nur_lesen = _key_anlegen(auth_client, admin, scopes=("reisen:read",), name="ro")
    r = auth_client.post("/api/v1/antrag/pdf", json=antrag_v1(), headers=_bearer(nur_lesen))
    assert r.status_code == 403


def test_kein_json(auth_client, mit_profil):
    r = auth_client.post("/api/v1/antrag/pdf", data="x", headers=_bearer(mit_profil))
    assert r.status_code == 415
    r = auth_client.post(
        "/api/v1/antrag/pdf", data="{kaputt", headers={**_bearer(mit_profil), "Content-Type": "application/json"}
    )
    assert r.status_code == 400


def test_abrechnung_berechnung(auth_client, mit_profil):
    r = auth_client.post("/api/v1/abrechnung/berechnung", json=abrechnung_v1(), headers=_bearer(mit_profil))
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["tagegeld_brutto_eur"] == 56.0  # 15.–17.05.: 2 Teiltage + 1 voller Tag
    assert j["wegstreckenentschaedigung_eur"] == 60.0
    assert j["uebernachtung_beleg_pro_nacht_eur"] == 90.0


def test_abrechnung_pdf_braucht_bankdaten(auth_client, admin, token):
    auth_client.post("/profil", data={**PROFIL, "iban": ""}, headers=admin)
    r = auth_client.post("/api/v1/abrechnung/pdf", json=abrechnung_v1(), headers=_bearer(token))
    assert r.status_code == 422 and "IBAN" in r.get_json()["detail"]
    auth_client.post("/profil", data=PROFIL, headers=admin)
    r = auth_client.post("/api/v1/abrechnung/pdf", json=abrechnung_v1(), headers=_bearer(token))
    assert r.status_code == 200 and r.mimetype == "application/pdf"


def test_entfernung(auth_client, token):
    from unittest.mock import patch

    with patch("routing.route_km", return_value={"km": 101.5, "duration_min": 75}):
        r = auth_client.post(
            "/api/v1/entfernung", json={"von": "49808 Lingen", "nach": "30159 Hannover"}, headers=_bearer(token)
        )
    assert r.get_json() == {"km": 101.5, "minuten": 75, "quelle": "OpenStreetMap / OSRM"}


# ---------- Phase 3: Reisen ----------


def test_reise_lebenszyklus(auth_client, mit_profil):
    h = _bearer(mit_profil)
    r = auth_client.post("/api/v1/reisen", json=antrag_v1(), headers=h)
    assert r.status_code == 201, r.get_json()
    reise = r.get_json()
    rid = reise["id"]
    assert r.headers["Location"] == f"/api/v1/reisen/{rid}"
    assert reise["status"] == "entwurf" and reise["pdfs"]["antrag"]

    # Roundtrip: GET-Antrag unverändert zurückschreiben
    antrag = auth_client.get(f"/api/v1/reisen/{rid}", headers=h).get_json()["antrag"]
    antrag["bemerkungen"] = "geändert"
    r = auth_client.put(f"/api/v1/reisen/{rid}/antrag", json=antrag, headers=h)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["antrag"]["bemerkungen"] == "geändert"

    assert [x["id"] for x in auth_client.get("/api/v1/reisen?status=entwurf", headers=h).get_json()["reisen"]].count(
        rid
    ) == 1

    # bezahlt vor Abrechnung → 409
    assert auth_client.post(f"/api/v1/reisen/{rid}/bezahlt", headers=h).status_code == 409

    r = auth_client.post(
        f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026", "aktenzeichen": "AZ-1"}, headers=h
    )
    assert r.get_json()["status"] == "genehmigt" and r.get_json()["genehmigung"]["datum"] == "2026-05-01"

    # Antrag nach Genehmigung → 409 (Entscheidung 3)
    assert auth_client.put(f"/api/v1/reisen/{rid}/antrag", json=antrag, headers=h).status_code == 409

    r = auth_client.put(f"/api/v1/reisen/{rid}/abrechnung", json=abrechnung_v1(), headers=h)
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["status"] == "abgerechnet" and j["berechnung"]["tagegeld_brutto_eur"] == 56.0
    # Anordnung wie im Web-Wizard: Dienststelle aus dem Profil, Datum aus der Genehmigung
    assert j["abrechnung"]["anordnung"] == {"dienststelle": "RLSB Osnabrück", "datum": "01.05.2026"}

    # Roundtrip Abrechnung
    r = auth_client.put(f"/api/v1/reisen/{rid}/abrechnung", json=j["abrechnung"], headers=h)
    assert r.status_code == 200, r.get_json()

    for art in ("antrag", "abrechnung"):
        pdf = auth_client.get(f"/api/v1/reisen/{rid}/{art}.pdf", headers=h)
        assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    r = auth_client.post(f"/api/v1/reisen/{rid}/bezahlt", json={"datum": "2026-06-01"}, headers=h)
    assert r.get_json()["status"] == "bezahlt" and r.get_json()["bezahlt_datum"] == "2026-06-01"

    assert auth_client.delete(f"/api/v1/reisen/{rid}", headers=h).status_code == 204
    assert auth_client.get(f"/api/v1/reisen/{rid}", headers=h).status_code == 404


def test_fremde_reise_404(auth_client, mit_profil):
    rid = auth_client.post("/api/v1/reisen", json=antrag_v1(), headers=_bearer(mit_profil)).get_json()["id"]
    fremd = {"Remote-User": f"fremd_{uuid.uuid4().hex[:6]}", "Remote-Groups": "admins"}
    auth_client.post("/profil", data=PROFIL, headers=fremd)
    t = _bearer(_key_anlegen(auth_client, fremd))
    assert auth_client.get(f"/api/v1/reisen/{rid}", headers=t).status_code == 404
    assert auth_client.get(f"/api/v1/reisen/{rid}/antrag.pdf", headers=t).status_code == 404
    assert auth_client.put(f"/api/v1/reisen/{rid}/antrag", json=antrag_v1(), headers=t).status_code == 404
    assert (
        auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026"}, headers=t).status_code
        == 404
    )
    assert auth_client.delete(f"/api/v1/reisen/{rid}", headers=t).status_code == 404
    assert rid not in [x["id"] for x in auth_client.get("/api/v1/reisen", headers=t).get_json()["reisen"]]


def test_nur_lesen_darf_nicht_schreiben(auth_client, admin, mit_profil):
    ro = _bearer(_key_anlegen(auth_client, admin, scopes=("reisen:read",), name="ro"))
    assert auth_client.get("/api/v1/reisen", headers=ro).status_code == 200
    assert auth_client.post("/api/v1/reisen", json=antrag_v1(), headers=ro).status_code == 403


def test_ungueltiger_status_filter_und_datum(auth_client, mit_profil):
    h = _bearer(mit_profil)
    assert auth_client.get("/api/v1/reisen?status=quatsch", headers=h).status_code == 422
    rid = auth_client.post("/api/v1/reisen", json=antrag_v1(), headers=h).get_json()["id"]
    r = auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "gestern"}, headers=h)
    assert r.status_code == 422


def test_api_reise_erscheint_im_dashboard(auth_client, admin, mit_profil):
    auth_client.post("/api/v1/reisen", json=antrag_v1(), headers=_bearer(mit_profil))
    assert b"Digitale Transformation" in auth_client.get("/dashboard", headers=admin).data


# ---------- Phase 4: extract, OpenAPI ----------


def test_openapi_ohne_key_und_vollstaendig(app_module, auth_client):
    import api_openapi

    r = auth_client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    spec = r.get_json()
    assert spec["openapi"] == "3.1.0" and "AntragV1" in spec["components"]["schemas"]
    # Doku-Tabelle == registrierte Routen
    registriert = set()
    for rule in app_module.app.url_map.iter_rules():
        if rule.rule.startswith("/api/v1/"):
            pfad = rule.rule.removeprefix("/api/v1").replace("<int:reise_id>", "{reise_id}")
            for m in rule.methods - {"HEAD", "OPTIONS"}:
                registriert.add((m.lower(), pfad))
    dokumentiert = {(m, p) for m, p, *_ in api_openapi.ROUTEN}
    assert registriert == dokumentiert


def test_extract_mit_profil_key(auth_client, admin, mit_profil):
    from unittest.mock import patch

    t = _key_anlegen(auth_client, admin, scopes=("extract",), name="ex")
    auth_client.post("/profil", data={**PROFIL, "deepseek_api_key": "sk-eigener"}, headers=admin)
    captured = {}

    def fake(freitext, api_key, system_prompt, sonderwuensche=""):
        captured.update(freitext=freitext, api_key=api_key)
        return {
            "reise_details": {"zielort": "Hannover [cite: 1]", "start_datum": "12.03.2027"},
            "zusatz_infos": {"bemerkungen_feld": "ICE 10:12"},
            "konfiguration_checkboxen": {"kosten_durch_andere_stelle": False},
        }

    with patch("ai_extract.call_deepseek", side_effect=fake):
        r = auth_client.post(
            "/api/v1/extract",
            json={"freitext": "Tagung in Hannover", "hinreise": {"typ": "BAHN"}},
            headers={**_bearer(t), "X-DeepSeek-Key": "sk-fremd"},
        )
    assert r.status_code == 200, r.get_json()
    e = r.get_json()["antrag_entwurf"]
    assert e["reise_details"]["zielort"] == "Hannover" and e["bemerkungen"] == "ICE 10:12"
    assert captured["api_key"] == "sk-eigener"
    assert "49808 Lingen" in captured["freitext"] and "Hinreise: Bahn" in captured["freitext"]


def test_extract_ohne_scope_und_ohne_key(auth_client, admin, mit_profil):
    assert auth_client.post("/api/v1/extract", json={"freitext": "x"}, headers=_bearer(mit_profil)).status_code == 403
    t = _key_anlegen(auth_client, admin, scopes=("extract",), name="ex2")
    r = auth_client.post("/api/v1/extract", json={"freitext": "x"}, headers=_bearer(t))
    assert r.status_code == 422 and "DeepSeek-Key" in r.get_json()["title"]


def test_cli_widerrufen(auth_client, admin, token, monkeypatch, capsys):
    import api_keys

    monkeypatch.setattr("sys.argv", ["api_keys.py", "widerrufen", admin["Remote-User"]])
    assert api_keys._cli() == 0
    assert "1 Key(s)" in capsys.readouterr().out
    assert auth_client.get("/api/v1/me", headers=_bearer(token)).status_code == 401
