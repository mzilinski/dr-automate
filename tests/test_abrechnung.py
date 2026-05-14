"""Tests für die Reisekostenabrechnung (Berechnung, Modell, PDF-Roundtrip)."""

import json
import os
import sys
from datetime import datetime

import pytest
from pypdf import PdfReader

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import nrkvo_rates  # noqa: E402
from abrechnung_calc import berechnung, tagegeld_tage  # noqa: E402
from generator_abrechnung import fill_pdf  # noqa: E402
from models import AbrechnungData, validate_abrechnung  # noqa: E402

# ---------- Fixtures ----------


@pytest.fixture
def base_data():
    """Minimaler valider Abrechnungs-Datensatz (1 Tag, PKW §II)."""
    with open("example_input.json") as f:
        d = json.load(f)
    d["stammdaten"] = {
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "email": "test@example.com",
        "abrechnende_dienststelle": "NLBV Aurich",
    }
    d["rkr"] = "DR"
    d["befoerderung"]["hinreise"]["paragraph_5_nrkvo"] = "II"
    d["befoerderung"]["rueckreise"]["paragraph_5_nrkvo"] = "II"
    return d


# ---------- Pydantic-Modell ----------


def test_validate_abrechnung_minimal_valid(base_data):
    ok, result = validate_abrechnung(base_data)
    assert ok, f"Validation failed: {result}"
    assert isinstance(result, AbrechnungData)
    assert result.stammdaten.iban == "DE89370400440532013000"


def test_iban_normalize_strips_whitespace(base_data):
    base_data["stammdaten"]["iban"] = "DE89 3704 0044 0532 0130 00"
    ok, result = validate_abrechnung(base_data)
    assert ok
    assert result.stammdaten.iban == "DE89370400440532013000"


def test_iban_too_long_is_rejected(base_data):
    """IBAN > 22 Zeichen (z.B. MT) ist nicht im Vordruck abbildbar — Validation muss greifen."""
    base_data["stammdaten"]["iban"] = "MT84MALT011000012345MTLCAST001S"  # 31 Zeichen
    ok, result = validate_abrechnung(base_data)
    assert not ok, "31-stellige IBAN haette abgelehnt werden muessen"
    assert "22" in str(result)  # Fehlertext nennt das Limit


def test_validate_abrechnung_rejects_invalid_rkr(base_data):
    base_data["rkr"] = "FOOBAR"
    ok, result = validate_abrechnung(base_data)
    assert not ok


def test_validate_abrechnung_defaults_for_optional_blocks(base_data):
    # Keine optionalen Blöcke → Defaults werden gesetzt
    for k in ("verpflegung", "uebernachtungen", "beleg_betraege", "wegstrecke", "abzuege", "flags"):
        base_data.pop(k, None)
    ok, result = validate_abrechnung(base_data)
    assert ok
    assert result.verpflegung.fruehstueck_anzahl == 0
    assert result.uebernachtungen.anzahl_pauschal == 0


def test_negative_amounts_rejected(base_data):
    base_data["beleg_betraege"] = {"fahrkarte_eur": -10}
    ok, result = validate_abrechnung(base_data)
    assert not ok


# ---------- Tagegeld-Tage ----------


def test_tagegeld_eintaegig_unter_8h():
    s = datetime(2026, 5, 15, 9, 0)
    e = datetime(2026, 5, 15, 16, 0)
    assert tagegeld_tage(s, e) == (0, 0)


def test_tagegeld_eintaegig_ueber_8h():
    s = datetime(2026, 5, 15, 6, 0)
    e = datetime(2026, 5, 15, 18, 0)
    assert tagegeld_tage(s, e) == (0, 1)


def test_tagegeld_zweitaegig():
    s = datetime(2026, 5, 15, 6, 0)
    e = datetime(2026, 5, 16, 20, 0)
    assert tagegeld_tage(s, e) == (0, 2)


def test_tagegeld_dreitaegig():
    s = datetime(2026, 5, 15, 6, 0)
    e = datetime(2026, 5, 17, 20, 0)
    assert tagegeld_tage(s, e) == (1, 2)


def test_tagegeld_woche():
    s = datetime(2026, 5, 11, 6, 0)
    e = datetime(2026, 5, 17, 20, 0)
    assert tagegeld_tage(s, e) == (5, 2)


def test_tagegeld_kurz_ueber_mitternacht_unter_8h():
    """Bug-Regression: 23:00→06:00 = 7 h, alte Logik gab (0, 2) zurueck."""
    s = datetime(2026, 5, 15, 23, 0)
    e = datetime(2026, 5, 16, 6, 0)
    assert tagegeld_tage(s, e) == (0, 0)


def test_tagegeld_ueber_mitternacht_8_bis_24h():
    """18:00→09:00 = 15 h, einmaliger Teiltag — nicht 2."""
    s = datetime(2026, 5, 15, 18, 0)
    e = datetime(2026, 5, 16, 9, 0)
    assert tagegeld_tage(s, e) == (0, 1)


# ---------- Berechnung ----------


def test_berechnung_eintaegig_unter_8h_kein_tagegeld(base_data):
    base_data["reise_details"]["start_datum"] = "15.05.2026"
    base_data["reise_details"]["start_zeit"] = "09:00"
    base_data["reise_details"]["ende_datum"] = "15.05.2026"
    base_data["reise_details"]["ende_zeit"] = "16:00"
    base_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "15.05.2026"
    base_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "10:00"
    base_data["reise_details"]["dienstgeschaeft_ende_datum"] = "15.05.2026"
    base_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "15:00"
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.tagegeld_brutto_eur == 0


def test_berechnung_zweitaegig_zwei_teiltage(base_data):
    base_data["reise_details"]["start_datum"] = "15.05.2026"
    base_data["reise_details"]["start_zeit"] = "06:00"
    base_data["reise_details"]["ende_datum"] = "16.05.2026"
    base_data["reise_details"]["ende_zeit"] = "20:00"
    base_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "15.05.2026"
    base_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "10:00"
    base_data["reise_details"]["dienstgeschaeft_ende_datum"] = "16.05.2026"
    base_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "16:00"
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.tagegeld_brutto_eur == 28.0  # 2 × 14 €


def test_berechnung_kuerzung_fruehstueck(base_data):
    base_data["verpflegung"] = {"fruehstueck_anzahl": 1}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.kuerzung_eur == pytest.approx(5.60, abs=0.01)


def test_berechnung_kuerzung_voll_paket(base_data):
    """Frühstück + Mittag + Abend = 100 % vom vollen Tagegeld."""
    base_data["verpflegung"] = {"fruehstueck_anzahl": 1, "mittag_anzahl": 1, "abend_anzahl": 1}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.kuerzung_eur == pytest.approx(28.0, abs=0.01)


def test_berechnung_kuerzung_kann_tagegeld_nicht_unter_null_druecken(base_data):
    """Bei nur Teiltagen kann die Kürzung nicht negativ werden."""
    # 1-Tagesreise > 8 h → 14 € Tagegeld
    base_data["reise_details"]["start_datum"] = "15.05.2026"
    base_data["reise_details"]["start_zeit"] = "06:00"
    base_data["reise_details"]["ende_datum"] = "15.05.2026"
    base_data["reise_details"]["ende_zeit"] = "20:00"
    base_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "15.05.2026"
    base_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "10:00"
    base_data["reise_details"]["dienstgeschaeft_ende_datum"] = "15.05.2026"
    base_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "16:00"
    base_data["verpflegung"] = {"fruehstueck_anzahl": 1, "mittag_anzahl": 1, "abend_anzahl": 1}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.tagegeld_netto_eur == 0
    assert b.kuerzung_eur == 14.0  # nicht 28


def test_berechnung_2km_regel_kein_tagegeld(base_data):
    base_data["konfiguration_checkboxen"]["dienstgeschaeft_2km_umkreis"] = True
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.tagegeld_brutto_eur == 0
    assert b.tagegeld_netto_eur == 0


def test_berechnung_verzicht_tagegeld(base_data):
    base_data["verzicht_erklaerung"]["verzicht_tagegeld"] = True
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.tagegeld_brutto_eur == 0
    assert b.tagegeld_netto_eur == 0


def test_berechnung_wegstrecke_klein_satz(base_data):
    base_data["wegstrecke"] = {"km_hinreise": 100, "km_rueckreise": 100}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    # 200 km × 0,25 = 50 €
    assert b.wegstreckenentschaedigung_eur == 50.0


def test_berechnung_wegstrecke_klein_cap_125_eur(base_data):
    # § 5 II: Cap bei 125 € pro Reise
    base_data["wegstrecke"] = {"km_hinreise": 1000, "km_rueckreise": 1000}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.wegstreckenentschaedigung_eur == 125.0


def test_berechnung_wegstrecke_gross_kein_cap(base_data):
    base_data["befoerderung"]["hinreise"]["paragraph_5_nrkvo"] = "III"
    base_data["befoerderung"]["rueckreise"]["paragraph_5_nrkvo"] = "III"
    base_data["wegstrecke"] = {"km_hinreise": 500, "km_rueckreise": 500}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    # 1000 km × 0,38 = 380 €
    assert b.wegstreckenentschaedigung_eur == 380.0


def test_berechnung_wegstrecke_keine_bei_bahn(base_data):
    base_data["befoerderung"]["hinreise"]["typ"] = "BAHN"
    base_data["befoerderung"]["rueckreise"]["typ"] = "BAHN"
    base_data["wegstrecke"] = {"km_hinreise": 500, "km_rueckreise": 500}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.wegstreckenentschaedigung_eur == 0


def test_berechnung_wegstrecke_keine_bei_mitfahrt(base_data):
    """MITFAHRT: Mitfahrer hat keinen eigenen Anspruch — auch wenn km eingetragen."""
    base_data["befoerderung"]["hinreise"]["typ"] = "MITFAHRT"
    base_data["befoerderung"]["rueckreise"]["typ"] = "MITFAHRT"
    base_data["wegstrecke"] = {"km_hinreise": 200, "km_rueckreise": 200}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.wegstreckenentschaedigung_eur == 0


def test_mitfahrt_validates(base_data):
    base_data["befoerderung"]["hinreise"]["typ"] = "MITFAHRT"
    ok, d = validate_abrechnung(base_data)
    assert ok
    assert d.befoerderung.hinreise.typ == "MITFAHRT"


def test_mitfahrt_pdf_erlaeuterung(base_data, tmp_path):
    """Mitfahrt-Hinweis erscheint automatisch im Erläuterungen-Feld."""
    base_data["befoerderung"]["hinreise"]["typ"] = "MITFAHRT"
    base_data["befoerderung"]["rueckreise"]["typ"] = "MITFAHRT"
    ok, d = validate_abrechnung(base_data)
    assert ok
    out = fill_pdf(d, "forms/Reisekostenvordruck.pdf", str(tmp_path))
    fields = PdfReader(out).get_fields()
    erl = fields["Erlaeuterungen"]["/V"]
    assert "Mitfahrer hin und zurück" in erl
    assert "Wegstreckenentschädigung" in erl


def test_mitfahrt_einseitig_pdf_erlaeuterung(base_data, tmp_path):
    """Nur Hinreise als Mitfahrt — Hinweis spezifiziert die Richtung."""
    base_data["befoerderung"]["hinreise"]["typ"] = "MITFAHRT"
    # Rueckreise bleibt PKW
    ok, d = validate_abrechnung(base_data)
    assert ok
    out = fill_pdf(d, "forms/Reisekostenvordruck.pdf", str(tmp_path))
    fields = PdfReader(out).get_fields()
    erl = fields["Erlaeuterungen"]["/V"]
    assert "Hinreise: Mitfahrer" in erl


def test_antrag_pdf_mitfahrt_box(base_data, tmp_path):
    """Antrag-Generator setzt Mitfahrt-Boxen (OBJ44/OBJ50) bei MITFAHRT."""
    from generator import fill_pdf as fill_antrag_pdf

    base_data["befoerderung"]["hinreise"]["typ"] = "MITFAHRT"
    base_data["befoerderung"]["rueckreise"]["typ"] = "MITFAHRT"
    out = fill_antrag_pdf(base_data, "forms/DR-Antrag_035_001Stand4-2025pdf.pdf", str(tmp_path))
    fields = PdfReader(out).get_fields()
    assert fields["OBJ44"]["/V"] == "/Yes"
    assert fields["OBJ50"]["/V"] == "/Yes"


def test_berechnung_uebernachtungsgeld_pauschal(base_data):
    # Reise auf 4 Tage = 3 Naechte verlaengern (sonst greift Plausibilitaets-Cap)
    base_data["reise_details"]["start_datum"] = "15.05.2026"
    base_data["reise_details"]["ende_datum"] = "18.05.2026"
    base_data["uebernachtungen"] = {"anzahl_pauschal": 3}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.uebernachtungsgeld_pauschal_eur == 60.0


def test_pauschal_naechte_werden_gegen_reisedauer_gedeckelt(base_data):
    """Eintaegige Reise + 5 Naechte → max 0 Naechte gewertet (Plausibilisierung)."""
    # base_data ist eine Tagesreise; falls nicht, hier anpassen
    rd = base_data["reise_details"]
    rd["start_datum"] = "10.05.2026"
    rd["start_zeit"] = "07:00"
    rd["ende_datum"] = "10.05.2026"
    rd["ende_zeit"] = "20:00"
    base_data["uebernachtungen"] = {"anzahl_pauschal": 5}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.uebernachtungsgeld_pauschal_eur == 0.0, "Eintagesreise sollte 0 Pauschal-Naechte ergeben"


def test_pauschal_naechte_capped_at_reisedauer(base_data):
    """4-Tage-Reise (3 Naechte) + 10 Naechte Input → 3 Naechte gewertet."""
    rd = base_data["reise_details"]
    rd["start_datum"] = "10.05.2026"
    rd["start_zeit"] = "07:00"
    rd["ende_datum"] = "13.05.2026"
    rd["ende_zeit"] = "20:00"
    base_data["uebernachtungen"] = {"anzahl_pauschal": 10}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.uebernachtungsgeld_pauschal_eur == 60.0, "Sollte auf 3 Naechte × 20 € = 60 € gedeckelt sein"


def test_berechnung_uebernachtungsgeld_max_14_naechte(base_data):
    # Reise auf 21 Tage = 20 Naechte ziehen, damit das 14-Naechte-Cap greift
    # (nicht der Plausibilitaets-Cap gegen Reisedauer).
    base_data["reise_details"]["start_datum"] = "01.05.2026"
    base_data["reise_details"]["ende_datum"] = "21.05.2026"
    base_data["uebernachtungen"] = {"anzahl_pauschal": 30}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    assert b.uebernachtungsgeld_pauschal_eur == 14 * 20.0


def test_berechnung_zwischensumme_und_auszahl(base_data):
    base_data["uebernachtungen"] = {"anzahl_pauschal": 1, "kosten_eur": 80}
    base_data["beleg_betraege"] = {"fahrkarte_eur": 50}
    base_data["abzuege"] = {"reisekostenabschlag_eur": 30}
    ok, d = validate_abrechnung(base_data)
    assert ok
    b = berechnung(d)
    # 28 € voll + 28 € teil (3-Tage) + 20 € pauschal + 80 € Beleg + 50 € Fahrkarte = 206 €
    # Wegstrecke ist im base_data 0 (keine km gesetzt)
    assert b.zwischensumme_eur == pytest.approx(206.0, abs=0.01)
    assert b.auszahlbetrag_eur == pytest.approx(176.0, abs=0.01)


# ---------- PDF-Roundtrip ----------


def test_pdf_roundtrip(base_data, tmp_path):
    base_data["wegstrecke"] = {"km_hinreise": 100, "km_rueckreise": 100}
    ok, d = validate_abrechnung(base_data)
    assert ok
    out = fill_pdf(d, "forms/Reisekostenvordruck.pdf", str(tmp_path))
    assert os.path.exists(out)
    # Lese zurück
    r = PdfReader(out)
    fields = r.get_fields()
    # IBAN char-für-char
    iban = base_data["stammdaten"]["iban"]
    for i, ch in enumerate(iban):
        assert fields[f"IBAN{i + 1}"]["/V"] == ch
    # Name
    assert fields["Name__Vorname"]["/V"] == base_data["antragsteller"]["name"]
    # Beschäftigungsstelle
    assert fields["Beschaeftigungsstelle"]["/V"] == base_data["antragsteller"]["abteilung"]
    # BIC (Feldname auf Stand 08.2025 von "Kreditinstitut" zu "BIC" umbenannt)
    assert fields["BIC"]["/V"] == base_data["stammdaten"]["bic"]


def test_pdf_filename_format(base_data, tmp_path):
    ok, d = validate_abrechnung(base_data)
    assert ok
    out = fill_pdf(d, "forms/Reisekostenvordruck.pdf", str(tmp_path))
    name = os.path.basename(out)
    assert name.startswith("20260515_DR-Abrechnung_")
    assert name.endswith(".pdf")


# ---------- Flask-Endpoints ----------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("DR_PASSPHRASE", "")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    return app_module.app.test_client()


def test_abrechnung_index_200(client):
    r = client.get("/abrechnung")
    assert r.status_code == 200
    assert b"Reisekosten" in r.data


def test_abrechnung_generate_returns_pdf(client, base_data):
    r = client.post("/abrechnung/generate", data={"json_data": json.dumps(base_data)})
    assert r.status_code == 200, r.data
    assert r.mimetype == "application/pdf"
    assert b"%PDF" in r.data[:10]


def test_abrechnung_generate_invalid_json(client):
    r = client.post("/abrechnung/generate", data={"json_data": "not json"})
    assert r.status_code == 400


def test_abrechnung_calc_returns_calculation(client, base_data):
    r = client.post("/abrechnung/calc", data={"json_data": json.dumps(base_data)})
    assert r.status_code == 200
    body = r.get_json()
    assert "tagegeld_brutto_eur" in body
    assert "auszahlbetrag_eur" in body


def test_abrechnung_generate_rechnet_kuerzung_serverseitig(client, base_data, tmp_path):
    """Regression: Frontend schickt 'berechnet' nicht zurück → Server muss neu rechnen.

    Vor dem Fix landete Brutto-Tagegeld im PDF, aber die Verpflegungs-Kürzung
    (Zeile 3 / EUR7) blieb leer, weil das Wizard-State 'berechnet' nicht
    aktualisiert und der Server-Endpoint dem Default vertraute.
    """
    # 4-Tage-Reise, 3 inkludierte Mahlzeiten an einem vollen Tag → 28 € Kürzung
    base_data["reise_details"]["start_datum"] = "10.05.2026"
    base_data["reise_details"]["start_zeit"] = "13:30"
    base_data["reise_details"]["ende_datum"] = "13.05.2026"
    base_data["reise_details"]["ende_zeit"] = "19:30"
    base_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "10.05.2026"
    base_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "18:00"
    base_data["reise_details"]["dienstgeschaeft_ende_datum"] = "13.05.2026"
    base_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "15:00"
    base_data["verpflegung"] = {"fruehstueck_anzahl": 3, "mittag_anzahl": 3, "abend_anzahl": 3}
    # Bewusst die Default-Nullen simulieren, die das Frontend mitschickt
    base_data["berechnet"] = {"tagegeld_brutto_eur": 0, "kuerzung_eur": 0, "tagegeld_netto_eur": 0}

    r = client.post("/abrechnung/generate", data={"json_data": json.dumps(base_data)})
    assert r.status_code == 200, r.data

    out_pdf = tmp_path / "out.pdf"
    out_pdf.write_bytes(r.data)
    fields = PdfReader(str(out_pdf)).get_form_text_fields() or {}

    # Brutto: 2× voller Tag à 28 € + 2× Teiltag à 14 € = 84 €
    assert fields.get("EUR") == "56,00"
    assert fields.get("EUR6") == "28,00"
    # Kürzung 84 € (3×5,60 + 3×11,20 + 3×11,20) → Netto 0,00 €
    # Der Server muss EUR7 jetzt füllen, weil kuerzung_eur > 0
    assert fields.get("EUR7") == "0,00", f"Server hat berechnet nicht überschrieben — EUR7={fields.get('EUR7')!r}"


# ---------- NRKVO-Sätze ----------


def test_nrkvo_kuerzungen_konsistent():
    assert nrkvo_rates.kuerzung_fruehstueck_eur() == 5.6
    assert nrkvo_rates.kuerzung_mittagessen_eur() == 11.2
    assert nrkvo_rates.kuerzung_abendessen_eur() == 11.2


def test_nrkvo_wegstrecke_satz_dispatcher():
    assert nrkvo_rates.wegstrecke_satz_eur("II") == 0.25
    assert nrkvo_rates.wegstrecke_satz_eur("III") == 0.38
