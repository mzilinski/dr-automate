"""NRKVO-Regeln der Abrechnung (Review 2026-10-26): Tagegeld je Kalendertag,
Kürzung pro Tag, Daueraufenthalt, Übernachtung, Wegstrecken-Deckel und das
Mapping der Abrechnungs-Kästchen."""

import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from abrechnung_calc import berechnung, tagegeld_kalender, tagegeld_tage  # noqa: E402
from generator_abrechnung import _build_button_fields, _build_text_fields  # noqa: E402
from models import AbrechnungData  # noqa: E402


@pytest.fixture
def base_data():
    with open("example_input.json") as f:
        d = json.load(f)
    d["stammdaten"] = {
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "email": "test@example.com",
        "abrechnende_dienststelle": "NLBV Aurich",
    }
    d["befoerderung"] = {
        "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
        "rueckreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
    }
    return d


def _reise(d, start, ende):
    sd, sz = start.split()
    ed, ez = ende.split()
    rd = d["reise_details"]
    rd.update(
        start_datum=sd,
        start_zeit=sz,
        ende_datum=ed,
        ende_zeit=ez,
        dienstgeschaeft_beginn_datum=sd,
        dienstgeschaeft_beginn_zeit=sz,
        dienstgeschaeft_ende_datum=ed,
        dienstgeschaeft_ende_zeit=ez,
    )
    return d


def _calc(d):
    data = AbrechnungData.model_validate(d)
    data.berechnet = berechnung(data)
    return data


# ---------- Tagegeld (§ 7 NRKVO i. V. m. § 9 Abs. 4a EStG) ----------


def test_genau_8_stunden_ist_kein_teiltag():
    """EStG: „mehr als 8 Stunden" — genau 8 h gibt nichts."""
    assert tagegeld_tage(datetime(2026, 5, 15, 8, 0), datetime(2026, 5, 15, 16, 0)) == (0, 0)
    assert tagegeld_tage(datetime(2026, 5, 15, 8, 0), datetime(2026, 5, 15, 16, 1)) == (0, 1)


def test_unter_24h_mit_uebernachtung_zwei_teiltage():
    """An- und Abreisetag einer Reise mit Übernachtung: je 14 €, unabhängig von der Dauer."""
    s, e = datetime(2026, 5, 15, 18, 0), datetime(2026, 5, 16, 12, 0)
    assert tagegeld_tage(s, e) == (0, 1)
    assert tagegeld_tage(s, e, mit_uebernachtung=True) == (0, 2)


def test_ueber_mitternacht_ohne_uebernachtung_tag_mit_ueberwiegender_abwesenheit():
    tage = tagegeld_kalender(datetime(2026, 5, 15, 20, 0), datetime(2026, 5, 16, 9, 0))
    assert [t.art for t in tage] == ["", "teil"]  # 4 h vs. 9 h


def test_berechnung_uebernachtung_aktiviert_zwei_teiltage(base_data):
    _reise(base_data, "15.05.2026 18:00", "16.05.2026 12:00")
    base_data["uebernachtungen"] = {"anzahl_beleg": 1, "kosten_eur": 90}
    b = _calc(base_data).berechnet
    assert b.tagegeld_teiltage == 2
    assert b.tagegeld_brutto_eur == 28.0


def test_daueraufenthalt_ab_tag_15_vermindert(base_data):
    # 01.06. Anreise, 02.–17.06. = 16 Aufenthaltstage, 18.06. Abreise
    _reise(base_data, "01.06.2026 08:00", "18.06.2026 18:00")
    b = _calc(base_data).berechnet
    assert b.tagegeld_volle_tage == 14
    assert b.tagegeld_reduzierte_tage == 2
    assert b.tagegeld_teiltage == 2
    assert b.tagegeld_brutto_eur == 14 * 28 + 2 * 14 + 2 * 14
    assert any("§ 7 Abs. 2" in h for h in b.hinweise)


def test_daueraufenthalt_genau_14_tage_unvermindert(base_data):
    _reise(base_data, "01.06.2026 08:00", "16.06.2026 18:00")
    b = _calc(base_data).berechnet
    assert (b.tagegeld_volle_tage, b.tagegeld_reduzierte_tage) == (14, 0)


def test_sommerzeitumstellung_wie_ortszeit(base_data):
    """Server rechnet mit Ortszeit-Differenz (23,5 h) — kein DST-Sprung."""
    _reise(base_data, "24.10.2026 08:00", "25.10.2026 07:30")
    b = _calc(base_data).berechnet
    assert b.tagegeld_teiltage == 1


# ---------- Kürzung pro Kalendertag ----------


def test_kuerzung_pro_tag_gedeckelt(base_data):
    """Tag 1: Mittag + Abend (22,40 € > 14 €) → 14 €; Tag 2: Frühstück 5,60 €."""
    _reise(base_data, "15.05.2026 06:00", "16.05.2026 22:00")
    base_data["verpflegung"] = {
        "tage": [
            {"datum": "15.05.2026", "mittag": True, "abend": True},
            {"datum": "16.05.2026", "fruehstueck": True},
        ]
    }
    data = _calc(base_data)
    assert data.verpflegung.mittag_anzahl == 1  # Zähler aus den Tagen abgeleitet
    b = data.berechnet
    assert b.tagegeld_brutto_eur == 28.0
    assert b.kuerzung_eur == 19.6
    assert b.tagegeld_netto_eur == 8.4


def test_kuerzung_ohne_tage_nur_gesamt_gedeckelt(base_data):
    _reise(base_data, "15.05.2026 06:00", "16.05.2026 22:00")
    base_data["verpflegung"] = {"fruehstueck_anzahl": 1, "mittag_anzahl": 1, "abend_anzahl": 1}
    b = _calc(base_data).berechnet
    assert b.kuerzung_eur == 28.0
    assert b.tagegeld_netto_eur == 0.0


# ---------- Übernachtung ----------


def test_begruendung_ueber_100_nach_belegnaechten(base_data):
    _reise(base_data, "15.05.2026 06:00", "17.05.2026 18:00")
    base_data["uebernachtungen"] = {"anzahl_beleg": 2, "kosten_eur": 250}
    b = _calc(base_data).berechnet
    assert b.uebernachtung_beleg_pro_nacht_eur == 125.0
    assert b.begruendung_ueber_100_noetig is True


def test_begruendung_ohne_anzahl_beleg_aus_reisenaechten(base_data):
    _reise(base_data, "15.05.2026 06:00", "17.05.2026 18:00")
    base_data["uebernachtungen"] = {"kosten_eur": 180}
    b = _calc(base_data).berechnet
    assert b.uebernachtung_beleg_pro_nacht_eur == 90.0
    assert b.begruendung_ueber_100_noetig is False


def test_zu_viele_naechte_gibt_hinweis(base_data):
    _reise(base_data, "15.05.2026 06:00", "16.05.2026 18:00")
    base_data["uebernachtungen"] = {"anzahl_pauschal": 1, "anzahl_beleg": 1, "kosten_eur": 80}
    b = _calc(base_data).berechnet
    assert any("mehr Nächte" in h for h in b.hinweise)


def test_verzicht_uebernachtungsgeld_umfasst_belegkosten(base_data):
    _reise(base_data, "15.05.2026 06:00", "17.05.2026 18:00")
    base_data["uebernachtungen"] = {"anzahl_pauschal": 1, "anzahl_beleg": 1, "kosten_eur": 80}
    base_data["verzicht_erklaerung"] = {"verzicht_uebernachtungsgeld": True}
    data = _calc(base_data)
    assert data.berechnet.uebernachtungsgeld_pauschal_eur == 0
    assert data.berechnet.uebernachtung_beleg_eur == 0
    assert _build_text_fields(data)["Erstattung_Uebernachtungskosten"] == ""


def test_verzicht_erklaerung_null_wird_akzeptiert(base_data):
    base_data["verzicht_erklaerung"] = None
    assert _calc(base_data).verzicht_erklaerung.verzicht_tagegeld is False


# ---------- Wegstrecke (§ 5) ----------


def test_wegstrecke_cap_ignoriert_paragraph_von_nicht_pkw(base_data):
    """PKW § II 600 km hin, Mitfahrt zurück mit Rest-Paragraph III → trotzdem 125 €."""
    base_data["befoerderung"]["rueckreise"] = {"typ": "MITFAHRT", "paragraph_5_nrkvo": "III"}
    base_data["wegstrecke"] = {"km_hinreise": 600, "km_rueckreise": 600}
    b = _calc(base_data).berechnet
    assert b.wegstreckenentschaedigung_eur == 125.0
    assert b.wegstrecke_rueck_eur == 0.0


def test_wegstrecke_gemischt_deckelt_nur_klein_anteil(base_data):
    base_data["befoerderung"]["rueckreise"] = {"typ": "PKW", "paragraph_5_nrkvo": "III"}
    base_data["wegstrecke"] = {"km_hinreise": 600, "km_rueckreise": 100}
    b = _calc(base_data).berechnet
    assert b.wegstrecke_hin_eur == 125.0
    assert b.wegstrecke_rueck_eur == 38.0
    assert b.wegstreckenentschaedigung_eur == 163.0


def test_wegstrecke_pdf_summen_gedeckelt(base_data):
    base_data["wegstrecke"] = {"km_hinreise": 300, "km_rueckreise": 300}
    fields = _build_text_fields(_calc(base_data))
    assert fields["Wegstreckenentschaedigung"] == "75,00"
    assert fields["Wegstreckenentschaedigung1"] == "50,00"


def test_verzicht_fahrtkosten_leert_fahrt_felder(base_data):
    base_data["wegstrecke"] = {"km_hinreise": 50, "km_rueckreise": 50}
    base_data["beleg_betraege"] = {"fahrkarte_eur": 20, "zuschlaege_eur": 5, "sonstige_fahrt_eur": 7}
    base_data["verzicht_erklaerung"] = {"verzicht_fahrtkosten": True}
    fields = _build_text_fields(_calc(base_data))
    for f in ("Fahrkarte", "Zuschlaege", "Sonstige_Fahrauslagen", "Tage3", "Wegstreckenentschaedigung"):
        assert fields[f] == "", f
    assert "Verzicht auf Fahrtkosten" in fields["Erlaeuterungen"]


def test_verzicht_tagegeld_leert_tagegeld_zeilen(base_data):
    _reise(base_data, "15.05.2026 06:00", "17.05.2026 18:00")
    base_data["verzicht_erklaerung"] = {"verzicht_tagegeld": True}
    fields = _build_text_fields(_calc(base_data))
    assert fields["Tage"] == fields["EUR"] == fields["Tage6"] == fields["EUR6"] == ""


# ---------- Kästchen im Abrechnungs-PDF ----------


@pytest.mark.parametrize(("stufe", "feld"), [(25, "OBJ26"), (50, "OBJ27"), (100, "OBJ28")])
def test_bahncard_stufe(base_data, stufe, feld):
    base_data["konfiguration_checkboxen"].update(bahncard_privat_vorhanden=True, bahncard_privat_stufe=stufe)
    cb = _build_button_fields(_calc(base_data))
    assert cb.get(feld) == "/Yes"
    assert sum(cb.get(f) == "/Yes" for f in ("OBJ26", "OBJ27", "OBJ28")) == 1


def test_ermaessigungskarte_mit_strecke(base_data):
    base_data["konfiguration_checkboxen"].update(
        ermaessigungskarte_vorhanden=True, ermaessigungskarte_strecke="Lingen – Osnabrück"
    )
    data = _calc(base_data)
    assert _build_button_fields(data).get("OBJ33") == "/Yes"
    assert _build_text_fields(data)["Strecke"] == "Lingen – Osnabrück"


def test_grosskundenrabatt_ohne_bahn_nein_mit_begruendung(base_data):
    base_data["konfiguration_checkboxen"].update(
        grosskundenrabatt_genutzt=True, grosskundenrabatt_begruendung_wenn_nein=""
    )
    data = _calc(base_data)
    cb = _build_button_fields(data)
    assert cb.get("OBJ30") == "/Yes"
    assert "OBJ29" not in cb
    assert "Keine Bahn-/Busfahrt" in _build_text_fields(data)["Begruendung_nein"]


def test_befoerderung_hin_und_rueck_angekreuzt(base_data):
    base_data["befoerderung"]["hinreise"] = {"typ": "BAHN"}
    cb = _build_button_fields(_calc(base_data))
    assert cb.get("OBJ4") == "/Yes"
    assert cb.get("OBJ6") == "/Yes"


def test_amtsspalte_auszahlen_bleibt_leer(base_data):
    cb = _build_button_fields(_calc(base_data))
    assert "OBJ56" not in cb and "OBJ57" not in cb
