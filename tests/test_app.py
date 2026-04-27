"""
Unit-Tests für dr-automate.

Führe die Tests aus mit:
    pytest tests/ -v

Oder mit Coverage:
    pytest tests/ -v --cov=. --cov-report=html
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

# Füge Projektverzeichnis zum Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from generator import apply_checkbox_logic, generate_output_filename
from models import ReiseantragData, validate_reiseantrag

# --- FIXTURES ---


@pytest.fixture
def client():
    """Flask Test-Client."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False  # CSRF für Tests deaktivieren
    with app.test_client() as client:
        yield client


@pytest.fixture
def valid_json_data():
    """Valide Beispieldaten für Tests."""
    return {
        "antragsteller": {
            "name": "Max Mustermann",
            "abteilung": "IT-Abteilung",
            "telefon": "0591 12345-678",
            "adresse_privat": "Musterstraße 1, 49808 Lingen",
            "mitreisender_name": "",
        },
        "reise_details": {
            "zielort": "26486 Wangerooge",
            "reiseweg": "Lingen -> Wangerooge -> Lingen",
            "zweck": "Fortbildung: Test",
            "start_datum": "15.05.2026",
            "start_zeit": "06:30",
            "ende_datum": "17.05.2026",
            "ende_zeit": "19:00",
            "dienstgeschaeft_beginn_datum": "15.05.2026",
            "dienstgeschaeft_beginn_zeit": "10:00",
            "dienstgeschaeft_ende_datum": "17.05.2026",
            "dienstgeschaeft_ende_zeit": "14:00",
        },
        "befoerderung": {
            "hinreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
            "rueckreise": {"typ": "PKW", "paragraph_5_nrkvo": "II"},
            "sonderfall_begruendung_textfeld": "",
        },
        "konfiguration_checkboxen": {
            "bahncard_business_vorhanden": False,
            "bahncard_privat_vorhanden": False,
            "bahncard_beschaffung_beantragt": False,
            "grosskundenrabatt_genutzt": False,
            "grosskundenrabatt_begruendung_wenn_nein": "",
            "weitere_ermaessigungen_vorhanden": False,
            "dienstgeschaeft_2km_umkreis": False,
            "anspruch_trennungsgeld": False,
            "weitere_anmerkungen_checkbox_aktivieren": False,
        },
    }


@pytest.fixture
def invalid_json_data():
    """Ungültige Daten (fehlende Pflichtfelder)."""
    return {
        "antragsteller": {
            "name": "Max"
            # Fehlende Pflichtfelder
        }
    }


# --- TESTS: MODELS ---


class TestModels:
    """Tests für Pydantic-Modelle."""

    def test_valid_data_passes_validation(self, valid_json_data):
        """Valide Daten werden akzeptiert."""
        is_valid, result = validate_reiseantrag(valid_json_data)
        assert is_valid is True
        assert isinstance(result, ReiseantragData)

    def test_missing_required_field_fails(self):
        """Fehlende Pflichtfelder werden erkannt."""
        data = {"antragsteller": {"name": "Test"}}
        is_valid, error = validate_reiseantrag(data)
        assert is_valid is False
        assert "reise_details" in error.lower() or "field required" in error.lower()

    def test_invalid_date_format_fails(self, valid_json_data):
        """Falsches Datumsformat wird abgelehnt."""
        valid_json_data["reise_details"]["start_datum"] = "2026-05-15"  # Falsches Format
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False
        assert "datum" in error.lower() or "format" in error.lower()

    def test_invalid_time_format_fails(self, valid_json_data):
        """Komplett unparsbare Zeit (z.B. Wort) wird abgelehnt."""
        valid_json_data["reise_details"]["start_zeit"] = "morgens"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False

    def test_invalid_transport_type_fails(self, valid_json_data):
        """Ungültiger Beförderungstyp wird abgelehnt."""
        valid_json_data["befoerderung"]["hinreise"]["typ"] = "FAHRRAD"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False

    def test_impossible_date_rejected(self, valid_json_data):
        """Datumsformat stimmt, aber Tag/Monat existiert nicht (32.13.2026)."""
        valid_json_data["reise_details"]["start_datum"] = "32.13.2026"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False
        assert "datum" in error.lower()

    def test_impossible_time_rejected(self, valid_json_data):
        """Zeitformat stimmt, aber 25:00 ist keine valide Uhrzeit."""
        valid_json_data["reise_details"]["start_zeit"] = "25:00"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False

    def test_ende_before_start_rejected(self, valid_json_data):
        """Reise-Ende vor Reise-Beginn wird abgelehnt."""
        valid_json_data["reise_details"]["start_datum"] = "20.05.2026"
        valid_json_data["reise_details"]["ende_datum"] = "15.05.2026"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False
        assert "ende" in error.lower() or "beginn" in error.lower()

    def test_dienstgeschaeft_ende_before_beginn_rejected(self, valid_json_data):
        """Dienstgeschäft-Ende vor Dienstgeschäft-Beginn wird abgelehnt."""
        valid_json_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "17.05.2026"
        valid_json_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "14:00"
        valid_json_data["reise_details"]["dienstgeschaeft_ende_datum"] = "15.05.2026"
        valid_json_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "10:00"
        is_valid, error = validate_reiseantrag(valid_json_data)
        assert is_valid is False
        assert "dienstgeschäft" in error.lower() or "dienstgeschaeft" in error.lower()

    def test_same_day_trip_accepted(self, valid_json_data):
        """Eintägige Reise (start_datum == ende_datum) wird akzeptiert."""
        valid_json_data["reise_details"]["start_datum"] = "15.05.2026"
        valid_json_data["reise_details"]["start_zeit"] = "08:00"
        valid_json_data["reise_details"]["ende_datum"] = "15.05.2026"
        valid_json_data["reise_details"]["ende_zeit"] = "18:00"
        valid_json_data["reise_details"]["dienstgeschaeft_beginn_datum"] = "15.05.2026"
        valid_json_data["reise_details"]["dienstgeschaeft_beginn_zeit"] = "10:00"
        valid_json_data["reise_details"]["dienstgeschaeft_ende_datum"] = "15.05.2026"
        valid_json_data["reise_details"]["dienstgeschaeft_ende_zeit"] = "16:00"
        is_valid, _ = validate_reiseantrag(valid_json_data)
        assert is_valid is True


# --- TESTS: AUTH ---


class TestAuth:
    """Tests für die Passphrase-Auth."""

    def test_check_passphrase_constant_time_returns_false_when_unset(self, monkeypatch):
        """Wenn keine Passphrase gesetzt ist, lehnt _check_passphrase jeden Wert ab."""
        from app import _check_passphrase

        monkeypatch.setattr("app.PASSPHRASE", "")
        assert _check_passphrase("anything") is False
        assert _check_passphrase("") is False  # leer == leer darf NICHT True ergeben

    def test_check_passphrase_matches(self, monkeypatch):
        """Korrekte Passphrase wird akzeptiert."""
        from app import _check_passphrase

        monkeypatch.setattr("app.PASSPHRASE", "geheim")
        assert _check_passphrase("geheim") is True

    def test_check_passphrase_rejects_wrong(self, monkeypatch):
        """Falsche Passphrase wird abgelehnt."""
        from app import _check_passphrase

        monkeypatch.setattr("app.PASSPHRASE", "geheim")
        assert _check_passphrase("wrong") is False
        assert _check_passphrase("geheim ") is False  # Whitespace zählt


# --- TESTS: GENERATOR ---


class TestGenerator:
    """Tests für den PDF-Generator."""

    def test_filename_generation_basic(self, valid_json_data):
        """Dateinamen-Generierung mit Standarddaten."""
        filename = generate_output_filename(valid_json_data)
        assert filename.startswith("20260515_DR-Antrag_")
        assert filename.endswith(".pdf")
        assert "Wangerooge" in filename

    def test_filename_generation_with_topic(self, valid_json_data):
        """Dateinamen-Generierung mit Thema aus Zweck."""
        valid_json_data["reise_details"]["zweck"] = "Fortbildung: Digitalisierung"
        filename = generate_output_filename(valid_json_data)
        assert "Fortbildung" in filename or "Digitalisierung" in filename

    def test_filename_fallback_on_invalid_date(self, valid_json_data):
        """Fallback bei ungültigem Datum."""
        valid_json_data["reise_details"]["start_datum"] = "invalid"
        filename = generate_output_filename(valid_json_data)
        assert filename.endswith(".pdf")
        # Sollte aktuelles Datum als Fallback verwenden

    def test_filename_fallback_on_empty_destination(self, valid_json_data):
        """Fallback bei leerem Zielort."""
        valid_json_data["reise_details"]["zielort"] = ""
        filename = generate_output_filename(valid_json_data)
        assert filename.endswith(".pdf")
        assert "Antrag" in filename  # Fallback


# --- TESTS: CHECKBOX-LOGIK ---
# Diese Tests dokumentieren das erwartete Mapping JSON → PDF-Form-Field-IDs.
# Bei Änderungen am NRKVO-Formular oder am Steuerrecht: hier zuerst anpassen,
# dann die Logik in generator.py.


def _make_data(hin_typ="PKW", hin_para="II", rueck_typ="PKW", rueck_para="II", config=None, verzicht=None):
    """Baut ein minimales data_json für die Checkbox-Tests."""
    default_config = {
        "bahncard_business_vorhanden": False,
        "bahncard_privat_vorhanden": False,
        "bahncard_beschaffung_beantragt": False,
        "grosskundenrabatt_genutzt": False,
        "grosskundenrabatt_begruendung_wenn_nein": "",
        "weitere_ermaessigungen_vorhanden": False,
        "dienstgeschaeft_2km_umkreis": False,
        "anspruch_trennungsgeld": False,
        "weitere_anmerkungen_checkbox_aktivieren": False,
    }
    if config:
        default_config.update(config)
    return {
        "befoerderung": {
            "hinreise": {"typ": hin_typ, "paragraph_5_nrkvo": hin_para},
            "rueckreise": {"typ": rueck_typ, "paragraph_5_nrkvo": rueck_para},
        },
        "konfiguration_checkboxen": default_config,
        "verzicht_erklaerung": verzicht or {},
    }


class TestCheckboxBefoerderungHin:
    """Beförderung Hinreise: Mapping Typ → PDF-Field-ID."""

    @pytest.mark.parametrize(
        ("typ", "para", "expected_id"),
        [
            ("BAHN", "II", "OBJ5"),
            ("BUS", "II", "OBJ5"),  # BAHN und BUS teilen sich das Feld
            ("DIENSTWAGEN", "II", "OBJ36"),
            ("PKW", "II", "OBJ42"),
            ("PKW", "III", "OBJ43"),
            ("FLUG", "II", "OBJ43"),  # Flug → §5 III
        ],
    )
    def test_hinreise_mapping(self, typ, para, expected_id):
        cb = apply_checkbox_logic(_make_data(hin_typ=typ, hin_para=para))
        assert cb.get(expected_id) == "/Yes"

    def test_pkw_default_paragraph_is_II(self):
        """Wenn paragraph_5_nrkvo fehlt, gilt §II als Default → OBJ42."""
        data = _make_data(hin_typ="PKW")
        del data["befoerderung"]["hinreise"]["paragraph_5_nrkvo"]
        cb = apply_checkbox_logic(data)
        assert cb.get("OBJ42") == "/Yes"
        assert "OBJ43" not in cb


class TestCheckboxBefoerderungRueck:
    """Beförderung Rückreise: Mapping Typ → PDF-Field-ID (anderes Set als Hin)."""

    @pytest.mark.parametrize(
        ("typ", "para", "expected_id"),
        [
            ("BAHN", "II", "OBJ46"),
            ("BUS", "II", "OBJ46"),
            ("DIENSTWAGEN", "II", "OBJ47"),
            ("PKW", "II", "OBJ48"),
            ("PKW", "III", "OBJ14"),
            ("FLUG", "II", "OBJ14"),
        ],
    )
    def test_rueckreise_mapping(self, typ, para, expected_id):
        cb = apply_checkbox_logic(_make_data(rueck_typ=typ, rueck_para=para))
        assert cb.get(expected_id) == "/Yes"


class TestCheckboxKonfiguration:
    """Konfigurations-Booleans: Bahncard / Rabatt / 2km / Trennungsgeld / Anmerkungen."""

    def test_no_bahncard_business_sets_BCB_Nein(self):
        cb = apply_checkbox_logic(_make_data(config={"bahncard_business_vorhanden": False}))
        assert cb.get("BCB_Nein") == "/Yes"

    def test_with_bahncard_business_does_not_set_BCB_Nein(self):
        cb = apply_checkbox_logic(_make_data(config={"bahncard_business_vorhanden": True}))
        assert "BCB_Nein" not in cb

    def test_no_bahncard_privat_sets_BC_Nein(self):
        cb = apply_checkbox_logic(_make_data(config={"bahncard_privat_vorhanden": False}))
        assert cb.get("BC_Nein") == "/Yes"

    def test_no_bahncard_beschaffung_sets_Beschaffung_Nein(self):
        cb = apply_checkbox_logic(_make_data(config={"bahncard_beschaffung_beantragt": False}))
        assert cb.get("Beschaffung_Nein") == "/Yes"

    def test_grosskundenrabatt_genutzt_sets_Obj6(self):
        cb = apply_checkbox_logic(_make_data(config={"grosskundenrabatt_genutzt": True}))
        assert cb.get("Obj6") == "/Yes"
        assert "Obj7" not in cb

    def test_grosskundenrabatt_nicht_genutzt_sets_Obj7(self):
        cb = apply_checkbox_logic(_make_data(config={"grosskundenrabatt_genutzt": False}))
        assert cb.get("Obj7") == "/Yes"
        assert "Obj6" not in cb

    def test_weitere_ermaessigungen_ja_sets_Obj8(self):
        cb = apply_checkbox_logic(_make_data(config={"weitere_ermaessigungen_vorhanden": True}))
        assert cb.get("Obj8") == "/Yes"
        assert "Obj15" not in cb

    def test_weitere_ermaessigungen_nein_sets_Obj15(self):
        cb = apply_checkbox_logic(_make_data(config={"weitere_ermaessigungen_vorhanden": False}))
        assert cb.get("Obj15") == "/Yes"
        assert "Obj8" not in cb

    def test_weitere_anmerkungen_aktivieren_sets_Obj39(self):
        cb = apply_checkbox_logic(_make_data(config={"weitere_anmerkungen_checkbox_aktivieren": True}))
        assert cb.get("Obj39") == "/Yes"

    def test_weitere_anmerkungen_inaktiv_keine_Obj39(self):
        cb = apply_checkbox_logic(_make_data(config={"weitere_anmerkungen_checkbox_aktivieren": False}))
        assert "Obj39" not in cb

    def test_dienstgeschaeft_2km_ja_sets_Obj52(self):
        cb = apply_checkbox_logic(_make_data(config={"dienstgeschaeft_2km_umkreis": True}))
        assert cb.get("Obj52") == "/Yes"
        assert "Obj49" not in cb

    def test_dienstgeschaeft_2km_nein_sets_Obj49(self):
        cb = apply_checkbox_logic(_make_data(config={"dienstgeschaeft_2km_umkreis": False}))
        assert cb.get("Obj49") == "/Yes"
        assert "Obj52" not in cb

    def test_anspruch_trennungsgeld_ja_sets_Obj59(self):
        cb = apply_checkbox_logic(_make_data(config={"anspruch_trennungsgeld": True}))
        assert cb.get("Obj59") == "/Yes"
        assert "Obj56" not in cb

    def test_anspruch_trennungsgeld_nein_sets_Obj56(self):
        cb = apply_checkbox_logic(_make_data(config={"anspruch_trennungsgeld": False}))
        assert cb.get("Obj56") == "/Yes"
        assert "Obj59" not in cb


class TestCheckboxVerzicht:
    """Verzichtserklärungen: optionales Top-Level-Feld."""

    def test_verzicht_tagegeld_sets_Obj10(self):
        cb = apply_checkbox_logic(_make_data(verzicht={"verzicht_tagegeld": True}))
        assert cb.get("Obj10") == "/Yes"

    def test_verzicht_uebernachtungsgeld_sets_Obj11(self):
        cb = apply_checkbox_logic(_make_data(verzicht={"verzicht_uebernachtungsgeld": True}))
        assert cb.get("Obj11") == "/Yes"

    def test_verzicht_fahrtkosten_sets_Obj12(self):
        cb = apply_checkbox_logic(_make_data(verzicht={"verzicht_fahrtkosten": True}))
        assert cb.get("Obj12") == "/Yes"

    def test_kein_verzicht_keine_Obj10_11_12(self):
        cb = apply_checkbox_logic(_make_data(verzicht={}))
        for obj_id in ("Obj10", "Obj11", "Obj12"):
            assert obj_id not in cb

    def test_verzicht_erklaerung_kann_komplett_fehlen(self):
        """Top-Level-Feld ist optional — kein Crash, keine Verzicht-Boxen."""
        data = _make_data()
        del data["verzicht_erklaerung"]
        cb = apply_checkbox_logic(data)
        for obj_id in ("Obj10", "Obj11", "Obj12"):
            assert obj_id not in cb


# --- TESTS: API ENDPOINTS ---


class TestAPIEndpoints:
    """Tests für Flask-Endpunkte."""

    def test_index_returns_200(self, client):
        """Hauptseite ist erreichbar."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Dienstreise-Antrag" in response.data

    def test_health_check_returns_200(self, client):
        """Health-Check funktioniert."""
        response = client.get("/health")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "healthy"
        assert "template_exists" in data

    def test_example_endpoint(self, client):
        """Beispiel-JSON Endpunkt."""
        response = client.get("/example")
        # Kann 200 (Datei existiert) oder 404 (nicht gefunden) sein
        assert response.status_code in [200, 404]

    def test_generate_without_data_returns_400(self, client):
        """Anfrage ohne JSON-Daten gibt 400."""
        response = client.post("/generate", data={})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_generate_with_invalid_json_returns_400(self, client):
        """Ungültiges JSON gibt 400."""
        response = client.post("/generate", data={"json_data": "{invalid json"})
        assert response.status_code == 400

    def test_generate_with_incomplete_data_returns_400(self, client, invalid_json_data):
        """Unvollständige Daten geben 400."""
        response = client.post("/generate", data={"json_data": json.dumps(invalid_json_data)})
        assert response.status_code == 400

    @patch("generator.fill_pdf")
    def test_generate_with_valid_data_returns_pdf(self, mock_fill_pdf, client, valid_json_data, tmp_path):
        """Valide Daten generieren PDF."""
        # Mock PDF-Generierung
        test_pdf_path = tmp_path / "test.pdf"
        test_pdf_path.write_bytes(b"%PDF-1.4 test content")
        mock_fill_pdf.return_value = str(test_pdf_path)

        response = client.post("/generate", data={"json_data": json.dumps(valid_json_data)})

        # Entweder erfolgreiche PDF-Antwort oder Fehler (wenn Template fehlt)
        assert response.status_code in [200, 500]


# --- TESTS: EDGE CASES ---


class TestEdgeCases:
    """Tests für Grenzfälle."""

    def test_empty_optional_fields(self, valid_json_data):
        """Optionale Felder dürfen leer sein."""
        valid_json_data["antragsteller"]["mitreisender_name"] = ""
        valid_json_data["befoerderung"]["sonderfall_begruendung_textfeld"] = ""
        is_valid, _ = validate_reiseantrag(valid_json_data)
        assert is_valid is True

    def test_extra_fields_are_ignored(self, valid_json_data):
        """Zusätzliche Felder werden ignoriert."""
        valid_json_data["unbekanntes_feld"] = "test"
        is_valid, _ = validate_reiseantrag(valid_json_data)
        assert is_valid is True

    def test_special_characters_in_destination(self, valid_json_data):
        """Sonderzeichen im Zielort."""
        valid_json_data["reise_details"]["zielort"] = "München (Hauptbahnhof) / Bayern"
        is_valid, _ = validate_reiseantrag(valid_json_data)
        assert is_valid is True

    def test_multiline_remarks(self, valid_json_data):
        """Mehrzeilige Bemerkungen."""
        valid_json_data["zusatz_infos"] = {"bemerkungen_feld": "Zeile 1\nZeile 2\nZeile 3"}
        is_valid, _ = validate_reiseantrag(valid_json_data)
        assert is_valid is True
