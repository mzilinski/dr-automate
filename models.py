"""
Pydantic Models für die JSON-Validierung von Dienstreise-Anträgen.

Diese Modelle definieren die erwartete Struktur der JSON-Daten und
validieren eingehende Anfragen strikt.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re


class Meta(BaseModel):
    """Metadaten des Antrags."""
    description: Optional[str] = "Reisekostenantrag NRKVO"
    version: Optional[str] = "AUTO_GENERATED"


class Antragsteller(BaseModel):
    """Daten des Antragstellers."""
    name: str = Field(..., min_length=2, max_length=100)
    abteilung: str = Field(..., min_length=1, max_length=100)
    telefon: str = Field(..., min_length=5, max_length=50)
    adresse_privat: str = Field(..., min_length=5, max_length=200)
    mitreisender_name: Optional[str] = ""


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
    
    @field_validator('start_datum', 'ende_datum', 'dienstgeschaeft_beginn_datum', 'dienstgeschaeft_ende_datum')
    @classmethod
    def validate_datum(cls, v: str) -> str:
        """Validiert das Datumsformat DD.MM.YYYY."""
        if not re.match(r'^\d{2}\.\d{2}\.\d{4}$', v):
            raise ValueError(f"Ungültiges Datumsformat: '{v}'. Erwartet: DD.MM.YYYY")
        return v
    
    @field_validator('start_zeit', 'ende_zeit', 'dienstgeschaeft_beginn_zeit', 'dienstgeschaeft_ende_zeit')
    @classmethod
    def validate_zeit(cls, v: str) -> str:
        """Validiert das Zeitformat HH:MM."""
        if not re.match(r'^\d{2}:\d{2}$', v):
            raise ValueError(f"Ungültiges Zeitformat: '{v}'. Erwartet: HH:MM")
        return v


class ZusatzInfos(BaseModel):
    """Zusätzliche Informationen und Bemerkungen."""
    bemerkungen_feld: Optional[str] = ""


class Befoerderungsart(BaseModel):
    """Art der Beförderung für Hin- oder Rückreise."""
    typ: str = Field(..., pattern=r'^(PKW|BAHN|BUS|DIENSTWAGEN|FLUG)$')
    paragraph_5_nrkvo: str = Field(default="II", pattern=r'^(II|III)$')

    @field_validator('paragraph_5_nrkvo', mode='before')
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
    sonderfall_begruendung_textfeld: Optional[str] = ""


class KonfigurationCheckboxen(BaseModel):
    """Konfiguration der Checkboxen im Formular."""
    bahncard_business_vorhanden: bool = False
    bahncard_privat_vorhanden: bool = False
    bahncard_beschaffung_beantragt: bool = False
    
    grosskundenrabatt_genutzt: bool = False
    grosskundenrabatt_begruendung_wenn_nein: Optional[str] = ""
    
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
    datum_seite_2: Optional[str] = ""


class ReiseantragData(BaseModel):
    """Hauptmodell für den kompletten Reiseantrag."""
    _meta: Optional[Meta] = None
    antragsteller: Antragsteller
    reise_details: ReiseDetails
    zusatz_infos: Optional[ZusatzInfos] = ZusatzInfos()
    befoerderung: Befoerderung
    konfiguration_checkboxen: KonfigurationCheckboxen
    verzicht_erklaerung: Optional[VerzichtErklaerung] = VerzichtErklaerung()
    unterschrift: Optional[Unterschrift] = Unterschrift()
    
    model_config = {
        "extra": "ignore",  # Ignoriere zusätzliche Felder
        "str_strip_whitespace": True
    }


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
            lines = error_msg.split('\n')
            errors = [line.strip() for line in lines if line.strip() and not line.startswith('For further')]
            error_msg = "; ".join(errors[:3])  # Max 3 Fehler anzeigen
        return False, error_msg
