"""Phase-3/4-Tests: profil-autoritativer Merge, Platzhalter-Abweisung,
Prompt-Strip, Reise-Kontext und der /extract- bzw. /generate-Vertrag.

DeepSeek-Aufrufe sind gemockt — keine echten Netzaufrufe.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import app
from models import (
    apply_profile_authoritative,
    bahncards_to_konfig_flags,
    find_placeholder,
    validate_reiseantrag,
)


@pytest.fixture
def client():
    app.app.config["TESTING"] = True
    app.app.config["WTF_CSRF_ENABLED"] = False
    app.app.config["TRUST_REMOTE_USER_HEADER"] = False
    with app.app.test_client() as c:
        yield c


def _partial_ai_json() -> dict:
    """So liefert die KI künftig: ohne antragsteller/befoerderung."""
    return {
        "reise_details": {
            "zielort": "26486 Wangerooge",
            "reiseweg": "Lingen -> Wangerooge -> Lingen",
            "zweck": "Fortbildung: Sensordaten",
            "start_datum": "02.05.2027",
            "start_zeit": "13:30",
            "ende_datum": "05.05.2027",
            "ende_zeit": "19:30",
            "dienstgeschaeft_beginn_datum": "02.05.2027",
            "dienstgeschaeft_beginn_zeit": "18:00",
            "dienstgeschaeft_ende_datum": "05.05.2027",
            "dienstgeschaeft_ende_zeit": "15:00",
        },
        "konfiguration_checkboxen": {"kosten_durch_andere_stelle": True},
    }


# --- apply_profile_authoritative -----------------------------------------


def test_profile_fields_win_when_present():
    data = _partial_ai_json()
    data["befoerderung"] = {
        "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
        "rueckreise": {"typ": "BAHN", "paragraph_5_nrkvo": "II"},
    }
    prof = {
        "name": "Malte Zilinski",
        "abteilung": "BBS Lingen",
        "telefon": "+4917693122465",
        "adresse_privat": "Am Biener Esch 11, 49808 Lingen",
        "mitreisender_name": "",
    }
    merged = apply_profile_authoritative(data, antragsteller=prof, bahncards={"grosskunde_1": True})
    assert merged["antragsteller"]["name"] == "Malte Zilinski"
    assert merged["konfiguration_checkboxen"]["grosskundenrabatt_genutzt"] is True
    # befoerderung bleibt Nutzer-Wahl, unangetastet
    assert merged["befoerderung"]["rueckreise"]["typ"] == "BAHN"
    ok, _ = validate_reiseantrag(merged)
    assert ok is True


def test_empty_profile_does_not_clobber_submitted():
    data = _partial_ai_json()
    data["antragsteller"] = {
        "name": "Echt Name",
        "abteilung": "Echt Abt",
        "telefon": "0591 12345",
        "adresse_privat": "Echte Str 1, 49808 Lingen",
        "mitreisender_name": "",
    }
    empty = {"name": "", "abteilung": "", "telefon": "", "adresse_privat": "", "mitreisender_name": ""}
    merged = apply_profile_authoritative(data, antragsteller=empty, bahncards={})
    assert merged["antragsteller"]["name"] == "Echt Name"
    assert merged["antragsteller"]["abteilung"] == "Echt Abt"


def test_none_profile_leaves_block_unchanged():
    data = _partial_ai_json()
    data["antragsteller"] = {"name": "Gast"}
    merged = apply_profile_authoritative(data, antragsteller=None, bahncards=None)
    assert merged["antragsteller"] == {"name": "Gast"}
    assert "konfiguration_checkboxen" in merged  # unverändert


def test_mitreisender_is_trip_specific():
    data = _partial_ai_json()
    data["antragsteller"] = {"name": "X", "mitreisender_name": "Reise-Kollege"}
    # Profil-Default gesetzt — darf den reise-spezifischen Wert NICHT überschreiben
    prof = {
        "name": "X",
        "abteilung": "A",
        "telefon": "12345",
        "adresse_privat": "Str 1, 12345 O",
        "mitreisender_name": "Default-Person",
    }
    merged = apply_profile_authoritative(data, antragsteller=prof, bahncards={})
    assert merged["antragsteller"]["mitreisender_name"] == "Reise-Kollege"


def test_bahncards_mapping_slot1_only():
    flags = bahncards_to_konfig_flags(
        {"bcb_1": True, "bc50_1": True, "grosskunde_1": True, "bcb_2": True, "grosskunde_2": True}
    )
    assert flags == {
        "bahncard_business_vorhanden": True,
        "bahncard_privat_vorhanden": True,
        "grosskundenrabatt_genutzt": True,
    }
    assert bahncards_to_konfig_flags(None) == {
        "bahncard_business_vorhanden": False,
        "bahncard_privat_vorhanden": False,
        "grosskundenrabatt_genutzt": False,
    }


# --- find_placeholder -----------------------------------------------------


def test_find_placeholder_detects_and_clears():
    assert find_placeholder({"antragsteller": {"name": "[DEIN NAME]"}}) == "[DEIN NAME]"
    assert find_placeholder({"a": ["x", {"b": "[DEINE ABTEILUNG]"}]}) == "[DEINE ABTEILUNG]"
    assert find_placeholder({"antragsteller": {"name": "Malte"}}) is None


# --- _load_system_prompt / strip -----------------------------------------


def test_system_prompt_strips_profile_section():
    p = app._load_system_prompt()
    assert "PROFIL:" not in p
    assert '"antragsteller"' not in p
    assert '"befoerderung"' not in p
    assert "bahncard_" not in p
    assert "reise_details" in p  # Kern-Schema intakt
    assert "\n\n\n" not in p


# --- _format_reise_kontext -----------------------------------------------


def test_format_reise_kontext():
    raw = json.dumps(
        {
            "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "III"},
            "rueckreise": {"typ": "MITFAHRT", "mitfahrer_name": "K. Müller"},
        }
    )
    out = app._format_reise_kontext(raw)
    assert "Hinreise: PKW" in out and "§ 5 III" in out
    assert "Rückreise: Mitfahrt bei K. Müller" in out
    assert app._format_reise_kontext("") == ""
    assert app._format_reise_kontext("{kaputt") == ""


# --- /extract-Vertrag -----------------------------------------------------


def test_extract_folds_reise_antworten_into_freitext(client):
    captured = {}

    def fake(freitext, api_key, system_prompt, sonderwuensche=""):
        captured["freitext"] = freitext
        captured["system_prompt"] = system_prompt
        return {"reise_details": {"zielort": "Wangerooge"}}

    with patch("app.ai_extract.call_deepseek", side_effect=fake):
        resp = client.post(
            "/extract",
            data={
                "freitext": "Fortbildung auf Wangerooge",
                "reise_antworten": json.dumps(
                    {"hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"}, "rueckreise": {"typ": "BAHN"}}
                ),
            },
            headers={"X-DeepSeek-Key": "sk-test"},
        )
    assert resp.status_code == 200
    assert "Beförderung" in captured["freitext"]
    assert "Hinreise: PKW" in captured["freitext"]
    assert "Rückreise: Bahn" in captured["freitext"]
    # Der an die KI gesendete Prompt ist die gestrippte Variante
    assert "PROFIL:" not in captured["system_prompt"]


def test_extract_without_reise_antworten_is_backward_compatible(client):
    captured = {}

    def fake(freitext, api_key, system_prompt, sonderwuensche=""):
        captured["freitext"] = freitext
        return {"reise_details": {"zielort": "Berlin"}}

    with patch("app.ai_extract.call_deepseek", side_effect=fake):
        resp = client.post(
            "/extract",
            data={"freitext": "Reise nach Berlin"},
            headers={"X-DeepSeek-Key": "sk-test"},
        )
    assert resp.status_code == 200
    assert "Beförderung" not in captured["freitext"]


# --- /generate Platzhalter-Abweisung -------------------------------------


def test_generate_rejects_placeholder(client):
    data = _partial_ai_json()
    data["antragsteller"] = {
        "name": "[DEIN NAME]",
        "abteilung": "[DEINE ABTEILUNG]",
        "telefon": "0591 12345",
        "adresse_privat": "Str 1, 49808 Lingen",
        "mitreisender_name": "",
    }
    data["befoerderung"] = {
        "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
        "rueckreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
    }
    resp = client.post("/generate", data={"json_data": json.dumps(data)})
    assert resp.status_code == 400
    assert "Platzhalter" in resp.get_json()["error"]
