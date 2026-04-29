"""
Pydantic Models für die JSON-Validierung von Dienstreise-Anträgen.

Diese Modelle definieren die erwartete Struktur der JSON-Daten und
validieren eingehende Anfragen strikt.
"""

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
    mitreisender_name: str | None = ""


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

    typ: str = Field(..., pattern=r"^(PKW|BAHN|BUS|DIENSTWAGEN|FLUG)$")
    paragraph_5_nrkvo: str = Field(default="II", pattern=r"^(II|III)$")

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
    bahncard_beschaffung_beantragt: bool = False

    grosskundenrabatt_genutzt: bool = False
    grosskundenrabatt_begruendung_wenn_nein: str | None = ""

    weitere_ermaessigungen_vorhanden: bool = False
    dienstgeschaeft_2km_umkreis: bool = False
    anspruch_trennungsgeld: bool = False

    weitere_anmerkungen_checkbox_aktivieren: bool = False


class VerzichtErklaerung(BaseModel):
    """Verzichtserklärungen."""

    verzicht_tagegeld: bool = False
    verzicht_uebernachtungsgeld: bool = False
    verzicht_fahrtkosten: bool = False


class Unterschrift(BaseModel):
    """Unterschriftsdaten."""

    datum_seite_2: str | None = ""


class ReiseantragData(BaseModel):
    """Hauptmodell für den kompletten Reiseantrag."""

    _meta: Meta | None = None
    antragsteller: Antragsteller
    reise_details: ReiseDetails
    zusatz_infos: ZusatzInfos | None = ZusatzInfos()
    befoerderung: Befoerderung
    konfiguration_checkboxen: KonfigurationCheckboxen
    verzicht_erklaerung: VerzichtErklaerung | None = VerzichtErklaerung()
    unterschrift: Unterschrift | None = Unterschrift()

    model_config = {
        "extra": "ignore",  # Ignoriere zusätzliche Felder
        "str_strip_whitespace": True,
    }


# ============================================================
# Abrechnungs-Modelle (Reisekostenvordruck 035_002)
# ============================================================

RKR_CODES = ("DR", "VR", "AFR", "RPR", "RRS", "GNE", "SONSTIGE")


class Stammdaten(BaseModel):
    """Abrechnungs-spezifische Stammdaten (Profil-Erweiterung)."""

    iban: str = Field(default="", max_length=34)
    bic: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    abrechnende_dienststelle: str = Field(default="", max_length=200)

    @field_validator("iban", mode="before")
    @classmethod
    def normalize_iban(cls, v: str) -> str:
        """IBAN: Whitespace entfernen, Großbuchstaben."""
        if not v:
            return ""
        return "".join(str(v).split()).upper()


class AnlagenBeigefuegt(BaseModel):
    genehmigung_035_001: bool = False
    anlagen_035_003: bool = False


class Anordnung(BaseModel):
    dienststelle: str = Field(default="", max_length=200)
    datum: str = Field(default="", max_length=10)


class Verpflegung(BaseModel):
    """Anzahl unentgeltlich bereitgestellter Mahlzeiten — treibt Tagegeld-Kürzung."""

    fruehstueck_anzahl: int = Field(default=0, ge=0, le=99)
    mittag_anzahl: int = Field(default=0, ge=0, le=99)
    abend_anzahl: int = Field(default=0, ge=0, le=99)


class Uebernachtungen(BaseModel):
    """Übernachtungs-Posten."""

    anzahl_pauschal: int = Field(default=0, ge=0, le=99, description="Nächte ohne Beleg → 20 €/Nacht")
    anzahl_unentgeltlich: int = Field(default=0, ge=0, le=99, description="Vom Amt gestellte Nächte (kein Übernachtungsgeld)")
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


class AbrechnungData(BaseModel):
    """Hauptmodell für die Reisekostenabrechnung (Formular 035_002)."""

    _meta: Meta | None = None

    # 1:1 vom Antrag übernommen / vorbefüllt (auf der Abrechnung pflicht)
    stammdaten: Stammdaten
    antragsteller: Antragsteller
    reise_details: ReiseDetails
    befoerderung: Befoerderung
    konfiguration_checkboxen: KonfigurationCheckboxen
    verzicht_erklaerung: VerzichtErklaerung | None = VerzichtErklaerung()

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
