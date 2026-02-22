import json
import os
import io
import re
import logging
from datetime import datetime
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

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
    "antragsteller.mitreisender_name": "Person.Name2",
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

    # Begründung kein Rabatt
    "konfiguration_checkboxen.grosskundenrabatt_begruendung_wenn_nein": "Begruendung3",

    # BEIDE Varianten des Feldes füllen
    "zusatz_infos.bemerkungen_feld": [
        "Bemerkungen_der_anstragstellenden_Person",
        "Bemerkungen_der_anstragstellenden_Person1"
    ],

    "CLEAR_DIENSTWAGEN": ["Genaue_Abfahrtsanschrift", "Genaue_Ankunftsanschrift"]
}

def load_json_data(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
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

def apply_checkbox_logic(data_json):
    cb = {}
    config = data_json["konfiguration_checkboxen"]
    trans = data_json["befoerderung"]
    verzicht = data_json.get("verzicht_erklaerung", {})

    # 1. BEFÖRDERUNG
    hin_typ = trans["hinreise"]["typ"].upper()
    hin_para = trans["hinreise"].get("paragraph_5_nrkvo", "II")

    if "PKW" in hin_typ:
        if hin_para == "III":
            cb["OBJ43"] = "/Yes"
        else:
            cb["OBJ42"] = "/Yes"

    rueck_typ = trans["rueckreise"]["typ"].upper()
    rueck_para = trans["rueckreise"].get("paragraph_5_nrkvo", "II")

    if "PKW" in rueck_typ:
        if rueck_para == "III":
            cb["OBJ14"] = "/Yes"
        else:
            cb["OBJ48"] = "/Yes"

    # 2. CHECKBOXEN
    if not config["bahncard_business_vorhanden"]: cb["BCB_Nein"] = "/Yes"
    if not config["bahncard_privat_vorhanden"]: cb["BC_Nein"] = "/Yes"
    if not config["bahncard_beschaffung_beantragt"]: cb["Beschaffung_Nein"] = "/Yes"

    if config["grosskundenrabatt_genutzt"]:
        cb["Obj6"] = "/Yes"
    else:
        cb["Obj7"] = "/Yes"

    if config["weitere_ermaessigungen_vorhanden"]:
        cb["Obj8"] = "/Yes"
    else:
        cb["Obj15"] = "/Yes"

    if config.get("weitere_anmerkungen_checkbox_aktivieren"):
        cb["Obj39"] = "/Yes"

    # 3. SONSTIGES
    if config["dienstgeschaeft_2km_umkreis"]: cb["Obj52"] = "/Yes"
    else: cb["Obj49"] = "/Yes"

    if config["anspruch_trennungsgeld"]: cb["Obj59"] = "/Yes"
    else: cb["Obj56"] = "/Yes"

    if verzicht.get("verzicht_tagegeld"): cb["Obj10"] = "/Yes"
    if verzicht.get("verzicht_uebernachtungsgeld"): cb["Obj11"] = "/Yes"
    if verzicht.get("verzicht_fahrtkosten"): cb["Obj12"] = "/Yes"

    return cb

def set_need_appearances(writer):
    """Zwingt den PDF-Viewer, Formularfelder neu zu rendern."""
    try:
        catalog = writer._root_object
        if "/AcroForm" not in catalog:
            writer._root_object.update({
                NameObject("/AcroForm"): writer._objects[len(writer._objects)-1]
            })

        acroform = catalog["/AcroForm"]
        if "/NeedAppearances" not in acroform:
            acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
        else:
            acroform["/NeedAppearances"] = BooleanObject(True)

    except Exception as e:
        print(f"Warnung bei NeedAppearances: {e}")

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
                for pid in pdf_id: fields_to_fill[pid] = ""
                continue

            keys = json_key.split('.')
            value = data
            for k in keys:
                value = value.get(k, {})
                if value is None: break

            if isinstance(value, (str, int)):
                if isinstance(value, str):
                    # PDF-Formularfelder nutzen \r als Zeilenumbruch (PDF-Spec ISO 32000).
                    # LLMs geben manchmal literal \\n (zwei Zeichen) aus → ebenfalls ersetzen.
                    value = value.replace('\r\n', '\r').replace('\\n', '\r').replace('\n', '\r')
                if isinstance(pdf_id, list):
                    for pid in pdf_id: fields_to_fill[pid] = value
                else:
                    fields_to_fill[pdf_id] = value

        # 2. Checkboxen
        checkbox_fields = apply_checkbox_logic(data)

        # 3. Anwenden
        all_fields = {**fields_to_fill, **checkbox_fields}
        
        # Iteriere über alle Seiten, um sicherzustellen, dass Felder auf Seite 2 (z.B. Obj39, Bemerkungen) auch gefüllt werden
        for page in writer.pages:
            writer.update_page_form_field_values(
                page, all_fields, auto_regenerate=False
            )

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
        logger.debug(f"Unterschrift: '{unterschrift_text}' an Position ({SIGNATURE_POSITION_X}, {SIGNATURE_POSITION_Y})")

        return output_pdf_path

    except FileNotFoundError as e:
        logger.error(f"Template nicht gefunden: {input_pdf_path}")
        raise
    except Exception as e:
        logger.exception(f"Fehler bei PDF-Generierung: {e}")
        raise
