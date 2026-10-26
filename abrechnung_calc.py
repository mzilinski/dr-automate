"""
Server-autoritative Berechnung der Reisekostenabrechnung nach NRKVO.

Eingabe: AbrechnungData (Wizard-State).
Ausgabe: BerechneteWerte (Tagegeld, Kürzungen, Übernachtungsgeld, Wegstrecke,
Zwischensumme, Auszahlbetrag) plus die Aufschlüsselung, die Wizard-Vorschau
und PDF-Generator brauchen.

Einzige Rechenlogik im Projekt: Der Wizard rechnet nicht selbst, sondern
holt die Vorschau über ``POST /abrechnung/calc`` — so können Vorschau und
PDF nicht auseinanderlaufen.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import nrkvo_rates as r
from models import AbrechnungData, BerechneteWerte

logger = logging.getLogger(__name__)

DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M"


def _parse_dt(datum: str, zeit: str) -> datetime:
    return datetime.strptime(f"{datum} {zeit}", f"{DATE_FMT} {TIME_FMT}")


def _round2(x: float) -> float:
    """Auf 2 Nachkommastellen runden (Cent-genau)."""
    return round(x, 2)


@dataclass
class TagegeldTag:
    """Ein Kalendertag der Reise mit seinem Tagegeld-Anspruch."""

    datum: date
    stunden: float
    art: str  # "voll" (24 h), "teil" (An-/Abreisetag bzw. > 8 h) oder "" (kein Anspruch)
    reduziert: bool = False  # § 7 Abs. 2 NRKVO: ab dem 15. Aufenthaltstag −50 %

    @property
    def betrag(self) -> float:
        if self.art == "voll":
            satz = r.TAGEGELD_VOLLER_TAG_EUR
        elif self.art == "teil":
            satz = r.TAGEGELD_TEILTAG_EUR
        else:
            return 0.0
        if self.reduziert:
            satz = satz * (100 - r.DAUERAUFENTHALT_REDUKTION_PROZENT) / 100
        return satz


def _stunden_pro_tag(start: datetime, ende: datetime) -> list[tuple[date, float]]:
    """Abwesenheitsstunden je Kalendertag (echte Uhrzeit-Differenz, ohne
    Sommerzeit-Sprung — die Reisezeiten sind Ortszeit-Angaben)."""
    out = []
    tag = start.date()
    while tag <= ende.date():
        tag_start = max(start, datetime.combine(tag, datetime.min.time()))
        tag_ende = min(ende, datetime.combine(tag + timedelta(days=1), datetime.min.time()))
        out.append((tag, max(0.0, (tag_ende - tag_start).total_seconds() / 3600.0)))
        tag += timedelta(days=1)
    return out


def tagegeld_kalender(start: datetime, ende: datetime, mit_uebernachtung: bool = False) -> list[TagegeldTag]:
    """Tagegeld-Anspruch je Kalendertag nach § 7 NRKVO i. V. m. § 9 Abs. 4a S. 3 EStG.

    - Eintägig: mehr als 8 h Abwesenheit → Teiltag (14 €).
    - Mehrtägig mit Übernachtung (oder ≥ 24 h): An- und Abreisetag je Teiltag
      unabhängig von der Stundenzahl, jeder Tag dazwischen voller Tag (28 €).
    - Über Mitternacht ohne Übernachtung (< 24 h): bei insgesamt mehr als 8 h
      ein Teiltag, zugeordnet dem Tag mit der überwiegenden Abwesenheit.
    - § 7 Abs. 2: Dauert der Aufenthalt (ohne Hin- und Rückreisetag) länger als
      14 Tage, wird das Tagegeld vom 15. Aufenthaltstag an um 50 % vermindert.
    """
    if ende < start:
        return []
    stunden = _stunden_pro_tag(start, ende)
    total_hours = (ende - start).total_seconds() / 3600.0
    tage = [TagegeldTag(datum=d, stunden=h, art="") for d, h in stunden]

    if len(tage) == 1:
        if total_hours > 8:
            tage[0].art = "teil"
        return tage

    if mit_uebernachtung or total_hours >= 24:
        tage[0].art = "teil"
        tage[-1].art = "teil"
        aufenthalt = tage[1:-1]
        for t in aufenthalt:
            t.art = "voll"
        for t in aufenthalt[r.DAUERAUFENTHALT_REDUKTION_AB_TAG - 1 :]:
            t.reduziert = True
        return tage

    # Über Mitternacht, < 24 h, keine Übernachtung → höchstens ein Teiltag.
    if total_hours > 8:
        max(tage, key=lambda t: t.stunden).art = "teil"
    return tage


def tagegeld_tage(start: datetime, ende: datetime, mit_uebernachtung: bool = False) -> tuple[int, int]:
    """Liefert (volle_tage, teiltage) — Kurzform von ``tagegeld_kalender``."""
    tage = tagegeld_kalender(start, ende, mit_uebernachtung)
    return (sum(1 for t in tage if t.art == "voll"), sum(1 for t in tage if t.art == "teil"))


def _mit_uebernachtung(data: AbrechnungData) -> bool:
    u = data.uebernachtungen
    return bool(u.anzahl_pauschal or u.anzahl_unentgeltlich or u.anzahl_beleg or u.kosten_eur)


def _kuerzung_satz(fruehstueck: int, mittag: int, abend: int) -> float:
    return (
        fruehstueck * r.kuerzung_fruehstueck_eur()
        + mittag * r.kuerzung_mittagessen_eur()
        + abend * r.kuerzung_abendessen_eur()
    )


def berechnung(data: AbrechnungData) -> BerechneteWerte:
    """Führt die komplette Abrechnung durch."""
    rd = data.reise_details
    start = _parse_dt(rd.start_datum, rd.start_zeit)
    ende = _parse_dt(rd.ende_datum, rd.ende_zeit)
    verzicht = data.verzicht_erklaerung
    hinweise: list[str] = []
    reale_naechte = max(0, (ende.date() - start.date()).days)

    # 1. Tagegeld
    tage: list[TagegeldTag] = []
    if data.konfiguration_checkboxen.dienstgeschaeft_2km_umkreis:
        hinweise.append("Dienstgeschäft im 2-km-Umkreis: kein Tagegeld (§ 7 Abs. 1 Satz 4 NRKVO).")
    else:
        tage = tagegeld_kalender(start, ende, _mit_uebernachtung(data))
    tagegeld_brutto = sum(t.betrag for t in tage)
    if any(t.reduziert for t in tage):
        hinweise.append(
            f"Aufenthalt länger als 14 Tage: Tagegeld ab dem {r.DAUERAUFENTHALT_REDUKTION_AB_TAG}. "
            f"Aufenthaltstag um {r.DAUERAUFENTHALT_REDUKTION_PROZENT} % vermindert (§ 7 Abs. 2 NRKVO)."
        )

    # 2. Kürzungen für unentgeltliche Verpflegung (§ 7 Abs. 3): pro Kalendertag
    #    höchstens bis auf 0 — mit Tageszuordnung exakt, sonst nur insgesamt.
    v = data.verpflegung
    if v.tage:
        betrag_je_tag = {t.datum.strftime(DATE_FMT): t.betrag for t in tage}
        kuerzung = 0.0
        for vt in v.tage:
            if vt.datum not in betrag_je_tag:
                hinweise.append(f"Verpflegung am {vt.datum} liegt außerhalb der Reise und wird ignoriert.")
                continue
            soll = _kuerzung_satz(int(vt.fruehstueck), int(vt.mittag), int(vt.abend))
            kuerzung += min(soll, betrag_je_tag[vt.datum])
    else:
        kuerzung = min(_kuerzung_satz(v.fruehstueck_anzahl, v.mittag_anzahl, v.abend_anzahl), tagegeld_brutto)
    tagegeld_netto = tagegeld_brutto - kuerzung

    if verzicht.verzicht_tagegeld:
        tagegeld_brutto = kuerzung = tagegeld_netto = 0.0

    # 3. Übernachtungsgeld (§ 8): pauschal 20 €/Nacht für höchstens 14 Nächte
    #    je Dienstreise, plausibilisiert gegen die tatsächliche Zahl der Nächte.
    u = data.uebernachtungen
    naechte = min(u.anzahl_pauschal, r.UEBERNACHTUNG_PAUSCHAL_MAX_NAECHTE, reale_naechte)
    if naechte < u.anzahl_pauschal:
        hinweise.append(f"Pauschal-Nächte auf {naechte} gedeckelt (Reise hat {reale_naechte} Nächte, max. 14).")
    beleg_naechte = u.anzahl_beleg or (
        max(1, reale_naechte - u.anzahl_pauschal - u.anzahl_unentgeltlich) if u.kosten_eur else 0
    )
    pro_nacht = u.kosten_eur / beleg_naechte if beleg_naechte else 0.0
    begruendung_noetig = pro_nacht > r.UEBERNACHTUNG_BELEG_OHNE_BEGRUENDUNG_MAX_EUR
    if u.anzahl_pauschal + u.anzahl_beleg + u.anzahl_unentgeltlich > reale_naechte:
        hinweise.append(
            f"Es sind mehr Nächte angegeben (pauschal + Beleg + unentgeltlich) als die Reise hat ({reale_naechte})."
        )
    uebernachtungsgeld_pauschal = naechte * r.UEBERNACHTUNG_PAUSCHAL_EUR
    uebernachtung_beleg = u.kosten_eur
    if verzicht.verzicht_uebernachtungsgeld:
        # Übernachtungsgeld nach § 8 umfasst Pauschale UND nachgewiesene Kosten.
        uebernachtungsgeld_pauschal = uebernachtung_beleg = 0.0

    # 4. Wegstreckenentschädigung (§ 5): nur selbst gefahrene PKW-Strecken.
    #    Der Höchstbetrag 125 € gilt für den § 5-II-Anteil je Dienstreise,
    #    auch wenn eine Strecke nach § 5 III abgerechnet wird.
    weg_hin = weg_rueck = 0.0
    if not verzicht.verzicht_fahrtkosten:
        rest_klein = r.WEGSTRECKE_KLEIN_MAX_EUR
        gedeckelt = False
        beitraege = []
        for b, km in (
            (data.befoerderung.hinreise, data.wegstrecke.km_hinreise),
            (data.befoerderung.rueckreise, data.wegstrecke.km_rueckreise),
        ):
            if b.typ != "PKW" or not km:
                beitraege.append(0.0)
                continue
            betrag = km * r.wegstrecke_satz_eur(b.paragraph_5_nrkvo)
            if b.paragraph_5_nrkvo != "III":
                if betrag > rest_klein:
                    betrag, gedeckelt = rest_klein, True
                rest_klein -= betrag
            beitraege.append(betrag)
        weg_hin, weg_rueck = beitraege
        if gedeckelt:
            hinweise.append(
                f"Wegstreckenentschädigung nach § 5 II auf {r.WEGSTRECKE_KLEIN_MAX_EUR:.0f} € je Dienstreise gedeckelt."
            )
    wegstrecke = weg_hin + weg_rueck

    # 5. Belegte Beträge
    bb = data.beleg_betraege
    fahrkarte = bb.fahrkarte_eur + bb.zuschlaege_eur
    sonstige_fahrt = bb.sonstige_fahrt_eur
    if verzicht.verzicht_fahrtkosten:
        fahrkarte = sonstige_fahrt = 0.0
    sonstige_kosten = bb.sonstige_kosten_eur

    # 6. Zwischensumme
    zwischensumme = (
        tagegeld_netto
        + uebernachtungsgeld_pauschal
        + uebernachtung_beleg
        + wegstrecke
        + fahrkarte
        + sonstige_fahrt
        + sonstige_kosten
    )

    # 7. Auszahlbetrag (kann negativ sein → Rückzahlung)
    abzuege = data.abzuege.zuwendungen_eur + data.abzuege.reisekostenabschlag_eur + data.abzuege.eigenanteile_eur
    auszahlbetrag = zwischensumme - abzuege

    for h in hinweise:
        logger.info("Abrechnung: %s", h)

    voll = [t for t in tage if t.art == "voll"]
    teil = [t for t in tage if t.art == "teil"]
    return BerechneteWerte(
        tagegeld_brutto_eur=_round2(tagegeld_brutto),
        kuerzung_eur=_round2(kuerzung),
        tagegeld_netto_eur=_round2(tagegeld_netto),
        uebernachtungsgeld_pauschal_eur=_round2(uebernachtungsgeld_pauschal),
        wegstreckenentschaedigung_eur=_round2(wegstrecke),
        zwischensumme_eur=_round2(zwischensumme),
        auszahlbetrag_eur=_round2(auszahlbetrag),
        tagegeld_volle_tage=sum(1 for t in voll if not t.reduziert),
        tagegeld_teiltage=sum(1 for t in teil if not t.reduziert),
        tagegeld_reduzierte_tage=sum(1 for t in tage if t.reduziert),
        uebernachtung_pauschal_naechte=0 if verzicht.verzicht_uebernachtungsgeld else naechte,
        uebernachtung_beleg_eur=_round2(uebernachtung_beleg),
        uebernachtung_beleg_pro_nacht_eur=_round2(pro_nacht),
        begruendung_ueber_100_noetig=begruendung_noetig,
        wegstrecke_hin_eur=_round2(weg_hin),
        wegstrecke_rueck_eur=_round2(weg_rueck),
        fahrkarte_eur=_round2(fahrkarte),
        sonstige_fahrt_eur=_round2(sonstige_fahrt),
        sonstige_kosten_eur=_round2(sonstige_kosten),
        abzuege_eur=_round2(abzuege),
        hinweise=hinweise,
    )
