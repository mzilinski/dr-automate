"""Tests fuer Datenbank-Encryption und Schema."""

from __future__ import annotations


def test_encrypted_string_roundtrip():
    from crypto import EncryptedString, decrypt, encrypt

    plain = "DE12 3456 7890 1234 5678 90"
    token = encrypt(plain)
    assert token != plain
    assert decrypt(token) == plain

    td = EncryptedString()
    assert td.process_bind_param(None, None) is None
    encoded = td.process_bind_param(plain, None)
    assert encoded != plain
    assert td.process_result_value(encoded, None) == plain


def test_encrypted_json_roundtrip():
    from crypto import EncryptedJSON

    payload = {"iban": "DE12345", "address": {"street": "Beispielweg 1", "city": "Bremen"}, "amount": 42.5}
    td = EncryptedJSON()
    encoded = td.process_bind_param(payload, None)
    assert encoded != payload
    assert td.process_result_value(encoded, None) == payload


def test_models_db_imports():
    """Wenn das Schema kaputt ist, scheitert der Import."""
    from models_db import AbrechnungStatus, AccountRequest, DienstreiseStatus, User, UserProfile  # noqa: F401

    assert DienstreiseStatus.genehmigt.value == "genehmigt"
    assert AbrechnungStatus.abgeschlossen.value == "abgeschlossen"


def test_deepseek_key_server_storage(auth_client, auth_headers):
    """DeepSeek-Key wird verschluesselt gespeichert, leerer Submit ueberschreibt nicht."""
    import os
    import sqlite3

    headers = {**auth_headers, "Remote-User": "deepseek_test"}
    # Initial setzen
    r = auth_client.post("/profil", data={"deepseek_api_key": "sk-test-1234567890"}, headers=headers)
    assert r.status_code in (200, 302)

    # JSON ohne Secrets: nur has_-Flag
    j = auth_client.get("/profil/json", headers=headers).get_json()
    assert j["has_deepseek_api_key"] is True
    assert "deepseek_api_key" not in j

    # JSON mit include_secrets: Klar-Key
    j = auth_client.get("/profil/json?include_secrets=1", headers=headers).get_json()
    assert j["deepseek_api_key"] == "sk-test-1234567890"

    # On-Disk: verschluesselt
    db_path = os.environ["DR_AUTOMATE_DATABASE_URL"].removeprefix("sqlite:///")
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT deepseek_api_key FROM user_profiles WHERE deepseek_api_key IS NOT NULL"))
    conn.close()
    assert rows and not any("sk-test" in r[0] for r in rows), "Key NICHT verschluesselt in DB!"

    # Leerer Submit ueberschreibt nicht
    auth_client.post("/profil", data={"deepseek_api_key": ""}, headers=headers)
    j = auth_client.get("/profil/json?include_secrets=1", headers=headers).get_json()
    assert j["deepseek_api_key"] == "sk-test-1234567890"

    # Loeschen via Checkbox
    auth_client.post("/profil", data={"clear_deepseek_api_key": "1"}, headers=headers)
    j = auth_client.get("/profil/json", headers=headers).get_json()
    assert j["has_deepseek_api_key"] is False


def test_profile_persistence(auth_client, auth_headers):
    """Profil speichern → IBAN/Adresse sind on-disk verschluesselt, im Read aber Plain."""
    headers = {**auth_headers, "Remote-User": "profiltest"}
    r = auth_client.post(
        "/profil",
        data={
            "vorname": "Test",
            "iban": "DE99 1234 5678 9012 3456 78",
            "adresse_privat": "Geheimstr. 13, 28000 Bremen",
        },
        headers=headers,
    )
    assert r.status_code in (200, 302)
    j = auth_client.get("/profil/json", headers=headers).get_json()
    assert j["iban"].startswith("DE99")
    assert "Geheimstr" in j["adresse_privat"]

    # On-Disk: Wert in der SQLite-DB darf nicht Plain sein
    import os
    import sqlite3

    db_url = os.environ["DR_AUTOMATE_DATABASE_URL"].removeprefix("sqlite:///")
    conn = sqlite3.connect(db_url)
    rows = list(conn.execute("SELECT iban, adresse_privat FROM user_profiles WHERE iban IS NOT NULL"))
    conn.close()
    assert rows, "no encrypted iban-row found"
    for iban_raw, adr_raw in rows:
        assert iban_raw and not iban_raw.startswith("DE"), f"IBAN nicht verschluesselt: {iban_raw!r}"
        assert adr_raw and "Geheimstr" not in adr_raw, "Adresse nicht verschluesselt!"
