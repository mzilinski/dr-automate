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
from abrechnung_calc import berechnung
from generator import grosskundenrabatt_begruendung, hat_bahn, set_need_appearances
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


def _fmt_eur_text(value: float) -> str:
    """Betrag für Fließtext (Erläuterungen), immer mit Einheit."""
    return f"{value:.2f}".replace(".", ",") + " €"


def _split_iban(iban: str) -> dict:
    """IBAN char-für-char auf IBAN1..IBAN22 verteilen.

    Der amtliche Vordruck 035-002 hat nur 22 Felder (passt fuer DE/AT/UK,
    nicht fuer MT/SA/MU mit bis zu 31/24/30 Zeichen). Bei laengeren IBANs
    warnen wir — die ueberzaehligen Zeichen wuerden sonst still abgeschnitten.
    """
    import logging as _logging

    fields = {}
    cleaned = "".join(iban.split()).upper()
    if len(cleaned) > 22:
        _logging.getLogger(__name__).warning(
            "IBAN ist %d Zeichen lang, der Vordruck hat nur 22 Felder — Zeichen %d–%d werden NICHT eingetragen!",
            len(cleaned),
            23,
            len(cleaned),
        )
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

    # Begründung "kein Großkundenrabatt" — ohne Bahn-/Busfahrt leitet der
    # Antrags-Generator sie aus der Verkehrsmittel-Wahl ab (gleiche Logik).
    fields["Begruendung_nein"] = grosskundenrabatt_begruendung(data.model_dump())

    # Strecke der Ermäßigungskarte („Ja, und zwar für die Strecke")
    k = data.konfiguration_checkboxen
    fields["Strecke"] = (k.ermaessigungskarte_strecke or "") if _hat_ermaessigungskarte(data) else ""

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

    # Tagegeld: Der Vordruck rechnet „Tage × EUR" (Satz je Tag) — die
    # Spalte EUR enthält den Tagessatz, nicht die Summe (wie bei der
    # Wegstrecke km × Satz). Bis 2026-10 stand hier der Gesamtbetrag, was die
    # Sachbearbeitung als Tage × Summe lesen musste. Zeilen:
    #   1 = volle Tage (28 €), 2 = Teiltage (14 €),
    #   3 = ab dem 15. Aufenthaltstag verminderte Tage (§ 7 Abs. 2 NRKVO).
    # Kürzungen trägt die Amtsspalte ein; die Mahlzeiten stehen im Feld
    # „Verpflegung", Brutto/Kürzung/Netto in den Erläuterungen.
    b = data.berechnet
    rows = [("Tage", "EUR", 0, 0.0), ("Tage6", "EUR6", 0, 0.0), ("Tage7", "EUR7", 0, 0.0)]
    if not data.verzicht_erklaerung.verzicht_tagegeld:
        reduziert_satz = (
            nrkvo_rates.TAGEGELD_VOLLER_TAG_EUR * (100 - nrkvo_rates.DAUERAUFENTHALT_REDUKTION_PROZENT) / 100
        )
        rows = [
            ("Tage", "EUR", b.tagegeld_volle_tage, nrkvo_rates.TAGEGELD_VOLLER_TAG_EUR),
            ("Tage6", "EUR6", b.tagegeld_teiltage, nrkvo_rates.TAGEGELD_TEILTAG_EUR),
            ("Tage7", "EUR7", b.tagegeld_reduzierte_tage, reduziert_satz),
        ]
    for f_tage, f_eur, anzahl, satz in rows:
        fields[f_tage] = str(anzahl) if anzahl else ""
        fields[f_eur] = _fmt_eur(satz) if anzahl else ""

    # Reisezeiten
    fields["Beginn_der_Dienstreise"] = _fmt_dt(rd.start_datum, rd.start_zeit)
    fields["Beginn_des_Dienstgeschaefts"] = _fmt_dt(rd.dienstgeschaeft_beginn_datum, rd.dienstgeschaeft_beginn_zeit)
    fields["Ende_des_Dienstgeschaefts"] = _fmt_dt(rd.dienstgeschaeft_ende_datum, rd.dienstgeschaeft_ende_zeit)
    fields["Ende_der_Dienstreise"] = _fmt_dt(rd.ende_datum, rd.ende_zeit)

    # Übernachtungsgeld (pauschal)
    fields["Uebernachtungsgeld"] = _fmt_eur(b.uebernachtungsgeld_pauschal_eur)

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
    mitreisende = [t.name for t in data.reise_details.weitere_teilnehmer]
    if data.antragsteller.mitreisender_name:
        mitreisende.append(data.antragsteller.mitreisender_name)
    if mitreisende:
        erl_parts.append(f"Mitreisende: {', '.join(mitreisende)}")
    # Begründung für Hotelkosten > 100 €/Nacht (§ 8 Abs. 1 NRKVO: darüber
    # nur, soweit unvermeidbar). €/Nacht rechnet abrechnung_calc über die
    # Belegnächte; eine eingetragene Begründung geht nie still verloren.
    if data.uebernachtungen.begruendung_ueber_100 and b.uebernachtung_beleg_eur:
        erl_parts.append(
            f"Übernachtung {_fmt_eur_text(b.uebernachtung_beleg_pro_nacht_eur)}/Nacht: "
            f"{data.uebernachtungen.begruendung_ueber_100}"
        )
    if b.kuerzung_eur:
        erl_parts.append(
            f"Tagegeld {_fmt_eur_text(b.tagegeld_brutto_eur)} − Kürzung Verpflegung "
            f"{_fmt_eur_text(b.kuerzung_eur)} = {_fmt_eur_text(b.tagegeld_netto_eur)}"
        )
    v = data.verzicht_erklaerung
    verzichte = [
        txt
        for flag, txt in (
            (v.verzicht_tagegeld, "Tagegeld"),
            (v.verzicht_uebernachtungsgeld, "Übernachtungsgeld"),
            (v.verzicht_fahrtkosten, "Fahrtkosten"),
        )
        if flag
    ]
    if verzichte:
        erl_parts.append(f"Verzicht auf {', '.join(verzichte)}.")
    erl_parts.extend(b.hinweise)
    if data.beleg_betraege.wagenklasse:
        erl_parts.append(f"Wagenklasse: {data.beleg_betraege.wagenklasse}")
    if data.beleg_betraege.sonstige_fahrt_erlaeuterung:
        erl_parts.append(data.beleg_betraege.sonstige_fahrt_erlaeuterung)
    fields["Erlaeuterungen"] = "\r".join(erl_parts)

    # Erstattung Übernachtungskosten (mit Beleg) — Beträge aus der
    # Berechnung, damit Verzichtserklärungen auch im PDF greifen.
    fields["Erstattung_Uebernachtungskosten"] = _fmt_eur(b.uebernachtung_beleg_eur)

    # Bahn-Beträge
    verzicht_fahrt = data.verzicht_erklaerung.verzicht_fahrtkosten
    fields["Fahrkarte"] = "" if verzicht_fahrt else _fmt_eur(data.beleg_betraege.fahrkarte_eur)
    fields["Zuschlaege"] = "" if verzicht_fahrt else _fmt_eur(data.beleg_betraege.zuschlaege_eur)

    # Sonstige Fahrtkosten (Page 1 — Belege beigefügt)
    fields["Sonstige_Fahrauslagen"] = _fmt_eur(b.sonstige_fahrt_eur)

    # Wegstrecke: Hinreise (Tage3/EUR3/Wegstreckenentschaedigung) + Rückreise
    # (Tage4/EUR4/Wegstreckenentschaedigung1). Die Summen kommen aus der
    # Berechnung — dort ist der 125-€-Deckel (§ 5 II) bereits verteilt.
    for befoerderung, km, betrag, (f_km, f_satz, f_sum) in (
        (
            data.befoerderung.hinreise,
            data.wegstrecke.km_hinreise,
            b.wegstrecke_hin_eur,
            ("Tage3", "EUR3", "Wegstreckenentschaedigung"),
        ),
        (
            data.befoerderung.rueckreise,
            data.wegstrecke.km_rueckreise,
            b.wegstrecke_rueck_eur,
            ("Tage4", "EUR4", "Wegstreckenentschaedigung1"),
        ),
    ):
        if befoerderung.typ == "PKW" and km > 0 and not verzicht_fahrt:
            satz = nrkvo_rates.wegstrecke_satz_eur(befoerderung.paragraph_5_nrkvo)
            fields[f_km] = str(km)
            fields[f_satz] = f"{satz:.2f}".replace(".", ",")
            fields[f_sum] = _fmt_eur(betrag)
        else:
            fields[f_km] = fields[f_satz] = fields[f_sum] = ""

    # Page 2: Erstattung sonstiger Kosten + Erläuterung
    fields["Sonstige_Fahrauslagen1"] = _fmt_eur(data.beleg_betraege.sonstige_kosten_eur)
    fields["Erlaeuterungen1"] = data.beleg_betraege.sonstige_kosten_erlaeuterung

    # Höhe der Abzüge
    fields["Tage5"] = _fmt_eur(data.abzuege.zuwendungen_eur)
    fields["Tage8"] = _fmt_eur(data.abzuege.reisekostenabschlag_eur)
    fields["Erlaeuterungen2"] = data.abzuege.eigenanteile_erlaeuterung

    # Zeilenumbrüche für PDF-Konvention (\r)
    return {
        k: (v.replace("\r\n", "\r").replace("\\n", "\r").replace("\n", "\r") if isinstance(v, str) else v)
        for k, v in fields.items()
    }


def _hat_ermaessigungskarte(data: AbrechnungData) -> bool:
    """Ermäßigungskarte (Monatskarte/Jobticket) für die Strecke. Ältere
    Wizard-Exporte kannten nur ``weitere_ermaessigungen_vorhanden`` für
    diese Frage — das zählt weiterhin als „Ja"."""
    k = data.konfiguration_checkboxen
    return bool(k.ermaessigungskarte_vorhanden or k.weitere_ermaessigungen_vorhanden)


def _build_button_fields(data: AbrechnungData) -> dict:
    """Befüllt alle Checkbox-Buttons."""
    cb = {}
    k = data.konfiguration_checkboxen

    # BahnCard (OBJ21–28): OBJ23/24/25 = Business 25/50/100,
    # OBJ26/27/28 = private BahnCard 25/50/100.
    if not k.bahncard_business_vorhanden and not k.bahncard_privat_vorhanden:
        cb["OBJ21"] = "/Yes"  # Nein
    else:
        cb["OBJ22"] = "/Yes"  # Ja, und zwar
        if k.bahncard_business_vorhanden:
            # Die Business-Stufe erfasst weder Profil noch Wizard; die
            # Dienststelle gibt in der Regel die Business 25 aus.
            cb["OBJ23"] = "/Yes"
        if k.bahncard_privat_vorhanden:
            stufe = k.bahncard_privat_stufe if k.bahncard_privat_stufe in (25, 50, 100) else 25
            cb[{25: "OBJ26", 50: "OBJ27", 100: "OBJ28"}[stufe]] = "/Yes"

    # Geschäftskundenrabatt: OBJ29=Ja, OBJ30=Nein. Reisebezogen wie im
    # Antrag: ohne Bahn-/Busfahrt immer „Nein" (Begründung automatisch).
    genutzt = k.grosskundenrabatt_genutzt and hat_bahn(data.befoerderung.model_dump())
    cb["OBJ29" if genutzt else "OBJ30"] = "/Yes"

    # Ermäßigungskarte: OBJ32=Nein, OBJ33=Ja („und zwar für die Strecke")
    cb["OBJ33" if _hat_ermaessigungskarte(data) else "OBJ32"] = "/Yes"

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
    # OBJ7=PKW §III, OBJ8=sonstiges/Anhänger). Unabhängige Kästchen — Hin-
    # und Rückreise werden beide angekreuzt (z. B. Bahn hin, PKW zurück).
    for b in (data.befoerderung.hinreise, data.befoerderung.rueckreise):
        if b.typ in ("BAHN", "BUS"):
            cb["OBJ4"] = "/Yes"
        elif b.typ == "DIENSTWAGEN":
            cb["OBJ5"] = "/Yes"
        elif b.typ == "PKW":
            cb["OBJ7" if b.paragraph_5_nrkvo == "III" else "OBJ6"] = "/Yes"
        elif b.typ == "FLUG":
            cb["OBJ8"] = "/Yes"
        # MITFAHRT: keine Box — der Mitfahrer macht für den PKW-Anteil keinen
        # eigenen Posten geltend, der Hinweis steht in den Erläuterungen.

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

    # OBJ56/OBJ57 („Auszuzahlen"/„Zurückzuzahlen") und OBJ58/OBJ59 stehen in
    # der Amtsspalte und sind im Vordruck schreibgeschützt (Ff=1) → leer.

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

    # Unterschrift Seite 2 — der Vordruck beschriftet die Zeile mit
    # „Unterschrift, Amtsbez./Datum"; daher Name, Amtsbezeichnung (falls
    # vorhanden) und Datum in genau dieser Reihenfolge.
    heute = datetime.now().strftime(DATE_INPUT_FORMAT)
    sig_parts = [data.antragsteller.name]
    if data.antragsteller.amtsbezeichnung:
        sig_parts.append(data.antragsteller.amtsbezeichnung)
    sig_parts.append(heute)
    overlay = _create_signature_overlay(", ".join(sig_parts))
    writer.pages[1].merge_page(overlay.pages[0], over=True)

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    logger.info(f"Abrechnungs-PDF erstellt: {output_pdf_path}")
    return output_pdf_path
