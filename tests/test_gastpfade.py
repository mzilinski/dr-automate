"""Identität nur auf two_factor-geschützten Pfaden (Live-Problem 2026-10-26).

Authelia schickt auf Bypass-Pfaden Remote-* auch für Sessions, die erst das
Passwort (1. Faktor) haben. Die App darf dort deshalb nichts aus dem Konto
zeigen oder schreiben."""

from __future__ import annotations

import json
import os
import uuid

import pytest

import auth

PROFIL = {
    "vorname": "Erika",
    "nachname": "Muster",
    "abteilung": "BBS",
    "telefon": "0591 123456",
    "adresse_privat": "Geheimweg 7, 49808 Lingen",
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
    "deepseek_api_key": "sk-gespeichert",
}


@pytest.fixture
def user(auth_client):
    h = {"Remote-User": f"gp_{uuid.uuid4().hex[:8]}", "Remote-Groups": "admins"}
    auth_client.post("/profil", data=PROFIL, headers=h)
    return h


def _antrag():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "example_input.json")) as f:
        return json.load(f)


@pytest.mark.parametrize(
    ("pfad", "ziel"),
    [
        ("/", "/dashboard"),
        ("/abrechnung", "/konto/abrechnung"),
        ("/landing", "/dashboard"),
        ("/?dienstreise=5", "/konto/?dienstreise=5"),
    ],
)
def test_gastseite_leitet_session_ins_konto(auth_client, user, pfad, ziel):
    r = auth_client.get(pfad, headers=user)
    assert r.status_code == 302 and r.headers["Location"] == ziel
    assert b"DE89" not in r.data and b"Geheimweg" not in r.data


def test_fremde_gruppe_bleibt_gast_ohne_umleitung(app_module, auth_client):
    """household hat in Authelia keinen Zugang zu /konto — darf nicht dorthin umgeleitet werden."""
    app_module.app.config["ALLOWED_GROUPS"] = "admins,dr-automate-users"
    try:
        r = auth_client.get("/", headers={"Remote-User": "nachbar_gp", "Remote-Groups": "household"})
    finally:
        app_module.app.config.pop("ALLOWED_GROUPS", None)
    assert r.status_code == 200 and b"Gast-Modus" in r.data


def test_kontoseite_zeigt_profil(auth_client, user):
    r = auth_client.get("/konto/", headers=user)
    assert r.status_code == 200 and b"DE89370400440532013000" in r.data
    assert b"/konto/generate" in r.data and b"/konto/extract" in r.data


def test_generate_auf_gastpfad_speichert_nicht(auth_client, user):
    r = auth_client.post("/generate", data={"json_data": json.dumps(_antrag()), "save_to_account": "1"}, headers=user)
    assert r.status_code == 200 and "X-Dienstreise-Id" not in r.headers


def test_abrechnung_auf_gastpfad_ueberschreibt_nicht(auth_client, user):
    rid = auth_client.post(
        "/konto/generate", data={"json_data": json.dumps(_antrag()), "save_to_account": "1"}, headers=user
    ).headers["X-Dienstreise-Id"]
    abr = {**_antrag(), "stammdaten": {"iban": "DE89370400440532013000", "bic": "X", "abrechnende_dienststelle": "N"}}
    r = auth_client.post(
        "/abrechnung/generate",
        data={"json_data": json.dumps(abr), "save_to_account": "1", "dienstreise_id": rid},
        headers=user,
    )
    assert r.status_code == 200 and "X-Abrechnung-Id" not in r.headers


def test_extract_auf_gastpfad_nutzt_keinen_gespeicherten_key(auth_client, user):
    r = auth_client.post("/extract", data={"freitext": "Tagung"}, headers=user)
    assert r.status_code == 400 and "API-Key fehlt" in r.get_json()["error"]


def test_api_berechtigung_nur_auf_geschuetzten_pfaden(auth_client, user):
    from datetime import datetime, timedelta

    from db import SessionLocal
    from models_db import User

    with SessionLocal() as s:
        u = s.query(User).filter(User.remote_user == user["Remote-User"]).one()
        u.api_berechtigt_bis = datetime.utcnow() - timedelta(days=1)
        s.commit()
    auth_client.get("/", headers=user)
    auth_client.post("/generate", data={"json_data": "{}"}, headers=user)
    with SessionLocal() as s:
        assert (
            s.query(User).filter(User.remote_user == user["Remote-User"]).one().api_berechtigt_bis < datetime.utcnow()
        )


@pytest.mark.parametrize(
    ("pfad", "geschuetzt"),
    [
        ("/konto/", True),
        ("/konto/generate", True),
        ("/dashboard", True),
        ("/dienstreisen/3/antrag.pdf", True),
        ("/profil", True),
        ("/profil/api-keys", True),
        ("/admin/account-requests", True),
        ("/", False),
        ("/generate", False),
        ("/extract", False),
        ("/api/v1/me", False),
        ("/docs/faq", False),
        ("/profilfoo", False),
        ("/konto-fake", False),
    ],
)
def test_pfad_geschuetzt(pfad, geschuetzt):
    assert auth.pfad_geschuetzt(pfad) is geschuetzt


def test_hilfeseite_mit_session_zeigt_nur_kontolink(auth_client, user):
    html = auth_client.get("/docs/faq", headers=user).get_data(as_text=True)
    assert "Zum Konto" in html and 'class="pill guest"' not in html
    assert user["Remote-User"] not in html  # keine Identität auf Gast-Pfaden
    assert 'class="pill guest"' in auth_client.get("/docs/faq").get_data(as_text=True)
