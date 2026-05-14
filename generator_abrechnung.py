"""PDF-Generator für die Reisekostenabrechnung (Formular 035_002)."""

import io
import logging
import os
import re
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import nrkvo_rates
from abrechnung_calc import berechnung, tagegeld_tage
from generator import set_need_appearances
from models import AbrechnungData

logger = logging.getLogger(__name__)

DATE_INPUT_FORMAT = "%d.%m.%Y"
DATE_OUTPUT_FORMAT = "%Y%m%d"

# Unterschrift Page 2 (visuell unterhalb von "Unterschrift, Amtsbez./Datum")
SIGNATURE_POSITION_X = 70
SIGNATURE_POSITION_Y = 595
SIGNATURE_FONT = "Helvetica"
SIGNATURE_FONT_SIZE = 10


def _fmt_dt(datum: str, zeit: str) -> str:
    return f"{datum} {zeit}".strip()


def _fmt_eur(value: float) -> str:
    """Formatiert EUR-Betrag deutsch (z. B. 28,00). Leere Zeichenkette bei 0."""
    if value == 0:
        return ""
    return f"{value:.2f}".replace(".", ",")


def _split_iban(iban: str) -> dict:
    """IBAN char-für-char auf IBAN1..IBAN22 verteilen."""
    fields = {}
    cleaned = "".join(iban.split()).upper()
    for i in range(22):
        fields[f"IBAN{i + 1}"] = cleaned[i] if i < len(cleaned) else ""
    return fields


def _create_signature_overlay(text_str: str) -> PdfReader:
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    can.setFont(SIGNATURE_FONT, SIGNATURE_FONT_SIZE)
    can.drawString(SIGNATURE_POSITION_X, SIGNATURE_POSITION_Y, text_str)
    can.save()
    packet.seek(0)
    return PdfReader(packet)


def _build_text_fields(data: AbrechnungData) -> dict:
    """Befüllt alle Textfelder."""
    fields = {}

    # Kopfblock
    fields["Beschaeftigungsstelle"] = data.antragsteller.abteilung
    fields["Abrechnende_Dienststelle"] = data.stammdaten.abrechnende_dienststelle
    fields["Name__Vorname"] = data.antragsteller.name

    wohnung_lines = [data.antragsteller.adresse_privat]
    if data.antragsteller.telefon:
        wohnung_lines.append(f"Tel.: {data.antragsteller.telefon}")
    if data.stammdaten.email:
        wohnung_lines.append(data.stammdaten.email)
    fields["Wohnungsanschrift"] = "\r".join(wohnung_lines)

    # IBAN char-für-char
    fields.update(_split_iban(data.stammdaten.iban))
    fields["BIC"] = data.stammdaten.bic

    # RKR + Datum/Daten der Reise
    rd = data.reise_details
    rkr_text = f"{data.rkr}: {rd.start_datum}"
    if rd.start_datum != rd.ende_datum:
        rkr_text += f" – {rd.ende_datum}"
    rkr_text += f" — {rd.zweck}"
    fields["Grund_der_RKR"] = rkr_text
    fields["Grund_der_RKR1"] = ""

    # Begründung "kein Großkundenrabatt"
    fields["Begruendung_nein"] = data.konfiguration_checkboxen.grosskundenrabatt_begruendung_wenn_nein or ""

    # Strecke der Ermäßigungskarte (kein passendes Feld im Antrag → leer)
    fields["Strecke"] = ""

    # Verpflegungs-Beschreibung (Tage/Mahlzeiten/Nächte)
    verpf_parts = []
    v = data.verpflegung
    if v.fruehstueck_anzahl:
        verpf_parts.append(f"{v.fruehstueck_anzahl}× Frühstück")
    if v.mittag_anzahl:
        verpf_parts.append(f"{v.mittag_anzahl}× Mittagessen")
    if v.abend_anzahl:
        verpf_parts.append(f"{v.abend_anzahl}× Abendessen")
    if data.uebernachtungen.anzahl_unentgeltlich:
        verpf_parts.append(f"{data.uebernachtungen.anzahl_unentgeltlich}× Übernachtung")
    fields["Verpflegung"] = ", ".join(verpf_parts)

    # RRS-Aktenzeichen
    fields["Bei_RRS"] = data.rrs_aktenzeichen if data.rkr == "RRS" else ""

    # Tagegeld-Zeilen aufgesplittet: Zeile 1 = volle Tage, Zeile 2 = Teiltage,
    # Zeile 3 = Netto nach Kürzung (nur wenn relevant). Kürzungsspalte ist
    # rotes Admin-Feld und bleibt leer.
    start_dt = datetime.strptime(f"{rd.start_datum} {rd.start_zeit}", "%d.%m.%Y %H:%M")
    ende_dt = datetime.strptime(f"{rd.ende_datum} {rd.ende_zeit}", "%d.%m.%Y %H:%M")
    if data.konfiguration_checkboxen.dienstgeschaeft_2km_umkreis:
        voll_count, teil_count = 0, 0
    else:
        voll_count, teil_count = tagegeld_tage(start_dt, ende_dt)

    voll_brutto = voll_count * nrkvo_rates.TAGEGELD_VOLLER_TAG_EUR
    teil_brutto = teil_count * nrkvo_rates.TAGEGELD_TEILTAG_EUR

    fields["Tage"] = str(voll_count) if voll_count else ""
    fields["EUR"] = _fmt_eur(voll_brutto)
    fields["Tage6"] = str(teil_count) if teil_count else ""
    fields["EUR6"] = _fmt_eur(teil_brutto)
    # Zeile 3: Netto-Tagegeld nach Kürzungen (Transparenz für Sachbearbeitung).
    # Wichtig: auch bei Netto = 0 € füllen, sonst kann die Sachbearbeitung
    # "keine Kürzung" nicht von "voll gekürzt" unterscheiden.
    fields["Tage7"] = ""
    if data.berechnet.kuerzung_eur > 0:
        netto = data.berechnet.tagegeld_netto_eur
        fields["EUR7"] = f"{netto:.2f}".replace(".", ",")
    else:
        fields["EUR7"] = ""

    # Reisezeiten
    fields["Beginn_der_Dienstreise"] = _fmt_dt(rd.start_datum, rd.start_zeit)
    fields["Beginn_des_Dienstgeschaefts"] = _fmt_dt(rd.dienstgeschaeft_beginn_datum, rd.dienstgeschaeft_beginn_zeit)
    fields["Ende_des_Dienstgeschaefts"] = _fmt_dt(rd.dienstgeschaeft_ende_datum, rd.dienstgeschaeft_ende_zeit)
    fields["Ende_der_Dienstreise"] = _fmt_dt(rd.ende_datum, rd.ende_zeit)

    # Übernachtungsgeld (pauschal)
    fields["Uebernachtungsgeld"] = _fmt_eur(data.berechnet.uebernachtungsgeld_pauschal_eur)

    # Anordnung
    if data.anordnung.dienststelle or data.anordnung.datum:
        fields["Dienststelle_Datum"] = f"{data.anordnung.dienststelle} / {data.anordnung.datum}".strip(" /")
    else:
        fields["Dienststelle_Datum"] = ""

    # Reiseziel/Reiseweg — Feld ist einzeilig (kein Multiline-Flag), daher
    # sichtbares Trennzeichen statt \r.
    fields["Reiseziel_Reiseweg"] = f"{rd.zielort} · {rd.reiseweg}"

    # Erläuterungen (Reisezweck, PKW-Begründung, mitfahrende Personen, Sonstiges)
    erl_parts = []
    # Mitfahrt explizit auszeichnen — die Abrechnung hat keine eigene Mitfahrt-Box
    mitfahrt_hin = data.befoerderung.hinreise.typ == "MITFAHRT"
    mitfahrt_rueck = data.befoerderung.rueckreise.typ == "MITFAHRT"
    if mitfahrt_hin and mitfahrt_rueck:
        erl_parts.append("Mitfahrer hin und zurück (kein eigener Anspruch auf Wegstreckenentschädigung)")
    elif mitfahrt_hin:
        erl_parts.append("Hinreise: Mitfahrer (kein eigener Anspruch auf Wegstreckenentschädigung)")
    elif mitfahrt_rueck:
        erl_parts.append("Rückreise: Mitfahrer (kein eigener Anspruch auf Wegstreckenentschädigung)")
    if data.befoerderung.sonderfall_begruendung_textfeld:
        erl_parts.append(data.befoerderung.sonderfall_begruendung_textfeld)
    if data.antragsteller.mitreisender_name:
        erl_parts.append(f"Mitreisender: {data.antragsteller.mitreisender_name}")
    naechte = data.uebernachtungen.anzahl_pauschal
    if naechte > 0:
        eur_pro_nacht = data.uebernachtungen.kosten_eur / naechte
        if eur_pro_nacht > nrkvo_rates.UEBERNACHTUNG_BELEG_OHNE_BEGRUENDUNG_MAX_EUR and data.uebernachtungen.begruendung_ueber_100:
            erl_parts.append(f"Übernachtung > 100 €/Nacht: {data.uebernachtungen.begruendung_ueber_100}")
    if data.beleg_betraege.wagenklasse:
        erl_parts.append(f"Wagenklasse: {data.beleg_betraege.wagenklasse}")
    if data.beleg_betraege.sonstige_fahrt_erlaeuterung:
        erl_parts.append(data.beleg_betraege.sonstige_fahrt_erlaeuterung)
    fields["Erlaeuterungen"] = "\r".join(erl_parts)

    # Erstattung Übernachtungskosten (mit Beleg)
    fields["Erstattung_Uebernachtungskosten"] = _fmt_eur(data.uebernachtungen.kosten_eur)

    # Bahn-Beträge
    fields["Fahrkarte"] = _fmt_eur(data.beleg_betraege.fahrkarte_eur)
    fields["Zuschlaege"] = _fmt_eur(data.beleg_betraege.zuschlaege_eur)

    # Sonstige Fahrtkosten (Page 1 — Belege beigefügt)
    fields["Sonstige_Fahrauslagen"] = _fmt_eur(data.beleg_betraege.sonstige_fahrt_eur)

    # Wegstrecke: Hinreise (Tage3/EUR3/Wegstreckenentschaedigung) + Rückreise (Tage4/EUR4/Wegstreckenentschaedigung1)
    if data.befoerderung.hinreise.typ == "PKW" and data.wegstrecke.km_hinreise > 0:
        satz = nrkvo_rates.wegstrecke_satz_eur(data.befoerderung.hinreise.paragraph_5_nrkvo)
        fields["Tage3"] = str(data.wegstrecke.km_hinreise)
        fields["EUR3"] = f"{satz:.2f}".replace(".", ",")
        fields["Wegstreckenentschaedigung"] = _fmt_eur(data.wegstrecke.km_hinreise * satz)
    else:
        fields["Tage3"] = ""
        fields["EUR3"] = ""
        fields["Wegstreckenentschaedigung"] = ""

    if data.befoerderung.rueckreise.typ == "PKW" and data.wegstrecke.km_rueckreise > 0:
        satz = nrkvo_rates.wegstrecke_satz_eur(data.befoerderung.rueckreise.paragraph_5_nrkvo)
        fields["Tage4"] = str(data.wegstrecke.km_rueckreise)
        fields["EUR4"] = f"{satz:.2f}".replace(".", ",")
        fields["Wegstreckenentschaedigung1"] = _fmt_eur(data.wegstrecke.km_rueckreise * satz)
    else:
        fields["Tage4"] = ""
        fields["EUR4"] = ""
        fields["Wegstreckenentschaedigung1"] = ""

    # Page 2: Erstattung sonstiger Kosten + Erläuterung
    fields["Sonstige_Fahrauslagen1"] = _fmt_eur(data.beleg_betraege.sonstige_kosten_eur)
    fields["Erlaeuterungen1"] = data.beleg_betraege.sonstige_kosten_erlaeuterung

    # Höhe der Abzüge
    fields["Tage5"] = _fmt_eur(data.abzuege.zuwendungen_eur)
    fields["Tage8"] = _fmt_eur(data.abzuege.reisekostenabschlag_eur)
    fields["Erlaeuterungen2"] = data.abzuege.eigenanteile_erlaeuterung

    # Zeilenumbrüche für PDF-Konvention (\r)
    return {k: (v.replace("\r\n", "\r").replace("\\n", "\r").replace("\n", "\r") if isinstance(v, str) else v) for k, v in fields.items()}


def _build_button_fields(data: AbrechnungData) -> dict:
    """Befüllt alle Checkbox-Buttons."""
    cb = {}
    k = data.konfiguration_checkboxen

    # BahnCard (OBJ21–28)
    if not k.bahncard_business_vorhanden and not k.bahncard_privat_vorhanden:
        cb["OBJ21"] = "/Yes"  # Nein
    else:
        cb["OBJ22"] = "/Yes"  # Ja, und zwar
        # OBJ23/24/25 = Business 25/50/100, OBJ26/27/28 = 25/50/100
        # Granularere Auswahl haben wir nicht im Modell — wir markieren nur
        # die Kategorie. Default Business 25 / privat 25 wenn unklar.
        if k.bahncard_business_vorhanden:
            cb["OBJ23"] = "/Yes"  # Business 25 (Default-Annahme)
        if k.bahncard_privat_vorhanden:
            cb["OBJ26"] = "/Yes"  # 25 (Default-Annahme)

    # Geschäftskundenrabatt: OBJ29=Ja, OBJ30=Nein
    if k.grosskundenrabatt_genutzt:
        cb["OBJ29"] = "/Yes"
    else:
        cb["OBJ30"] = "/Yes"

    # Ermäßigungskarte: OBJ32=Nein, OBJ33=Ja
    if k.weitere_ermaessigungen_vorhanden:
        cb["OBJ33"] = "/Yes"
    else:
        cb["OBJ32"] = "/Yes"

    # 2-km-Umkreis: OBJ34=Nein, OBJ35=Ja
    if k.dienstgeschaeft_2km_umkreis:
        cb["OBJ35"] = "/Yes"
    else:
        cb["OBJ34"] = "/Yes"

    # Unentgeltliche Verpflegung/Unterkunft: OBJ36=Ja, OBJ37=Nein
    has_unent = (
        data.verpflegung.fruehstueck_anzahl > 0
        or data.verpflegung.mittag_anzahl > 0
        or data.verpflegung.abend_anzahl > 0
        or data.uebernachtungen.anzahl_unentgeltlich > 0
    )
    if has_unent:
        cb["OBJ36"] = "/Yes"
    else:
        cb["OBJ37"] = "/Yes"

    # Trennungsgeld: OBJ38=Nein, OBJ39=Ja
    if k.anspruch_trennungsgeld:
        cb["OBJ39"] = "/Yes"
    else:
        cb["OBJ38"] = "/Yes"

    # Urlaub > 5 Tage: OBJ40=Nein, OBJ41=Ja
    if data.flags.urlaub_ueber_5_tage:
        cb["OBJ41"] = "/Yes"
    else:
        cb["OBJ40"] = "/Yes"

    # Auslandsdienstreise: OBJ42=Nein (immer, v1 nur Inland), OBJ43=Ja
    cb["OBJ42"] = "/Yes"

    # Anlagen: OBJ1=035_001, OBJ2=035_003
    if data.anlagen_beigefuegt.genehmigung_035_001:
        cb["OBJ1"] = "/Yes"
    if data.anlagen_beigefuegt.anlagen_035_003:
        cb["OBJ2"] = "/Yes"

    # Anordnung-Checkbox (OBJ3): "Auf Anordnung oder Genehmigung durch"
    if data.anordnung.dienststelle:
        cb["OBJ3"] = "/Yes"

    # Beförderungsmittel (OBJ4=Bahn/Bus, OBJ5=Dienst-Kfz, OBJ6=PKW §II,
    # OBJ7=PKW §III, OBJ8=sonstiges/Anhänger). Hinreise-Typ als primär.
    typ = data.befoerderung.hinreise.typ
    para = data.befoerderung.hinreise.paragraph_5_nrkvo
    if typ in ("BAHN", "BUS"):
        cb["OBJ4"] = "/Yes"
    elif typ == "DIENSTWAGEN":
        cb["OBJ5"] = "/Yes"
    elif typ == "PKW":
        cb["OBJ7" if para == "III" else "OBJ6"] = "/Yes"
    elif typ == "FLUG":
        cb["OBJ8"] = "/Yes"
    # MITFAHRT: keine Box angekreuzt — der Mitfahrer macht für den PKW-Anteil
    # keinen eigenen Posten geltend, der Hinweis steht in den Erläuterungen.

    # Zuwendungen Dritter: OBJ9=Nein, OBJ10=Ja
    if data.abzuege.zuwendungen_eur > 0:
        cb["OBJ10"] = "/Yes"
    else:
        cb["OBJ9"] = "/Yes"

    # Reisekostenabschlag: OBJ52=Nein, OBJ53=Ja
    if data.abzuege.reisekostenabschlag_eur > 0:
        cb["OBJ53"] = "/Yes"
    else:
        cb["OBJ52"] = "/Yes"

    # Eigenanteile: OBJ54=Nein, OBJ55=Ja
    if data.abzuege.eigenanteile_eur > 0:
        cb["OBJ55"] = "/Yes"
    else:
        cb["OBJ54"] = "/Yes"

    # Auszuzahlen / Zurückzuzahlen: OBJ56/OBJ57
    if data.berechnet.auszahlbetrag_eur >= 0:
        cb["OBJ56"] = "/Yes"
    else:
        cb["OBJ57"] = "/Yes"

    # OBJ58/OBJ59 sind Admin-Felder → bleiben leer

    return cb


def generate_output_filename(data: AbrechnungData) -> str:
    """YYYYMMDD_DR-Abrechnung_<Stadt>_<Thema>.pdf"""
    rd = data.reise_details
    try:
        date_obj = datetime.strptime(rd.start_datum, DATE_INPUT_FORMAT)
        date_prefix = date_obj.strftime(DATE_OUTPUT_FORMAT)
    except ValueError:
        date_prefix = datetime.now().strftime(DATE_OUTPUT_FORMAT)

    match = re.search(r"\d{5}\s+([A-Za-zäöüÄÖÜß\s\-]+)", rd.zielort)
    city_suffix = match.group(1).strip() if match else rd.zielort

    topic_suffix = ""
    if rd.zweck:
        remaining = rd.zweck.split(":", 1)[-1].strip() if ":" in rd.zweck else rd.zweck
        words = remaining.split()
        if words:
            topic_suffix = words[0]

    raw_suffix = city_suffix + (f"_{topic_suffix}" if topic_suffix else "")
    clean = re.sub(r"[^A-Za-z0-9äöüÄÖÜß_]", "_", raw_suffix)
    clean = re.sub(r"_+", "_", clean).strip("_") or "Abrechnung"

    return f"{date_prefix}_DR-Abrechnung_{clean}.pdf"


def fill_pdf(data: AbrechnungData, input_pdf_path: str, output_dir: str) -> str:
    """Befüllt das Abrechnungs-PDF.

    Berechnungswerte werden vor dem Befüllen autoritativ neu berechnet —
    Werte aus dem Input werden überschrieben.
    """
    # Autoritative Berechnung
    data.berechnet = berechnung(data)

    os.makedirs(output_dir, exist_ok=True)
    output_filename = generate_output_filename(data)
    output_pdf_path = os.path.join(output_dir, output_filename)

    writer = PdfWriter(clone_from=input_pdf_path)

    text_fields = _build_text_fields(data)
    button_fields = _build_button_fields(data)
    all_fields = {**text_fields, **button_fields}

    for page in writer.pages:
        writer.update_page_form_field_values(page, all_fields, auto_regenerate=False)

    set_need_appearances(writer)

    # Unterschrift Seite 2
    heute = datetime.now().strftime(DATE_INPUT_FORMAT)
    overlay = _create_signature_overlay(f"{data.antragsteller.name}, {heute}")
    writer.pages[1].merge_page(overlay.pages[0], over=True)

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    logger.info(f"Abrechnungs-PDF erstellt: {output_pdf_path}")
    return output_pdf_path
