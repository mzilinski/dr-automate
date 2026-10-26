"""
Pydantic Models für die JSON-Validierung von Dienstreise-Anträgen.

Diese Modelle definieren die erwartete Struktur der JSON-Daten und
validieren eingehende Anfragen strikt.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M"


class Meta(BaseModel):
    """Metadaten des Antrags."""

    description: str | None = "Reisekostenantrag NRKVO"
    version: str | None = "AUTO_GENERATED"


class Antragsteller(BaseModel):
    """Daten des Antragstellers."""

    name: str = Field(..., min_length=2, max_length=100)
    abteilung: str = Field(..., min_length=1, max_length=100)
    telefon: str = Field(..., min_length=5, max_length=50)
    adresse_privat: str = Field(..., min_length=5, max_length=200)
    # Amtsbezeichnung (z.B. „Studienrat") — nur für die Abrechnung relevant
    # (Signaturzeile „Unterschrift, Amtsbez./Datum"). Optional: nicht jeder
    # hat eine (Angestellte), darf den Antrag/die Abrechnung nie blockieren.
    amtsbezeichnung: str = Field(default="", max_length=100)
    mitreisender_name: str | None = ""


class Teilnehmer(BaseModel):
    """Weitere teilnehmende Person (Vordruck: „ggf. Angabe weiterer
    teilnehmender Personen", Slots Person.Name2–4 mit Dienststelle/OE und
    Telefon). Reise-spezifisch — kommt aus der KI-Extraktion (z.B.
    „Anreise mit Karsten Haim im PKW") oder wird im Wizard eingetragen."""

    name: str = Field(..., min_length=2, max_length=100)
    dienststelle: str = Field(default="", max_length=100)
    telefon: str = Field(default="", max_length=50)


class ReiseDetails(BaseModel):
    """Details zur Reise."""

    zielort: str = Field(..., min_length=3, max_length=300)
    reiseweg: str = Field(..., min_length=3, max_length=500)
    zweck: str = Field(..., min_length=3, max_length=500)

    start_datum: str = Field(..., description="Format: DD.MM.YYYY")
    start_zeit: str = Field(..., description="Format: HH:MM")

    ende_datum: str = Field(..., description="Format: DD.MM.YYYY")
    ende_zeit: str = Field(..., description="Format: HH:MM")

    dienstgeschaeft_beginn_datum: str = Field(..., description="Format: DD.MM.YYYY")
    dienstgeschaeft_beginn_zeit: str = Field(..., description="Format: HH:MM")
    dienstgeschaeft_ende_datum: str = Field(..., description="Format: DD.MM.YYYY")
    dienstgeschaeft_ende_zeit: str = Field(..., description="Format: HH:MM")

    # Weitere teilnehmende Personen (max. 3 Slots im Vordruck; Überzählige
    # werden vom Generator ignoriert). Zusammen mit dem Profil-Default
    # ``antragsteller.mitreisender_name`` dedupliziert.
    weitere_teilnehmer: list[Teilnehmer] = Field(default_factory=list)

    @field_validator("weitere_teilnehmer", mode="before")
    @classmethod
    def drop_empty_teilnehmer(cls, v):
        """Leere Zeilen aus dem Wizard (Name leer) still verwerfen."""
        if not v:
            return []
        out = []
        for t in v:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
            if (name or "").strip():
                out.append(t)
        return out

    @field_validator("start_datum", "ende_datum", "dienstgeschaeft_beginn_datum", "dienstgeschaeft_ende_datum")
    @classmethod
    def validate_datum(cls, v: str) -> str:
        """Validiert Format UND Plausibilität (z.B. lehnt 32.13.2026 ab)."""
        try:
            datetime.strptime(v, DATE_FMT)
        except ValueError as e:
            raise ValueError(f"Ungültiges Datum: '{v}'. Erwartet: DD.MM.YYYY") from e
        return v

    @field_validator("start_zeit", "ende_zeit", "dienstgeschaeft_beginn_zeit", "dienstgeschaeft_ende_zeit")
    @classmethod
    def validate_zeit(cls, v: str) -> str:
        """Validiert Format UND Plausibilität (z.B. lehnt 25:00 ab)."""
        try:
            datetime.strptime(v, TIME_FMT)
        except ValueError as e:
            raise ValueError(f"Ungültige Zeit: '{v}'. Erwartet: HH:MM") from e
        return v

    @model_validator(mode="after")
    def validate_zeitraum(self) -> "ReiseDetails":
        """Reise-Ende darf nicht vor Reise-Beginn liegen, gleiches gilt für Dienstgeschäft."""
        start = datetime.strptime(f"{self.start_datum} {self.start_zeit}", f"{DATE_FMT} {TIME_FMT}")
        ende = datetime.strptime(f"{self.ende_datum} {self.ende_zeit}", f"{DATE_FMT} {TIME_FMT}")
        if ende < start:
            raise ValueError(
                f"Reise-Ende ({self.ende_datum} {self.ende_zeit}) liegt vor Reise-Beginn "
                f"({self.start_datum} {self.start_zeit})"
            )

        dg_start = datetime.strptime(
            f"{self.dienstgeschaeft_beginn_datum} {self.dienstgeschaeft_beginn_zeit}", f"{DATE_FMT} {TIME_FMT}"
        )
        dg_ende = datetime.strptime(
            f"{self.dienstgeschaeft_ende_datum} {self.dienstgeschaeft_ende_zeit}", f"{DATE_FMT} {TIME_FMT}"
        )
        if dg_ende < dg_start:
            raise ValueError(
                f"Dienstgeschäft-Ende ({self.dienstgeschaeft_ende_datum} {self.dienstgeschaeft_ende_zeit}) "
                f"liegt vor Dienstgeschäft-Beginn ({self.dienstgeschaeft_beginn_datum} {self.dienstgeschaeft_beginn_zeit})"
            )
        return self


class ZusatzInfos(BaseModel):
    """Zusätzliche Informationen und Bemerkungen."""

    bemerkungen_feld: str | None = ""


class Befoerderungsart(BaseModel):
    """Art der Beförderung für Hin- oder Rückreise."""

    typ: str = Field(..., pattern=r"^(PKW|BAHN|BUS|DIENSTWAGEN|FLUG|MITFAHRT)$")
    paragraph_5_nrkvo: str = Field(default="II", pattern=r"^(II|III)$")
    # Bei MITFAHRT: Name der Person, in deren Auto man mitgefahren ist.
    # Landet im PDF-Feld "Mitfahrt_bei" (Hin) bzw. "Mitfahrt_bei1" (Rueck).
    mitfahrer_name: str = ""
    # Bei PKW: freitext-Begruendung, warum kein OePNV. Optional.
    begruendung_pkw: str = ""

    @field_validator("paragraph_5_nrkvo", mode="before")
    @classmethod
    def coerce_paragraph(cls, v: str) -> str:
        """Leere oder fehlende Werte → 'II' als Standard."""
        if not v or str(v).strip() == "":
            return "II"
        return v


class Befoerderung(BaseModel):
    """Beförderungsmittel für die Reise."""

    hinreise: Befoerderungsart
    rueckreise: Befoerderungsart
    sonderfall_begruendung_textfeld: str | None = ""


class KonfigurationCheckboxen(BaseModel):
    """Konfiguration der Checkboxen im Formular."""

    bahncard_business_vorhanden: bool = False
    bahncard_privat_vorhanden: bool = False
    # Rabattstufe der privaten BahnCard (25/50/100) fuer die BC25/BC50/BC100-
    # Checkboxen im Vordruck; kommt aus dem Profil (Slot _1).
    bahncard_privat_stufe: int | None = None
    bahncard_beschaffung_beantragt: bool = False
    # Freitext "Ja, und zwar" neben Beschaffung_Ja (welche Karte aufgegeben wurde).
    bahncard_beschaffung_karte: str | None = ""

    grosskundenrabatt_genutzt: bool = False
    grosskundenrabatt_begruendung_wenn_nein: str | None = ""

    # Ermaeßigungskarte (Monats-/Zeitkarte) fuer die Strecke — OBJ57/OBJ58
    # im Vordruck; bei Ja verlangt das Formular die genaue Strecke.
    ermaessigungskarte_vorhanden: bool = False
    ermaessigungskarte_strecke: str | None = ""

    weitere_ermaessigungen_vorhanden: bool = False
    dienstgeschaeft_2km_umkreis: bool = False
    anspruch_trennungsgeld: bool = False
    # Obj55-Checkbox im Vordruck: "Die Reisekosten werden von einer anderen
    # Person oder Stelle uebernommen" — nur bei echter Kostenuebernahme durch
    # Dritte (Veranstalter, andere Dienststelle), NICHT bei einer selbst
    # gezahlten Tagungsgebuehr inkl. Uebernachtung/Verpflegung (system_prompt.md
    # Abschnitt 4). Obj53/Obj54 daneben sind unentgeltliche Unterkunft/
    # Verpflegung des Amtes wegen.
    kosten_durch_andere_stelle: bool = False

    # Wird in ReiseantragData aus zusatz_infos.bemerkungen_feld abgeleitet.
    weitere_anmerkungen_checkbox_aktivieren: bool = False


class VerzichtErklaerung(BaseModel):
    """Verzichtserklärungen."""

    verzicht_tagegeld: bool = False
    verzicht_uebernachtungsgeld: bool = False
    verzicht_fahrtkosten: bool = False


class ReiseantragData(BaseModel):
    """Hauptmodell für den kompletten Reiseantrag."""

    _meta: Meta | None = None
    antragsteller: Antragsteller
    reise_details: ReiseDetails
    zusatz_infos: ZusatzInfos | None = ZusatzInfos()
    befoerderung: Befoerderung
    konfiguration_checkboxen: KonfigurationCheckboxen
    verzicht_erklaerung: VerzichtErklaerung | None = VerzichtErklaerung()
    # Das Unterschriftsdatum setzt der Generator (Erzeugungstag); ein
    # ``unterschrift``-Block aus älteren JSONs wird ignoriert.

    model_config = {
        "extra": "ignore",  # Ignoriere zusätzliche Felder
        "str_strip_whitespace": True,
    }

    @model_validator(mode="after")
    def anmerkungen_checkbox_aus_bemerkungen(self) -> "ReiseantragData":
        """„Weitere Anmerkungen" ist angekreuzt genau dann, wenn Bemerkungen
        im Formular stehen — deterministisch, keine KI-/Client-Aufgabe."""
        bemerkungen = (self.zusatz_infos.bemerkungen_feld if self.zusatz_infos else "") or ""
        self.konfiguration_checkboxen.weitere_anmerkungen_checkbox_aktivieren = bool(bemerkungen.strip())
        return self


# ============================================================
# Abrechnungs-Modelle (Reisekostenvordruck 035_002)
# ============================================================

RKR_CODES = ("DR", "VR", "AFR", "RPR", "RRS", "GNE", "SONSTIGE")


class Stammdaten(BaseModel):
    """Abrechnungs-spezifische Stammdaten (Profil-Erweiterung)."""

    # IBAN: max 22 Zeichen — der amtliche Vordruck 035-002 hat genau 22
    # Felder (IBAN1..IBAN22) und kann technisch keine laengeren IBANs
    # abbilden. Deckt DE/AT/UK/CH ab; nicht MT/SA/MU. Strikte Validation
    # ist sicherer als stilles Abschneiden im Generator.
    iban: str = Field(default="", max_length=22)
    bic: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    abrechnende_dienststelle: str = Field(default="", max_length=200)

    @field_validator("iban", mode="before")
    @classmethod
    def normalize_iban(cls, v: str) -> str:
        """IBAN: Whitespace entfernen, Großbuchstaben, Pflicht ≤ 22 Zeichen."""
        if not v:
            return ""
        cleaned = "".join(str(v).split()).upper()
        if len(cleaned) > 22:
            raise ValueError(
                f"IBAN ist {len(cleaned)} Zeichen — Vordruck 035-002 unterstützt "
                f"nur 22 Zeichen (DE/AT/UK). Längere IBANs (MT, SA, MU) sind "
                f"nicht abbildbar."
            )
        return cleaned


class AnlagenBeigefuegt(BaseModel):
    genehmigung_035_001: bool = False
    anlagen_035_003: bool = False


class Anordnung(BaseModel):
    dienststelle: str = Field(default="", max_length=200)
    datum: str = Field(default="", max_length=10)


class VerpflegungTag(BaseModel):
    """Unentgeltliche Mahlzeiten an einem Kalendertag (§ 7 Abs. 3 NRKVO)."""

    datum: str = Field(..., description="Format: DD.MM.YYYY")
    fruehstueck: bool = False
    mittag: bool = False
    abend: bool = False

    @field_validator("datum")
    @classmethod
    def validate_datum(cls, v: str) -> str:
        try:
            datetime.strptime(v, DATE_FMT)
        except ValueError as e:
            raise ValueError(f"Ungültiges Datum: '{v}'. Erwartet: DD.MM.YYYY") from e
        return v


class Verpflegung(BaseModel):
    """Unentgeltlich bereitgestellte Mahlzeiten — treibt die Tagegeld-Kürzung.

    Mit ``tage`` (Zuordnung je Kalendertag) wird die Kürzung pro Tag auf das
    Tagegeld dieses Tages gedeckelt; die Anzahl-Felder werden dann daraus
    abgeleitet. Ohne ``tage`` gelten die Anzahlen (nur Gesamt-Deckel).
    """

    fruehstueck_anzahl: int = Field(default=0, ge=0, le=99)
    mittag_anzahl: int = Field(default=0, ge=0, le=99)
    abend_anzahl: int = Field(default=0, ge=0, le=99)
    tage: list[VerpflegungTag] = Field(default_factory=list, max_length=400)

    @model_validator(mode="after")
    def counts_from_tage(self) -> "Verpflegung":
        if self.tage:
            self.fruehstueck_anzahl = sum(t.fruehstueck for t in self.tage)
            self.mittag_anzahl = sum(t.mittag for t in self.tage)
            self.abend_anzahl = sum(t.abend for t in self.tage)
        return self


class Uebernachtungen(BaseModel):
    """Übernachtungs-Posten."""

    anzahl_pauschal: int = Field(default=0, ge=0, le=99, description="Nächte ohne Beleg → 20 €/Nacht")
    anzahl_unentgeltlich: int = Field(
        default=0, ge=0, le=99, description="Vom Amt gestellte Nächte (kein Übernachtungsgeld)"
    )
    anzahl_beleg: int = Field(default=0, ge=0, le=99, description="Nächte mit Hotelbeleg (Basis für €/Nacht)")
    kosten_eur: float = Field(default=0.0, ge=0)
    begruendung_ueber_100: str = Field(default="", max_length=500)


class BelegBetraege(BaseModel):
    """Einzeln belegte Beträge (Belege gehen physisch zur Dienststelle)."""

    fahrkarte_eur: float = Field(default=0.0, ge=0)
    zuschlaege_eur: float = Field(default=0.0, ge=0)
    wagenklasse: str = Field(default="", max_length=50)
    sonstige_fahrt_eur: float = Field(default=0.0, ge=0)
    sonstige_fahrt_erlaeuterung: str = Field(default="", max_length=500)
    sonstige_kosten_eur: float = Field(default=0.0, ge=0)
    sonstige_kosten_erlaeuterung: str = Field(default="", max_length=500)


class Wegstrecke(BaseModel):
    """Kilometer für Wegstreckenentschädigung. Satz wird aus § 5 II/III abgeleitet."""

    km_hinreise: int = Field(default=0, ge=0, le=99999)
    km_rueckreise: int = Field(default=0, ge=0, le=99999)


class Abzuege(BaseModel):
    zuwendungen_eur: float = Field(default=0.0, ge=0)
    reisekostenabschlag_eur: float = Field(default=0.0, ge=0)
    eigenanteile_eur: float = Field(default=0.0, ge=0)
    eigenanteile_erlaeuterung: str = Field(default="", max_length=500)


class Flags(BaseModel):
    urlaub_ueber_5_tage: bool = False


class BerechneteWerte(BaseModel):
    """Server-autoritative Berechnung — wird beim Generieren ignoriert/überschrieben."""

    tagegeld_brutto_eur: float = 0.0
    kuerzung_eur: float = 0.0
    tagegeld_netto_eur: float = 0.0
    uebernachtungsgeld_pauschal_eur: float = 0.0
    wegstreckenentschaedigung_eur: float = 0.0
    zwischensumme_eur: float = 0.0
    auszahlbetrag_eur: float = 0.0

    # Aufschlüsselung für Wizard-Vorschau und PDF-Zeilen (Tage × Satz)
    tagegeld_volle_tage: int = 0
    tagegeld_teiltage: int = 0
    tagegeld_reduzierte_tage: int = 0
    uebernachtung_pauschal_naechte: int = 0
    uebernachtung_beleg_eur: float = 0.0
    uebernachtung_beleg_pro_nacht_eur: float = 0.0
    begruendung_ueber_100_noetig: bool = False
    wegstrecke_hin_eur: float = 0.0
    wegstrecke_rueck_eur: float = 0.0
    fahrkarte_eur: float = 0.0
    sonstige_fahrt_eur: float = 0.0
    sonstige_kosten_eur: float = 0.0
    abzuege_eur: float = 0.0
    hinweise: list[str] = Field(default_factory=list)


class AbrechnungData(BaseModel):
    """Hauptmodell für die Reisekostenabrechnung (Formular 035_002)."""

    _meta: Meta | None = None

    # 1:1 vom Antrag übernommen / vorbefüllt (auf der Abrechnung pflicht)
    stammdaten: Stammdaten
    antragsteller: Antragsteller
    reise_details: ReiseDetails
    befoerderung: Befoerderung
    konfiguration_checkboxen: KonfigurationCheckboxen
    verzicht_erklaerung: VerzichtErklaerung = VerzichtErklaerung()

    # Abrechnungs-spezifisch
    rkr: Literal["DR", "VR", "AFR", "RPR", "RRS", "GNE", "SONSTIGE"] = "DR"
    rrs_aktenzeichen: str = Field(default="", max_length=200)
    anlagen_beigefuegt: AnlagenBeigefuegt = AnlagenBeigefuegt()
    anordnung: Anordnung = Anordnung()
    verpflegung: Verpflegung = Verpflegung()
    uebernachtungen: Uebernachtungen = Uebernachtungen()
    beleg_betraege: BelegBetraege = BelegBetraege()
    wegstrecke: Wegstrecke = Wegstrecke()
    abzuege: Abzuege = Abzuege()
    flags: Flags = Flags()

    # Wird vom Server gesetzt
    berechnet: BerechneteWerte = BerechneteWerte()

    @field_validator("verzicht_erklaerung", mode="before")
    @classmethod
    def verzicht_none_to_default(cls, v):
        """Ältere Exporte enthalten ``null`` — gleichbedeutend mit „kein Verzicht"."""
        return v if v is not None else {}

    model_config = {
        "extra": "ignore",
        "str_strip_whitespace": True,
    }


def validate_abrechnung(data: dict) -> tuple[bool, str | AbrechnungData]:
    """Validiert die Abrechnungs-Daten gegen das Pydantic-Schema."""
    try:
        validated = AbrechnungData.model_validate(data)
        return True, validated
    except Exception as e:
        error_msg = str(e)
        if "validation error" in error_msg.lower():
            lines = error_msg.split("\n")
            errors = [line.strip() for line in lines if line.strip() and not line.startswith("For further")]
            error_msg = "; ".join(errors[:3])
        return False, error_msg


def validate_reiseantrag(data: dict) -> tuple[bool, str | ReiseantragData]:
    """
    Validiert die Reiseantrag-Daten gegen das Pydantic-Schema.

    Args:
        data: Die zu validierenden JSON-Daten als dict

    Returns:
        Tuple von (erfolg, ergebnis/fehlermeldung)
    """
    try:
        validated = ReiseantragData.model_validate(data)
        return True, validated
    except Exception as e:
        # Formatiere die Fehlermeldung benutzerfreundlich
        error_msg = str(e)
        if "validation error" in error_msg.lower():
            # Extrahiere die relevanten Teile
            lines = error_msg.split("\n")
            errors = [line.strip() for line in lines if line.strip() and not line.startswith("For further")]
            error_msg = "; ".join(errors[:3])  # Max 3 Fehler anzeigen
        return False, error_msg


# ============================================================
# Profil-autoritativer Merge (Antrag)
# ============================================================
#
# Antragsteller-, BahnCard- und Großkundenrabatt-Felder gehören dem
# Nutzerprofil, nicht der KI. Die KI gibt sie nicht mehr aus
# (system_prompt.md, Abschnitt 2 wird gestrippt); das System fügt sie hier
# autoritativ ein, BEVOR validiert wird.

# Prompt-Platzhalter aus system_prompt.md: [DEIN NAME], [DEINE ABTEILUNG],
# [DEINE TELEFONNUMMER], [DEINE PRIVATADRESSE], [OPTIONALER NAME].
_PLACEHOLDER_RE = re.compile(r"\[(?:DEIN|DEINE|OPTIONALER)\b[^\]]*\]")


def find_placeholder(obj) -> str | None:
    """Sucht rekursiv den ersten zurückgebliebenen Prompt-Platzhalter in
    String-Werten (defense-in-depth — soll nie ins PDF gelangen)."""
    if isinstance(obj, str):
        m = _PLACEHOLDER_RE.search(obj)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        for v in obj.values():
            hit = find_placeholder(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find_placeholder(v)
            if hit:
                return hit
    return None


def bahncards_to_konfig_flags(bahncards: dict | None) -> dict:
    """Mappt das Profil-``bahncards``-Blob (Slot _1 = Antragsteller) auf die
    profil-eigenen ``konfiguration_checkboxen``-Felder des Antrags.

    ``bahncard_beschaffung_beantragt`` wird im Profil nicht erfasst und
    daher nicht überschrieben.
    """
    bc = bahncards or {}
    stufe = 25 if bc.get("bc25_1") else 50 if bc.get("bc50_1") else 100 if bc.get("bc100_1") else None
    return {
        "bahncard_business_vorhanden": bool(bc.get("bcb_1")),
        "bahncard_privat_vorhanden": stufe is not None,
        "bahncard_privat_stufe": stufe,
        "grosskundenrabatt_genutzt": bool(bc.get("grosskunde_1")),
    }


_ANTRAGSTELLER_IDENTITY = ("name", "abteilung", "amtsbezeichnung", "telefon", "adresse_privat")


def apply_profile_authoritative(
    data: dict,
    antragsteller: dict | None = None,
    bahncards: dict | None = None,
) -> dict:
    """Überschreibt die profil-eigenen Felder im (Teil-)Antrag-JSON.

    Pro Identitätsfeld (Name/Abteilung/Telefon/Privatadresse) gewinnt der
    **nicht-leere** Profilwert — so kann ein eingeloggter Nutzer diese Felder
    nicht clientseitig fälschen, ein unvollständiges Profil blockiert aber
    keinen Antrag (eingereichter Wert bleibt als Fallback). Bei ``antragsteller
    is None`` (Gast ohne Server-Profil) bleibt der Block unverändert.

    ``mitreisender_name`` ist reise-spezifisch, nicht profil-autoritativ: der
    eingereichte Wert gewinnt, der Profil-Default dient nur als Fallback.

    BahnCard-/Großkundenrabatt-Flags kommen vollständig aus dem Profil
    (Abwesenheit = ``false`` ist korrekt). ``befoerderung`` bleibt unangetastet
    (Nutzer-Wahl aus der Reise-Abfrage).
    """
    merged = dict(data)
    if antragsteller is not None:
        out = dict(merged.get("antragsteller") or {})
        for k in _ANTRAGSTELLER_IDENTITY:
            v = (antragsteller.get(k) or "").strip()
            if v:
                out[k] = v
        if not (out.get("mitreisender_name") or "").strip():
            out["mitreisender_name"] = antragsteller.get("mitreisender_name", "") or ""
        merged["antragsteller"] = out
    if bahncards is not None:
        kc = dict(merged.get("konfiguration_checkboxen") or {})
        kc.update(bahncards_to_konfig_flags(bahncards))
        merged["konfiguration_checkboxen"] = kc
    return merged
