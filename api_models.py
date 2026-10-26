"""Schema der REST-API v1 (plan-api-v1.md, Abschnitt 4).

Eigene, eingefrorene Modelle mit ``extra="forbid"`` (Tippfehler → 422) und
ein Mapping auf die internen Wizard-Modelle (``models.py``). Antragsteller,
Bankdaten und BahnCards kommen nie aus dem Request, sondern aus dem Profil.

``ReiseDetailsV1``/``TeilnehmerV1`` erben die Validierung der internen Modelle
(identische Bedeutung). Ändert sich das interne Modell inkompatibel, werden
sie hier abgekoppelt — der v1-Vertrag bleibt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models import BerechneteWerte, ReiseDetails, Teilnehmer

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)

Verkehrsmittel = Literal["PKW", "BAHN", "BUS", "DIENSTWAGEN", "FLUG", "MITFAHRT"]
Datum = Field(pattern=r"^\d{2}\.\d{2}\.\d{4}$", description="DD.MM.YYYY")


class V1(BaseModel):
    model_config = _STRICT


class TeilnehmerV1(Teilnehmer):
    model_config = _STRICT


class ReiseDetailsV1(ReiseDetails):
    model_config = _STRICT
    weitere_teilnehmer: list[TeilnehmerV1] = Field(default_factory=list, max_length=20)


class StreckeV1(V1):
    typ: Verkehrsmittel
    paragraph_5_nrkvo: Literal["II", "III"] = Field("II", description="nur bei PKW relevant")
    mitfahrer_name: str = Field("", max_length=100, description="nur bei MITFAHRT")


class BefoerderungV1(V1):
    hinreise: StreckeV1
    rueckreise: StreckeV1
    begruendung: str = Field("", max_length=500, description="Pflicht bei PKW § 5 III und bei FLUG")


class AngabenV1(V1):
    dienstgeschaeft_2km_umkreis: bool = False
    anspruch_trennungsgeld: bool = False
    kosten_durch_andere_stelle: bool = False


class VerzichtV1(V1):
    tagegeld: bool = False
    uebernachtungsgeld: bool = False
    fahrtkosten: bool = False


class AntragV1(V1):
    """Dienstreiseantrag (Formular 035_001) ohne Antragsteller-Daten."""

    reise_details: ReiseDetailsV1
    befoerderung: BefoerderungV1
    bemerkungen: str = Field("", max_length=2000, description="erscheint unverändert im Formular, \\n für Umbrüche")
    angaben: AngabenV1 = AngabenV1()
    verzicht: VerzichtV1 = VerzichtV1()


# ---------- Abrechnung ----------


class VerpflegungTagV1(V1):
    datum: str = Datum
    fruehstueck: bool = False
    mittag: bool = False
    abend: bool = False


class VerpflegungV1(V1):
    """Unentgeltliche Mahlzeiten — entweder je Kalendertag (``tage``, genauer)
    oder als Anzahlen."""

    fruehstueck: int = Field(0, ge=0, le=99)
    mittag: int = Field(0, ge=0, le=99)
    abend: int = Field(0, ge=0, le=99)
    tage: list[VerpflegungTagV1] = Field(default_factory=list, max_length=400)


class UebernachtungenV1(V1):
    pauschal_naechte: int = Field(0, ge=0, le=99, description="ohne Beleg, 20 €/Nacht")
    unentgeltliche_naechte: int = Field(0, ge=0, le=99)
    beleg_naechte: int = Field(0, ge=0, le=99)
    beleg_kosten_eur: float = Field(0, ge=0)
    begruendung_ueber_100: str = Field("", max_length=500)


class BelegeV1(V1):
    fahrkarte_eur: float = Field(0, ge=0)
    zuschlaege_eur: float = Field(0, ge=0)
    wagenklasse: str = Field("", max_length=50)
    sonstige_fahrt_eur: float = Field(0, ge=0)
    sonstige_fahrt_erlaeuterung: str = Field("", max_length=500)
    sonstige_kosten_eur: float = Field(0, ge=0)
    sonstige_kosten_erlaeuterung: str = Field("", max_length=500)


class WegstreckeV1(V1):
    km_hinreise: int = Field(0, ge=0, le=99999)
    km_rueckreise: int = Field(0, ge=0, le=99999)


class AbzuegeV1(V1):
    zuwendungen_eur: float = Field(0, ge=0)
    reisekostenabschlag_eur: float = Field(0, ge=0)
    eigenanteile_eur: float = Field(0, ge=0)
    eigenanteile_erlaeuterung: str = Field("", max_length=500)


class BahnV1(V1):
    ermaessigungskarte_strecke: str = Field("", max_length=200, description="gesetzt = Ermäßigungskarte vorhanden")
    grosskundenrabatt_begruendung: str = Field("", max_length=500, description="bei Bahnreise ohne Großkundenrabatt")


class AnordnungV1(V1):
    dienststelle: str = Field("", max_length=200)
    datum: str = Field("", max_length=10, description="DD.MM.YYYY oder leer")


class AnlagenV1(V1):
    genehmigung_035_001: bool = False
    anlagen_035_003: bool = False


class AbrechnungV1(V1):
    """Reisekostenabrechnung (Formular 035_002) ohne Antragsteller-/Bankdaten."""

    reise_details: ReiseDetailsV1
    befoerderung: BefoerderungV1
    rkr: Literal["DR", "VR", "AFR", "RPR", "RRS", "GNE", "SONSTIGE"] = "DR"
    rrs_aktenzeichen: str = Field("", max_length=200)
    anordnung: AnordnungV1 = AnordnungV1()
    anlagen: AnlagenV1 = AnlagenV1()
    angaben: AngabenV1 = AngabenV1()
    bahn: BahnV1 = BahnV1()
    verzicht: VerzichtV1 = VerzichtV1()
    verpflegung: VerpflegungV1 = VerpflegungV1()
    uebernachtungen: UebernachtungenV1 = UebernachtungenV1()
    belege: BelegeV1 = BelegeV1()
    wegstrecke: WegstreckeV1 = WegstreckeV1()
    abzuege: AbzuegeV1 = AbzuegeV1()
    urlaub_ueber_5_tage: bool = False


class BerechnungV1(BerechneteWerte):
    """Ergebnis der NRKVO-Berechnung (Beträge in EUR, Hinweise als Text)."""


class EntfernungV1(V1):
    von: str = Field(..., min_length=3, max_length=300)
    nach: str = Field(..., min_length=3, max_length=300)


# ---------- Mapping v1 → intern ----------


def _befoerderung(b: BefoerderungV1) -> dict:
    def strecke(s: StreckeV1) -> dict:
        d = {"typ": s.typ, "paragraph_5_nrkvo": s.paragraph_5_nrkvo if s.typ == "PKW" else "II"}
        if s.typ == "MITFAHRT":
            d["mitfahrer_name"] = s.mitfahrer_name
        return d

    return {
        "hinreise": strecke(b.hinreise),
        "rueckreise": strecke(b.rueckreise),
        "sonderfall_begruendung_textfeld": b.begruendung,
    }


def _verzicht(v: VerzichtV1) -> dict:
    return {
        "verzicht_tagegeld": v.tagegeld,
        "verzicht_uebernachtungsgeld": v.uebernachtungsgeld,
        "verzicht_fahrtkosten": v.fahrtkosten,
    }


def antrag_to_internal(a: AntragV1, profil: dict) -> dict:
    """``profil`` aus ``services.profil_daten`` — liefert Antragsteller und BahnCards."""
    return {
        "antragsteller": profil["antragsteller"],
        "reise_details": a.reise_details.model_dump(),
        "zusatz_infos": {"bemerkungen_feld": a.bemerkungen},
        "befoerderung": _befoerderung(a.befoerderung),
        "konfiguration_checkboxen": {**profil["konfiguration"], **a.angaben.model_dump()},
        "verzicht_erklaerung": _verzicht(a.verzicht),
    }


def abrechnung_to_internal(a: AbrechnungV1, profil: dict) -> dict:
    v, u, b = a.verpflegung, a.uebernachtungen, a.belege
    return {
        "stammdaten": profil["stammdaten"],
        "antragsteller": profil["antragsteller"],
        "reise_details": a.reise_details.model_dump(),
        "befoerderung": _befoerderung(a.befoerderung),
        "konfiguration_checkboxen": {
            **profil["konfiguration"],
            **a.angaben.model_dump(),
            "ermaessigungskarte_vorhanden": bool(a.bahn.ermaessigungskarte_strecke),
            "ermaessigungskarte_strecke": a.bahn.ermaessigungskarte_strecke,
            "grosskundenrabatt_begruendung_wenn_nein": a.bahn.grosskundenrabatt_begruendung,
        },
        "verzicht_erklaerung": _verzicht(a.verzicht),
        "rkr": a.rkr,
        "rrs_aktenzeichen": a.rrs_aktenzeichen,
        "anordnung": a.anordnung.model_dump(),
        "anlagen_beigefuegt": a.anlagen.model_dump(),
        "verpflegung": {
            "fruehstueck_anzahl": v.fruehstueck,
            "mittag_anzahl": v.mittag,
            "abend_anzahl": v.abend,
            "tage": [t.model_dump() for t in v.tage],
        },
        "uebernachtungen": {
            "anzahl_pauschal": u.pauschal_naechte,
            "anzahl_unentgeltlich": u.unentgeltliche_naechte,
            "anzahl_beleg": u.beleg_naechte,
            "kosten_eur": u.beleg_kosten_eur,
            "begruendung_ueber_100": u.begruendung_ueber_100,
        },
        "beleg_betraege": b.model_dump(),
        "wegstrecke": a.wegstrecke.model_dump(),
        "abzuege": a.abzuege.model_dump(),
        "flags": {"urlaub_ueber_5_tage": a.urlaub_ueber_5_tage},
    }


def antrag_from_internal(d: dict) -> dict:
    """Gespeicherten Antrag (internes Format) als v1-JSON ausgeben."""
    rd = d.get("reise_details") or {}
    bf = d.get("befoerderung") or {}
    kc = d.get("konfiguration_checkboxen") or {}
    vz = d.get("verzicht_erklaerung") or {}

    def strecke(s: dict) -> dict:
        return {
            "typ": s.get("typ", "PKW"),
            "paragraph_5_nrkvo": s.get("paragraph_5_nrkvo") or "II",
            "mitfahrer_name": s.get("mitfahrer_name") or "",
        }

    return {
        "reise_details": {k: rd.get(k) for k in ReiseDetailsV1.model_fields},
        "befoerderung": {
            "hinreise": strecke(bf.get("hinreise") or {}),
            "rueckreise": strecke(bf.get("rueckreise") or {}),
            "begruendung": bf.get("sonderfall_begruendung_textfeld") or "",
        },
        "bemerkungen": (d.get("zusatz_infos") or {}).get("bemerkungen_feld") or "",
        "angaben": {k: bool(kc.get(k)) for k in AngabenV1.model_fields},
        "verzicht": {
            "tagegeld": bool(vz.get("verzicht_tagegeld")),
            "uebernachtungsgeld": bool(vz.get("verzicht_uebernachtungsgeld")),
            "fahrtkosten": bool(vz.get("verzicht_fahrtkosten")),
        },
    }


def abrechnung_from_internal(d: dict) -> dict:
    """Gespeicherte Abrechnung (internes Format) als v1-JSON ausgeben."""
    base = antrag_from_internal(d)
    kc = d.get("konfiguration_checkboxen") or {}
    v = d.get("verpflegung") or {}
    u = d.get("uebernachtungen") or {}
    return {
        "reise_details": base["reise_details"],
        "befoerderung": base["befoerderung"],
        "rkr": d.get("rkr") or "DR",
        "rrs_aktenzeichen": d.get("rrs_aktenzeichen") or "",
        "anordnung": d.get("anordnung") or {"dienststelle": "", "datum": ""},
        "anlagen": d.get("anlagen_beigefuegt") or {"genehmigung_035_001": False, "anlagen_035_003": False},
        "angaben": {k: bool(kc.get(k)) for k in AngabenV1.model_fields},
        "bahn": {
            "ermaessigungskarte_strecke": kc.get("ermaessigungskarte_strecke") or "",
            "grosskundenrabatt_begruendung": kc.get("grosskundenrabatt_begruendung_wenn_nein") or "",
        },
        "verzicht": base["verzicht"],
        "verpflegung": {
            "fruehstueck": v.get("fruehstueck_anzahl", 0),
            "mittag": v.get("mittag_anzahl", 0),
            "abend": v.get("abend_anzahl", 0),
            "tage": v.get("tage") or [],
        },
        "uebernachtungen": {
            "pauschal_naechte": u.get("anzahl_pauschal", 0),
            "unentgeltliche_naechte": u.get("anzahl_unentgeltlich", 0),
            "beleg_naechte": u.get("anzahl_beleg", 0),
            "beleg_kosten_eur": u.get("kosten_eur", 0),
            "begruendung_ueber_100": u.get("begruendung_ueber_100") or "",
        },
        "belege": d.get("beleg_betraege") or {},
        "wegstrecke": d.get("wegstrecke") or {},
        "abzuege": d.get("abzuege") or {},
        "urlaub_ueber_5_tage": bool((d.get("flags") or {}).get("urlaub_ueber_5_tage")),
    }
