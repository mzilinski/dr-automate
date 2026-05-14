"""Dashboard- und Dienstreise-CRUD-Tests inkl. IDOR-Schutz."""

from __future__ import annotations

import json


def _example_input():
    import json as _j
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "example_input.json")) as f:
        return _j.load(f)


def test_save_flag_persists_reise(auth_client, auth_headers):
    headers = {**auth_headers, "Remote-User": "save_test"}
    payload = _example_input()
    r = auth_client.post(
        "/generate",
        data={"json_data": json.dumps(payload), "save_to_account": "1"},
        headers=headers,
    )
    assert r.status_code == 200
    assert "X-Dienstreise-Id" in r.headers
    reise_id = int(r.headers["X-Dienstreise-Id"])
    assert reise_id > 0

    # Dashboard zeigt die Reise jetzt
    dash = auth_client.get("/dashboard", headers=headers)
    assert dash.status_code == 200
    assert b"badge" in dash.data


def test_generate_without_save_flag_does_not_persist(auth_client, auth_headers):
    headers = {**auth_headers, "Remote-User": "nosave"}
    payload = _example_input()
    r = auth_client.post(
        "/generate", data={"json_data": json.dumps(payload)}, headers=headers
    )
    assert r.status_code == 200
    # Kein X-Dienstreise-Id, wenn save_to_account nicht gesetzt war
    assert "X-Dienstreise-Id" not in r.headers


def test_idor_protection_on_dienstreise(auth_client, auth_headers):
    """Alice legt Reise an, Bob darf sie NICHT lesen."""
    alice = {"Remote-User": "alice", "Remote-Name": "Alice"}
    bob = {"Remote-User": "bob", "Remote-Name": "Bob"}
    payload = _example_input()

    r = auth_client.post(
        "/generate", data={"json_data": json.dumps(payload), "save_to_account": "1"}, headers=alice
    )
    assert r.status_code == 200
    reise_id = r.headers["X-Dienstreise-Id"]

    # Alice darf
    r_alice = auth_client.get(f"/dienstreisen/{reise_id}/antrag-json", headers=alice)
    assert r_alice.status_code == 200

    # Bob bekommt 404 (nicht 403, damit ID-Enumeration nicht moeglich)
    r_bob = auth_client.get(f"/dienstreisen/{reise_id}/antrag-json", headers=bob)
    assert r_bob.status_code == 404

    # Auch PDF-Download blockiert
    r_bob_pdf = auth_client.get(f"/dienstreisen/{reise_id}/antrag.pdf", headers=bob)
    assert r_bob_pdf.status_code == 404


def test_genehmigung_workflow(auth_client, auth_headers):
    headers = {**auth_headers, "Remote-User": "gene_test"}
    payload = _example_input()
    r = auth_client.post(
        "/generate", data={"json_data": json.dumps(payload), "save_to_account": "1"}, headers=headers
    )
    reise_id = int(r.headers["X-Dienstreise-Id"])

    # Form anzeigen
    r = auth_client.get(f"/dienstreisen/{reise_id}/genehmigung", headers=headers)
    assert r.status_code == 200

    # Speichern
    r = auth_client.post(
        f"/dienstreisen/{reise_id}/genehmigung",
        data={"genehmigung_datum": "2026-05-10", "genehmigung_aktenzeichen": "AZ-42", "next": "dashboard"},
        headers=headers,
    )
    assert r.status_code in (200, 302)

    # Status ist jetzt 'genehmigt'
    j = auth_client.get(f"/dienstreisen/{reise_id}/antrag-json", headers=headers).get_json()
    assert j["status"] == "genehmigt"
    assert j["genehmigung_datum"] == "2026-05-10"
    assert j["genehmigung_aktenzeichen"] == "AZ-42"


def test_dienstreise_delete_cleans_pdfs(auth_client, auth_headers):
    import os

    headers = {**auth_headers, "Remote-User": "deltest"}
    payload = _example_input()
    r = auth_client.post(
        "/generate", data={"json_data": json.dumps(payload), "save_to_account": "1"}, headers=headers
    )
    reise_id = int(r.headers["X-Dienstreise-Id"])

    # PDF jetzt da
    r_pdf = auth_client.get(f"/dienstreisen/{reise_id}/antrag.pdf", headers=headers)
    assert r_pdf.status_code == 200
    pdf_dir = os.path.join(os.environ["DR_AUTOMATE_DATA_DIR"], "pdfs")
    assert os.path.isdir(pdf_dir)

    # Loeschen
    r = auth_client.post(f"/dienstreisen/{reise_id}/delete", headers=headers)
    assert r.status_code in (200, 302)

    # PDF weg
    r = auth_client.get(f"/dienstreisen/{reise_id}/antrag.pdf", headers=headers)
    assert r.status_code == 404


def test_docs_path_traversal_blocked(guest_client):
    """Sicherheit: docs_view darf keine Pfad-Tricks zulassen."""
    for evil in ("../etc/passwd", "..%2Fetc%2Fpasswd", "/etc/passwd"):
        r = guest_client.get(f"/docs/{evil}")
        assert r.status_code == 404, f"Path traversal not blocked for {evil!r}"


def test_account_request_honeypot_blocks_bots(guest_client):
    """Honeypot-Feld 'website' fuellt nur ein Bot."""
    r = guest_client.post(
        "/account/request",
        data={
            "email": "spam@example.org",
            "display_name": "Spammer",
            "website": "http://spam.example.org/",  # honeypot
        },
    )
    # Bot wird leise abgewiesen / umgeleitet, kein Account-Request angelegt
    assert r.status_code in (200, 302)
    # Verifizieren: keine echte Anlage
    import os
    import sqlite3

    db_path = os.environ["DR_AUTOMATE_DATABASE_URL"].removeprefix("sqlite:///")
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT email FROM account_requests WHERE email = 'spam@example.org'"))
    conn.close()
    assert rows == [], "Bot-Eintrag wurde gespeichert!"
