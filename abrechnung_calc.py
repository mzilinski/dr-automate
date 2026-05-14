"""
Server-autoritative Berechnung der Reisekostenabrechnung nach NRKVO.

Eingabe: AbrechnungData (Wizard-State).
Ausgabe: BerechneteWerte (Tagegeld, Kürzungen, Übernachtungsgeld, Wegstrecke,
Zwischensumme, Auszahlbetrag).

Identische Logik liegt zusätzlich im Frontend für Live-Berechnung; diese hier
ist die einzig autoritative Quelle für das PDF.
"""

from datetime import datetime

import nrkvo_rates as r
from models import AbrechnungData, BerechneteWerte

DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M"


def _parse_dt(datum: str, zeit: str) -> datetime:
    return datetime.strptime(f"{datum} {zeit}", f"{DATE_FMT} {TIME_FMT}")


def _round2(x: float) -> float:
    """Auf 2 Nachkommastellen runden (Cent-genau)."""
    return round(x, 2)


def tagegeld_tage(start: datetime, ende: datetime) -> tuple[int, int]:
    """Liefert (volle_24h_tage, teiltage).

    NRKVO-Logik:
    - Abwesenheit < 8 h: kein Tagegeld.
    - 8 h ≤ Abwesenheit < 24 h: 1 Teiltag (auch bei Mitternachts-Ueberquerung —
      eine 23:00→06:00 Reise sind 7 h und damit unter Tagegeld-Schwelle;
      eine 18:00→09:00 Reise sind 15 h = 1 Teiltag, nicht 2).
    - Abwesenheit ≥ 24 h: An- und Abreisetag je Teiltag, dazwischen volle Tage
      (kalendrisch gezaehlt).
    """
    delta = ende - start
    total_hours = delta.total_seconds() / 3600.0

    if total_hours < 8:
        return (0, 0)
    if total_hours < 24:
        # Reise < 24 h zaehlt immer als 1 Teiltag, egal ob Datum-Uebergang.
        return (0, 1)

    # ≥ 24 h: kalendrisch volle Tage zwischen Anreise- und Abreise-Tag.
    voll_tage = max(0, (ende.date() - start.date()).days - 1)
    return (voll_tage, 2)


def berechnung(data: AbrechnungData) -> BerechneteWerte:
    """Führt die komplette Abrechnung durch."""
    rd = data.reise_details
    start = _parse_dt(rd.start_datum, rd.start_zeit)
    ende = _parse_dt(rd.ende_datum, rd.ende_zeit)

    # 1. Tagegeld
    tagegeld_brutto = 0.0
    if not data.konfiguration_checkboxen.dienstgeschaeft_2km_umkreis:
        voll, teil = tagegeld_tage(start, ende)
        tagegeld_brutto = voll * r.TAGEGELD_VOLLER_TAG_EUR + teil * r.TAGEGELD_TEILTAG_EUR

    # 2. Kürzungen für unentgeltliche Verpflegung
    kuerzung = (
        data.verpflegung.fruehstueck_anzahl * r.kuerzung_fruehstueck_eur()
        + data.verpflegung.mittag_anzahl * r.kuerzung_mittagessen_eur()
        + data.verpflegung.abend_anzahl * r.kuerzung_abendessen_eur()
    )
    # Kürzung kann Tagegeld nicht negativ machen
    kuerzung = min(kuerzung, tagegeld_brutto)
    tagegeld_netto = tagegeld_brutto - kuerzung

    if data.verzicht_erklaerung and data.verzicht_erklaerung.verzicht_tagegeld:
        tagegeld_netto = 0.0
        kuerzung = 0.0
        tagegeld_brutto = 0.0

    # 3. Übernachtungsgeld pauschal (20 €/Nacht, max 14, plausibilisiert
    #    gegen tatsaechliche Reisedauer — bei eintaegiger Reise sind 0
    #    Naechte moeglich, bei n-Tage-Reise max n Naechte).
    max_naechte_real = max(0, (ende.date() - start.date()).days)
    naechte_input = data.uebernachtungen.anzahl_pauschal
    naechte = min(
        naechte_input,
        r.UEBERNACHTUNG_PAUSCHAL_MAX_NAECHTE,
        max_naechte_real,
    )
    if naechte < naechte_input:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Pauschal-Naechte %d > Reisedauer %d Naechte; auf %d gedeckelt.",
            naechte_input,
            max_naechte_real,
            naechte,
        )
    uebernachtungsgeld_pauschal = naechte * r.UEBERNACHTUNG_PAUSCHAL_EUR
    if data.verzicht_erklaerung and data.verzicht_erklaerung.verzicht_uebernachtungsgeld:
        uebernachtungsgeld_pauschal = 0.0

    # 4. Wegstreckenentschädigung
    wegstrecke = 0.0
    if not (data.verzicht_erklaerung and data.verzicht_erklaerung.verzicht_fahrtkosten):
        # Hinreise
        if data.befoerderung.hinreise.typ == "PKW":
            satz = r.wegstrecke_satz_eur(data.befoerderung.hinreise.paragraph_5_nrkvo)
            wegstrecke += data.wegstrecke.km_hinreise * satz
        # Rückreise
        if data.befoerderung.rueckreise.typ == "PKW":
            satz = r.wegstrecke_satz_eur(data.befoerderung.rueckreise.paragraph_5_nrkvo)
            wegstrecke += data.wegstrecke.km_rueckreise * satz

        # Cap bei § 5 II (kleine Wegstrecke): 125 € pro Reise — nur greifen, wenn
        # AUSSCHLIESSLICH § 5 II verwendet wird (gemischte Reisen sind selten,
        # bei reiner § 5 III ist kein Cap definiert).
        nur_klein = (
            data.befoerderung.hinreise.paragraph_5_nrkvo == "II"
            and data.befoerderung.rueckreise.paragraph_5_nrkvo == "II"
        )
        if nur_klein and wegstrecke > r.WEGSTRECKE_KLEIN_MAX_EUR:
            wegstrecke = r.WEGSTRECKE_KLEIN_MAX_EUR

    # 5. Belegte Beträge (kein Verzicht-Mechanismus auf Belege)
    belege = (
        data.beleg_betraege.fahrkarte_eur
        + data.beleg_betraege.zuschlaege_eur
        + data.beleg_betraege.sonstige_fahrt_eur
        + data.beleg_betraege.sonstige_kosten_eur
        + data.uebernachtungen.kosten_eur
    )
    if data.verzicht_erklaerung and data.verzicht_erklaerung.verzicht_fahrtkosten:
        # Belegfahrtkosten + Wegstrecke unterdrücken
        belege -= (
            data.beleg_betraege.fahrkarte_eur
            + data.beleg_betraege.zuschlaege_eur
            + data.beleg_betraege.sonstige_fahrt_eur
        )

    # 6. Zwischensumme
    zwischensumme = tagegeld_netto + uebernachtungsgeld_pauschal + wegstrecke + belege

    # 7. Auszahlbetrag (kann negativ sein → Rückzahlung)
    abzuege = data.abzuege.zuwendungen_eur + data.abzuege.reisekostenabschlag_eur + data.abzuege.eigenanteile_eur
    auszahlbetrag = zwischensumme - abzuege

    return BerechneteWerte(
        tagegeld_brutto_eur=_round2(tagegeld_brutto),
        kuerzung_eur=_round2(kuerzung),
        tagegeld_netto_eur=_round2(tagegeld_netto),
        uebernachtungsgeld_pauschal_eur=_round2(uebernachtungsgeld_pauschal),
        wegstreckenentschaedigung_eur=_round2(wegstrecke),
        zwischensumme_eur=_round2(zwischensumme),
        auszahlbetrag_eur=_round2(auszahlbetrag),
    )
