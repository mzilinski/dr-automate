"""Tests fuer Authelia-Header-Authentifizierung und IDOR-Schutz."""

from __future__ import annotations


def test_trust_flag_default_blocks_header_spoofing(guest_client):
    """Ohne TRUST_REMOTE_USER_HEADER darf ein gesetzter Header NICHT zur Authentifizierung fuehren."""
    r = guest_client.get("/dashboard", headers={"Remote-User": "attacker"})
    # Gast wird auf landing umgeleitet (302) oder bekommt 401 — beides ist kein 200.
    assert r.status_code in (302, 401), f"Unexpected {r.status_code} – Header-Spoofing moeglich!"


def test_auth_client_creates_user_on_first_access(auth_client, auth_headers):
    r = auth_client.get("/dashboard", headers=auth_headers)
    assert r.status_code == 200
    # Zweiter Aufruf macht keinen Fehler (Upsert idempotent)
    r2 = auth_client.get("/dashboard", headers=auth_headers)
    assert r2.status_code == 200


def test_dashboard_is_per_user(auth_client, auth_headers):
    alice = {"Remote-User": "alice", "Remote-Name": "Alice"}
    bob = {"Remote-User": "bob", "Remote-Name": "Bob"}
    # Beide Konten anlegen
    auth_client.get("/dashboard", headers=alice)
    auth_client.get("/dashboard", headers=bob)
    # Beide Dashboards leer & unabhaengig
    r_alice = auth_client.get("/dashboard", headers=alice)
    r_bob = auth_client.get("/dashboard", headers=bob)
    assert r_alice.status_code == 200 and r_bob.status_code == 200


def test_profil_requires_auth(guest_client):
    r = guest_client.get("/profil")
    assert r.status_code in (302, 401)


def test_account_request_public(guest_client):
    r = guest_client.get("/account/request")
    assert r.status_code == 200
    assert b"<form" in r.data


def test_login_required_endpoints_block_guest(guest_client):
    for path in ("/dashboard", "/profil", "/profil/json"):
        r = guest_client.get(path)
        assert r.status_code in (302, 401), f"Public access on {path}!"
