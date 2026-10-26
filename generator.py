import io
import json
import logging
import os
import re
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# --- LOGGING ---
logger = logging.getLogger(__name__)

# --- KONFIGURATION ---
# Unterschrift-Position (X, Y auf Seite 2)
SIGNATURE_POSITION_X = 70
SIGNATURE_POSITION_Y = 465
SIGNATURE_FONT = "Helvetica"
SIGNATURE_FONT_SIZE = 10

# Datumsformate
DATE_INPUT_FORMAT = "%d.%m.%Y"
DATE_OUTPUT_FORMAT = "%Y%m%d"

# --- MAPPING TEXTFELDER ---
FIELD_MAPPING = {
    # Kopfdaten
    "antragsteller.name": "Person.Name1",
    "antragsteller.abteilung": "Person.Orga1",
    "antragsteller.telefon": "Person.Telefon1",
    "antragsteller.adresse_privat": ["Abfahrtsort", "RueckkehrNach"],
    # Reise
    "reise_details.zielort": "Reiseziel",
    "reise_details.reiseweg": "Reiseweg",
    "reise_details.zweck": "Begruendung",
    # Zeiten
    "reise_details.start_datum": "Datum",
    "reise_details.start_zeit": "Uhrzeit1",
    "reise_details.dienstgeschaeft_beginn_datum": "Datum3",
    "reise_details.dienstgeschaeft_beginn_zeit": "Uhrzeit3",
    "reise_details.dienstgeschaeft_ende_datum": "Datum2",
    "reise_details.dienstgeschaeft_ende_zeit": "Uhrzeit2",
    "reise_details.ende_datum": "Datum4",
    "reise_details.ende_zeit": "Uhrzeit4",
    # Begründung Pkw
    "befoerderung.sonderfall_begruendung_textfeld": "Begruendung2",
    # Mitfahrer-Name pro Reise-Richtung (nur relevant bei typ=MITFAHRT)
    "befoerderung.hinreise.mitfahrer_name": "Mitfahrt_bei",
    "befoerderung.rueckreise.mitfahrer_name": "Mitfahrt_bei1",
    # Begründung kein Rabatt
    "konfiguration_checkboxen.grosskundenrabatt_begruendung_wenn_nein": "Begruendung3",
    # Ermäßigungskarte "Ja, und zwar für die Strecke" (neben OBJ57)
    "konfiguration_checkboxen.ermaessigungskarte_strecke": "Strecke",
    # BahnCard-Beschaffung "Ja, und zwar" — genaue Angabe der Karte (neben Beschaffung_Ja)
    "konfiguration_checkboxen.bahncard_beschaffung_karte": "Karte",
    # BEIDE Varianten des Feldes füllen
    "zusatz_infos.bemerkungen_feld": [
        "Bemerkungen_der_anstragstellenden_Person",
        "Bemerkungen_der_anstragstellenden_Person1",
    ],
    "CLEAR_DIENSTWAGEN": ["Genaue_Abfahrtsanschrift", "Genaue_Ankunftsanschrift"],
}


# Slots „ggf. Angabe weiterer teilnehmender Personen" im Vordruck.
_TEILNEHMER_SLOTS = (
    ("Person.Name2", "Person.Orga2", "Person.Telefon2"),
    ("Person.Name3", "Person.Orga3", "Person.Telefon3"),
    ("Person.Name4", "Person.Orga4", "Person.Telefon4"),
)


def teilnehmer_liste(data: dict) -> list[tuple[str, str, str]]:
    """Alle weiteren teilnehmenden Personen als (Name, Dienststelle, Telefon).

    Quellen (in dieser Reihenfolge, nach Name dedupliziert):
    1. ``reise_details.weitere_teilnehmer`` — reise-spezifisch aus KI/Wizard,
       mit Dienststelle/Telefon.
    2. ``antragsteller.mitreisender_name`` — Profil-Default („Mitreisende",
       mehrere mit Komma), nur Name.
    """
    personen: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def _add(name: str, orga: str = "", tel: str = "") -> None:
        name = (name or "").strip()
        key = name.casefold()
        if not name or key in seen:
            return
        seen.add(key)
        personen.append((name, (orga or "").strip(), (tel or "").strip()))

    for t in (data.get("reise_details") or {}).get("weitere_teilnehmer") or []:
        if isinstance(t, dict):
            _add(t.get("name", ""), t.get("dienststelle", ""), t.get("telefon", ""))
    for name in re.split(r"[,;]", (data.get("antragsteller") or {}).get("mitreisender_name") or ""):
        _add(name)
    return personen


def teilnehmer_fields(data: dict) -> dict:
    """Weitere teilnehmende Personen auf Person.Name2–4 / Orga2–4 / Telefon2–4
    mappen. Mehr als drei passen nicht in den Vordruck — die übrigen schreibt
    ``fill_pdf`` in die Bemerkungen (``teilnehmer_ueberzaehlig``)."""
    fields: dict[str, str] = {}
    for (f_name, f_orga, f_tel), (name, orga, tel) in zip(_TEILNEHMER_SLOTS, teilnehmer_liste(data), strict=False):
        fields[f_name] = name
        fields[f_orga] = orga
        fields[f_tel] = tel
    return fields


def teilnehmer_ueberzaehlig(data: dict) -> list[str]:
    """Namen, die nicht mehr in die drei Vordruck-Zeilen passen."""
    return [name for name, _, _ in teilnehmer_liste(data)[len(_TEILNEHMER_SLOTS) :]]


def load_json_data(filepath):
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def create_signature_overlay(text_str: str) -> PdfReader:
    """Erstellt ein PDF-Overlay mit dem Unterschriftstext.

    Args:
        text_str: Der Text für die Unterschrift (Name, Datum)

    Returns:
        PdfReader mit dem Overlay
    """
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)

    can.setFont(SIGNATURE_FONT, SIGNATURE_FONT_SIZE)
    can.drawString(SIGNATURE_POSITION_X, SIGNATURE_POSITION_Y, text_str)

    can.save()
    packet.seek(0)
    return PdfReader(packet)


def _checkbox_befoerderung(trans: dict) -> dict:
    """Hin-/Rückreise-Typ auf PDF-Field-IDs mappen.

    Formular-Spalten (x-Position): 114=Bahn/Bus, 156=Dienstwagen,
    213=PKW §II, 336=PKW §III, 430=Mitfahrt, 492=sonstiges Beförderungsmittel.
    Hin und Rück haben jeweils eigene Field-IDs. Flug ist „sonstiges
    Beförderungsmittel" (OBJ45/OBJ51, Begründungspflicht über Begruendung2) —
    bis 2026-10 wurde fälschlich „privater PKW § 5 III" angekreuzt.
    """
    cb = {}

    hin_typ = trans["hinreise"]["typ"].upper()
    hin_para = trans["hinreise"].get("paragraph_5_nrkvo", "II")
    if hin_typ in ("BAHN", "BUS"):
        cb["OBJ5"] = "/Yes"
    elif hin_typ == "DIENSTWAGEN":
        cb["OBJ36"] = "/Yes"
    elif hin_typ == "PKW":
        cb["OBJ43" if hin_para == "III" else "OBJ42"] = "/Yes"
    elif hin_typ == "FLUG":
        cb["OBJ45"] = "/Yes"
    elif hin_typ == "MITFAHRT":
        cb["OBJ44"] = "/Yes"  # eigene Mitfahrt-Box im Antrag

    rueck_typ = trans["rueckreise"]["typ"].upper()
    rueck_para = trans["rueckreise"].get("paragraph_5_nrkvo", "II")
    if rueck_typ in ("BAHN", "BUS"):
        cb["OBJ46"] = "/Yes"
    elif rueck_typ == "DIENSTWAGEN":
        cb["OBJ47"] = "/Yes"
    elif rueck_typ == "PKW":
        cb["OBJ14" if rueck_para == "III" else "OBJ48"] = "/Yes"
    elif rueck_typ == "FLUG":
        cb["OBJ51"] = "/Yes"
    elif rueck_typ == "MITFAHRT":
        cb["OBJ50"] = "/Yes"  # eigene Mitfahrt-Box im Antrag

    return cb


_BAHN_TYPEN = ("BAHN", "BUS")

# Klartext-Label je Verkehrsmittel für die automatische Großkundenrabatt-
# Begründung (Begruendung3), wenn die Reise keine Bahn-/Busfahrt enthält.
_VERKEHRSMITTEL_TEXT = {
    "PKW": "privatem Pkw",
    "DIENSTWAGEN": "Dienst-Kfz",
    "MITFAHRT": "Mitfahrt im Pkw",
    "FLUG": "Flugzeug",
}


def hat_bahn(befoerderung: dict | None) -> bool:
    """True, wenn Hin- oder Rückreise per Bahn/Bus erfolgt."""
    if not befoerderung:
        return False
    hin = (befoerderung.get("hinreise") or {}).get("typ", "").upper()
    rueck = (befoerderung.get("rueckreise") or {}).get("typ", "").upper()
    return hin in _BAHN_TYPEN or rueck in _BAHN_TYPEN


def grosskundenrabatt_begruendung(data: dict) -> str:
    """Text für Begruendung3 („Großkundenrabatt: Nein — bitte Begründung").

    Der Nutzer-Text gewinnt immer. Ohne Bahn-/Busfahrt wird die Frage
    „Für diese Reise wird der Großkundenrabatt genutzt" immer mit „Nein"
    beantwortet (siehe ``_checkbox_konfiguration``) und der sachliche Grund
    aus der Verkehrsmittel-Wahl abgeleitet — der Vordruck verlangt bei „Nein"
    eine Begründung, und ohne Bahnfahrt ist „kein Bahnticket" die einzig
    richtige. Bei Bahnreise ohne Rabatt bleibt das Feld leer (echte
    Begründungspflicht des Nutzers, nichts erfinden).
    """
    config = data.get("konfiguration_checkboxen") or {}
    eigen = (config.get("grosskundenrabatt_begruendung_wenn_nein") or "").strip()
    befoerderung = data.get("befoerderung") or {}
    if eigen or hat_bahn(befoerderung):
        # Bahnreise: „Ja" braucht keine Begründung, „Nein" ist Nutzersache.
        return eigen
    hin = (befoerderung.get("hinreise") or {}).get("typ", "").upper()
    rueck = (befoerderung.get("rueckreise") or {}).get("typ", "").upper()
    if not hin and not rueck:
        return ""
    hin_txt = _VERKEHRSMITTEL_TEXT.get(hin, hin.title())
    rueck_txt = _VERKEHRSMITTEL_TEXT.get(rueck, rueck.title())
    if hin == rueck:
        return f"Keine Bahn-/Busfahrt: Hin- und Rückreise mit {hin_txt}."
    return f"Keine Bahn-/Busfahrt: Hinreise mit {hin_txt}, Rückreise mit {rueck_txt}."


def _checkbox_konfiguration(config: dict, befoerderung: dict | None = None) -> dict:
    """Konfigurations-Booleans auf PDF-Field-IDs mappen.

    Die Bahn-Sektion (BahnCard Business / BahnCard / Beschaffung /
    Ermäßigungskarte, im Vordruck „Bitte immer ausfüllen") und die
    Großkundenrabatt-Frage („Bitte immer beantworten!") werden **unabhängig
    vom Verkehrsmittel** beantwortet — auch bei reinen PKW-/Mitfahrt-/Flug-/
    Dienstwagen-Reisen. Bis 2026-09 blieb die Sektion bei Reisen ohne
    Bahn/Bus leer (issues.md #3) und der Antrag kam von der Schulleitung
    als „unvollständig" zurück. Die Werte kommen aus dem Nutzerprofil
    (``apply_profile_authoritative``), Default ist überall „Nein".

    ``befoerderung`` steuert nur noch die reisebezogene Großkundenrabatt-Frage.
    """
    cb = {}

    cb["BCB_Ja" if config["bahncard_business_vorhanden"] else "BCB_Nein"] = "/Yes"
    if config["bahncard_privat_vorhanden"]:
        cb["BC_Ja"] = "/Yes"
        stufe = config.get("bahncard_privat_stufe")
        if stufe in (25, 50, 100):
            cb[f"BC{stufe}"] = "/Yes"
    else:
        cb["BC_Nein"] = "/Yes"
    cb["Beschaffung_Ja" if config["bahncard_beschaffung_beantragt"] else "Beschaffung_Nein"] = "/Yes"
    # Großkundenrabatt: Obj6=Ja, Obj7=Nein. Die Frage ist reisebezogen („Für
    # diese Reise …") — ohne Bahn-/Busfahrt wird kein Ticket gekauft, also
    # „Nein", egal was das Profil sagt; grosskundenrabatt_begruendung()
    # liefert dann die Pflicht-Begründung für Begruendung3.
    genutzt = bool(config["grosskundenrabatt_genutzt"]) and hat_bahn(befoerderung)
    cb["Obj6" if genutzt else "Obj7"] = "/Yes"
    # Ermaeßigungskarte (Monats-/Zeitkarte): OBJ57=Ja ("und zwar fuer die
    # Strecke", Textfeld via FIELD_MAPPING), OBJ58=Nein.
    cb["OBJ57" if config.get("ermaessigungskarte_vorhanden") else "OBJ58"] = "/Yes"

    # Weitere Ermaeßigungen (außer BahnCards/Ermaeßigungskarten/Großkunden-
    # rabatt): Obj15=Ja, Obj8=Nein laut Feld-Tooltips im Vordruck — die
    # Zuordnung war bis 2026-08 vertauscht (Default landete auf "Ja").
    cb["Obj15" if config["weitere_ermaessigungen_vorhanden"] else "Obj8"] = "/Yes"
    cb["Obj52" if config["dienstgeschaeft_2km_umkreis"] else "Obj49"] = "/Yes"
    cb["Obj59" if config["anspruch_trennungsgeld"] else "Obj56"] = "/Yes"

    # Obj55: "Die Reisekosten werden von einer anderen Person oder Stelle
    # uebernommen" — nur echte Kostenuebernahme durch Dritte, nicht die selbst
    # gezahlte Tagungsgebuehr inkl. Uebernachtung/Verpflegung (siehe
    # system_prompt.md). Obj53/Obj54 daneben waeren unentgeltliche Unterkunft/
    # Verpflegung des Amtes wegen — bis 2026-08 wurde faelschlich Obj53 gesetzt.
    if config.get("kosten_durch_andere_stelle"):
        cb["Obj55"] = "/Yes"

    if config.get("weitere_anmerkungen_checkbox_aktivieren"):
        cb["Obj39"] = "/Yes"

    return cb


def _checkbox_verzicht(verzicht: dict) -> dict:
    """Optionale Verzichtserklärungen auf PDF-Field-IDs mappen."""
    cb = {}
    if verzicht.get("verzicht_tagegeld"):
        cb["Obj10"] = "/Yes"
    if verzicht.get("verzicht_uebernachtungsgeld"):
        cb["Obj11"] = "/Yes"
    if verzicht.get("verzicht_fahrtkosten"):
        cb["Obj12"] = "/Yes"
    return cb


def apply_checkbox_logic(data_json: dict) -> dict:
    """Aggregiert alle Checkbox-Felder aus Beförderung, Konfiguration und Verzicht."""
    return {
        **_checkbox_befoerderung(data_json["befoerderung"]),
        **_checkbox_konfiguration(
            data_json["konfiguration_checkboxen"],
            data_json.get("befoerderung"),
        ),
        **_checkbox_verzicht(data_json.get("verzicht_erklaerung", {})),
    }


def set_need_appearances(writer):
    """Setzt /NeedAppearances=True im AcroForm, damit Viewer Formularfelder neu rendern.

    Best-effort: schlägt das Setzen fehl (z.B. weil das Template kein AcroForm hat oder
    die pypdf-Variante des Objekts unerwartet ist), wird nur eine Warnung geloggt — das
    PDF ist trotzdem korrekt befüllt, die Felder erscheinen je nach Viewer ggf. erst
    nach einer User-Aktion.
    """
    catalog = writer._root_object
    if "/AcroForm" not in catalog:
        logger.warning("PDF-Template hat kein /AcroForm — NeedAppearances wird nicht gesetzt.")
        return
    try:
        # /AcroForm liefert oft einen IndirectObject — vor dem Schreiben dereferenzieren.
        acroform = catalog["/AcroForm"]
        if hasattr(acroform, "get_object"):
            acroform = acroform.get_object()
        acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
    except Exception as e:
        logger.warning(f"NeedAppearances konnte nicht gesetzt werden: {e}")


def generate_output_filename(data: dict) -> str:
    """Generiert den Dateinamen basierend auf den JSON-Daten.

    Format: YYYYMMDD_DR-Antrag_Stadt_Thema.pdf

    Args:
        data: Die JSON-Daten mit Reiseinformationen

    Returns:
        Bereinigter Dateiname für das PDF
    """
    # 1. Datum für Prefix (YYYYMMDD)
    start_datum_str = data.get("reise_details", {}).get("start_datum", "")
    try:
        date_obj = datetime.strptime(start_datum_str, DATE_INPUT_FORMAT)
        date_prefix = date_obj.strftime(DATE_OUTPUT_FORMAT)
    except ValueError:
        logger.warning(f"Ungültiges Datum '{start_datum_str}', verwende aktuelles Datum")
        date_prefix = datetime.now().strftime(DATE_OUTPUT_FORMAT)

    # 2. Suffix aus Zielort (Stadt)
    zielort = data.get("reise_details", {}).get("zielort", "Reise")
    # Versuch: PLZ und Stadt finden (z.B. "26486 Wangerooge")
    match = re.search(r"\d{5}\s+([A-Za-zäöüÄÖÜß\s\-]+)", zielort)
    if match:
        # Wenn gefunden, nimm den Städtenamen
        city_suffix = match.group(1).strip()
    else:
        # Sonst nimm simplen String
        city_suffix = zielort

    # 3. Inhaltliches Stichwort aus Zweck
    zweck = data.get("reise_details", {}).get("zweck", "")
    topic_suffix = ""
    if zweck:
        # Falls Doppelpunkt (z.B. "Fortbildung: Thema"), nimm Teil danach
        if ":" in zweck:
            parts = zweck.split(":", 1)
            remaining = parts[1].strip() if len(parts) > 1 else parts[0]
        else:
            remaining = zweck

        # Nimm das erste Wort
        words = remaining.split()
        if words:
            topic_suffix = words[0]

    # Zusammenbauen: Stadt_Thema
    raw_suffix = f"{city_suffix}"
    if topic_suffix:
        raw_suffix += f"_{topic_suffix}"

    # Bereinigen für Dateinamen
    clean_suffix = re.sub(r"[^A-Za-z0-9äöüÄÖÜß_]", "_", raw_suffix)
    clean_suffix = re.sub(r"_+", "_", clean_suffix).strip("_")

    # Fallback wenn Suffix leer ist
    if not clean_suffix:
        clean_suffix = "Antrag"

    return f"{date_prefix}_DR-Antrag_{clean_suffix}.pdf"


def fill_pdf(json_input: dict | str, input_pdf_path: str, output_dir: str) -> str:
    """Füllt das PDF-Formular mit den übergebenen Daten.

    Args:
        json_input: Entweder ein dict mit Daten oder Pfad zu einer JSON-Datei
        input_pdf_path: Pfad zum PDF-Template
        output_dir: Ausgabeverzeichnis für das generierte PDF

    Returns:
        Pfad zur generierten PDF-Datei

    Raises:
        FileNotFoundError: Wenn das Template nicht gefunden wird
        ValueError: Bei ungültigen JSON-Daten
    """
    try:
        if isinstance(json_input, str):
            data = load_json_data(json_input)
        else:
            data = json_input

        # Stelle sicher, dass Ausgabeverzeichnis existiert
        os.makedirs(output_dir, exist_ok=True)

        output_filename = generate_output_filename(data)
        output_pdf_path = os.path.join(output_dir, output_filename)

        writer = PdfWriter(clone_from=input_pdf_path)

        # 1. Textfelder
        fields_to_fill = {}
        for json_key, pdf_id in FIELD_MAPPING.items():
            if json_key == "CLEAR_DIENSTWAGEN":
                for pid in pdf_id:
                    fields_to_fill[pid] = ""
                continue

            keys = json_key.split(".")
            value = data
            for k in keys:
                value = value.get(k, {})
                if value is None:
                    break

            if isinstance(value, (str, int)):
                if isinstance(value, str):
                    # PDF-Formularfelder nutzen \r als Zeilenumbruch (PDF-Spec ISO 32000).
                    # LLMs geben manchmal literal \\n (zwei Zeichen) aus → ebenfalls ersetzen.
                    value = value.replace("\r\n", "\r").replace("\\n", "\r").replace("\n", "\r")
                if isinstance(pdf_id, list):
                    for pid in pdf_id:
                        fields_to_fill[pid] = value
                else:
                    fields_to_fill[pdf_id] = value

        # 1a. Weitere teilnehmende Personen (Slots 2–4); Überzählige in die
        # Bemerkungen statt still zu verschwinden.
        fields_to_fill.update(teilnehmer_fields(data))
        ueberzaehlig = teilnehmer_ueberzaehlig(data)
        if ueberzaehlig:
            zeile = "Weitere Teilnehmende: " + ", ".join(ueberzaehlig)
            for pid in FIELD_MAPPING["zusatz_infos.bemerkungen_feld"]:
                bisher = fields_to_fill.get(pid) or ""
                fields_to_fill[pid] = f"{bisher}\r{zeile}" if bisher else zeile

        # 1b. Großkundenrabatt-Begründung: Nutzer-Text oder abgeleiteter
        # Grund bei „Nein" ohne Bahnfahrt (Vordruck verlangt eine Begründung).
        fields_to_fill["Begruendung3"] = grosskundenrabatt_begruendung(data).replace("\n", "\r")

        # 2. Checkboxen
        checkbox_fields = apply_checkbox_logic(data)
        if ueberzaehlig:
            checkbox_fields["Obj39"] = "/Yes"  # „Weitere Anmerkungen"

        # 3. Anwenden
        all_fields = {**fields_to_fill, **checkbox_fields}

        # Iteriere über alle Seiten, um sicherzustellen, dass Felder auf Seite 2 (z.B. Obj39, Bemerkungen) auch gefüllt werden
        for page in writer.pages:
            writer.update_page_form_field_values(page, all_fields, auto_regenerate=False)

        set_need_appearances(writer)

        # 4. Unterschrift / Datum auf Seite 2
        heute_str = datetime.now().strftime(DATE_INPUT_FORMAT)
        name = data.get("antragsteller", {}).get("name", "")
        unterschrift_text = f"{name}, {heute_str}"

        overlay = create_signature_overlay(unterschrift_text)
        writer.pages[1].merge_page(overlay.pages[0], over=True)

        with open(output_pdf_path, "wb") as f:
            writer.write(f)

        logger.info(f"PDF erstellt: {output_pdf_path}")
        logger.debug(
            f"Unterschrift: '{unterschrift_text}' an Position ({SIGNATURE_POSITION_X}, {SIGNATURE_POSITION_Y})"
        )

        return output_pdf_path

    except FileNotFoundError:
        logger.error(f"Template nicht gefunden: {input_pdf_path}")
        raise
    except Exception as e:
        logger.exception(f"Fehler bei PDF-Generierung: {e}")
        raise
