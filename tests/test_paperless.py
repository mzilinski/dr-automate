"""Paperless-Anbindung: Einreihen, Upload, Task-Status, Wiederholung (plan-api-v1.md §11)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

import pytest

import paperless_sync
from tests.test_api_v1 import PROFIL, abrechnung_v1, antrag_v1


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakePaperless:
    """Minimaler Paperless-Ersatz: Tag 'Dienstreise' existiert, Dokumenttypen nicht."""

    def __init__(self, task_status="SUCCESS", task_result="", fehler=False):
        self.posts, self.gets = [], []
        self.task_status, self.task_result, self.fehler = task_status, task_result, fehler

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, params, headers))
        if self.fehler:
            raise ConnectionError("Paperless nicht erreichbar")
        if url.endswith("/api/tags/"):
            return FakeResp({"results": [{"id": 7}]} if params["name__iexact"] == "Dienstreise" else {"results": []})
        if url.endswith("/api/document_types/"):
            return FakeResp({"results": []})
        if url.endswith("/api/tasks/"):
            return FakeResp([{"status": self.task_status, "related_document": "55", "result": self.task_result}])
        return FakeResp({}, 404)

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "data": data, "datei": files["document"][0]})
        return FakeResp("2b1c-task")


@pytest.fixture(autouse=True)
def paperless_url(monkeypatch):
    monkeypatch.setenv("PAPERLESS_URL", "https://paperless.example.org")


@pytest.fixture
def admin():
    return {"Remote-User": f"pl_{uuid.uuid4().hex[:8]}", "Remote-Groups": "admins"}


@pytest.fixture
def key(auth_client, admin):
    r = auth_client.post(
        "/profil/api-keys",
        data={"name": "pl", "laufzeit_tage": "30", "scopes": ["reisen:read", "reisen:write"]},
        headers=admin,
    )
    return {
        "Authorization": "Bearer " + re.search(r"dra_[0-9a-f]{12}_[A-Za-z0-9_-]+", r.get_data(as_text=True)).group(0)
    }


def _profil(client, admin, **extra):
    client.post("/profil", data={**PROFIL, **extra}, headers=admin)


def _reise(client, key) -> int:
    return client.post("/api/v1/reisen", json=antrag_v1(), headers=key).get_json()["id"]


def _uploads(reise_id):
    return paperless_sync.status_je_reise([reise_id]).get(reise_id, {})


def test_ohne_automatik_nichts_eingereiht(auth_client, admin, key):
    _profil(auth_client, admin, paperless_api_token="tok-123")
    rid = _reise(auth_client, key)
    auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026"}, headers=key)
    assert _uploads(rid) == {}


def test_genehmigung_legt_antrag_ab(auth_client, admin, key):
    _profil(auth_client, admin, paperless_api_token="tok-123", paperless_auto="1")
    rid = _reise(auth_client, key)
    auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026"}, headers=key)
    assert _uploads(rid)["antrag"].status == "offen"

    http = FakePaperless()
    paperless_sync.verarbeiten(http=http)
    post = http.posts[-1]
    assert post["url"] == "https://paperless.example.org/api/documents/post_document/"
    assert post["headers"]["Authorization"] == "Token tok-123"
    assert post["data"]["tags"] == [7] and "document_type" not in post["data"]
    assert post["data"]["created"] == "2026-05-15"
    assert post["data"]["title"].startswith("Dienstreiseantrag Fortbildung")
    assert _uploads(rid)["antrag"].status == "gesendet"

    paperless_sync.verarbeiten(http=http, jetzt=datetime.utcnow() + timedelta(minutes=1))
    up = _uploads(rid)["antrag"]
    assert (up.status, up.dokument_id) == ("fertig", 55)
    j = auth_client.get(f"/api/v1/reisen/{rid}", headers=key).get_json()
    assert j["paperless"]["antrag"]["status"] == "fertig"


def test_bezahlt_legt_abrechnung_ab(auth_client, admin, key):
    _profil(auth_client, admin, paperless_api_token="tok-1", paperless_auto="1")
    rid = _reise(auth_client, key)
    auth_client.put(f"/api/v1/reisen/{rid}/abrechnung", json=abrechnung_v1(), headers=key)
    auth_client.post(f"/api/v1/reisen/{rid}/bezahlt", headers=key)
    assert _uploads(rid)["abrechnung"].status == "offen"
    http = FakePaperless()
    paperless_sync.verarbeiten(http=http)
    assert http.posts[-1]["datei"] == "abrechnung.pdf"


@pytest.mark.parametrize(
    ("result", "erwartet"),
    [("Not consuming x: It is a duplicate of y", "fertig"), ("Kaputtes PDF", "fehler")],
)
def test_task_fehler(auth_client, admin, key, result, erwartet):
    _profil(auth_client, admin, paperless_api_token="tok", paperless_auto="1")
    rid = _reise(auth_client, key)
    auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026"}, headers=key)
    http = FakePaperless(task_status="FAILURE", task_result=result)
    paperless_sync.verarbeiten(http=http)
    paperless_sync.verarbeiten(http=http, jetzt=datetime.utcnow() + timedelta(minutes=1))
    assert _uploads(rid)["antrag"].status == erwartet


def test_wiederholung_bis_fehler(auth_client, admin, key):
    _profil(auth_client, admin, paperless_api_token="tok", paperless_auto="1")
    rid = _reise(auth_client, key)
    auth_client.post(f"/api/v1/reisen/{rid}/genehmigung", json={"datum": "01.05.2026"}, headers=key)
    http = FakePaperless(fehler=True)
    jetzt = datetime.utcnow()
    for i in range(paperless_sync.MAX_VERSUCHE):
        paperless_sync.verarbeiten(http=http, jetzt=jetzt)
        jetzt += timedelta(minutes=2 ** (i + 1) + 1)
    up = _uploads(rid)["antrag"]
    assert up.status == "fehler" and up.versuche == paperless_sync.MAX_VERSUCHE
    assert "nicht erreichbar" in up.meldung


def test_api_manuell(auth_client, admin, key):
    _profil(auth_client, admin)  # Profil ohne Paperless-Token
    rid = _reise(auth_client, key)
    r = auth_client.post(f"/api/v1/reisen/{rid}/paperless", json={"art": "antrag"}, headers=key)
    assert r.status_code == 422  # kein Token
    _profil(auth_client, admin, paperless_api_token="tok")
    r = auth_client.post(f"/api/v1/reisen/{rid}/paperless", json={"art": "antrag"}, headers=key)
    assert r.status_code == 202 and r.get_json()["antrag"]["status"] == "offen"
    r = auth_client.post(f"/api/v1/reisen/{rid}/paperless", json={"art": "abrechnung"}, headers=key)
    assert r.status_code == 409  # noch kein Abrechnungs-PDF


def test_dashboard_button(auth_client, admin, key):
    _profil(auth_client, admin, paperless_api_token="tok")
    rid = _reise(auth_client, key)
    html = auth_client.get("/dashboard", headers=admin).get_data(as_text=True)
    assert "Antrag → Paperless" in html
    r = auth_client.post(f"/dienstreisen/{rid}/paperless", data={"art": "antrag"}, headers=admin)
    assert r.status_code == 302 and _uploads(rid)["antrag"].status == "offen"


def test_token_nur_fuer_admins_und_verschluesselt(auth_client):
    import os
    import sqlite3

    h = {"Remote-User": f"kein_admin_{uuid.uuid4().hex[:6]}", "Remote-Groups": "dr-automate-users"}
    auth_client.post("/profil", data={**PROFIL, "paperless_api_token": "fremd-tok"}, headers=h)
    db = os.environ["DR_AUTOMATE_DATABASE_URL"].removeprefix("sqlite:///")
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT paperless_api_token FROM user_profiles WHERE paperless_api_token IS NOT NULL"
    ).fetchall()
    conn.close()
    assert all("tok" not in r[0] for r in rows)  # nur Fernet-Token, nie Klartext
    assert "fremd" not in json.dumps(rows)
