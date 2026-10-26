"""Fachlogik, die Wizard-Routen (app.py) und REST-API (api_v1.py) teilen:
Profil-Snapshot, Validierung, Berechnung und PDF-Erzeugung."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import generator
import generator_abrechnung
from abrechnung_calc import berechnung
from db import SessionLocal
from models import (
    AbrechnungData,
    ReiseantragData,
    apply_profile_authoritative,
    bahncards_to_konfig_flags,
    find_placeholder,
    validate_abrechnung,
    validate_reiseantrag,
)
from models_db import User, UserProfile

PDF_TEMPLATE_PATH = os.environ.get("PDF_TEMPLATE_PATH", os.path.join("forms", "DR-Antrag_035_001Stand4-2025pdf.pdf"))
PDF_TEMPLATE_ABRECHNUNG_PATH = os.environ.get(
    "PDF_TEMPLATE_ABRECHNUNG_PATH", os.path.join("forms", "Reisekostenvordruck.pdf")
)

# Pflichtangaben aus dem Profil je Vorgang (Feld → Anzeigename)
_PFLICHT_ANTRAG = {
    "name": "Vor-/Nachname",
    "abteilung": "Abteilung",
    "telefon": "Telefon",
    "adresse_privat": "Privatadresse",
}
_PFLICHT_ABRECHNUNG_STAMM = {"iban": "IBAN", "bic": "BIC", "abrechnende_dienststelle": "Abrechnende Dienststelle"}


class FachlicherFehler(ValueError):
    """Eingabe ist formal gültig, aber fachlich nicht verarbeitbar (→ 422)."""

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or []


def profil_daten(user: User) -> dict:
    """Profil-Snapshot im Format der internen Modelle: ``antragsteller``,
    ``stammdaten`` und die profil-eigenen ``konfiguration``-Flags (BahnCards,
    Großkundenrabatt). Fehlt das Profil, sind die Werte leer."""
    with SessionLocal() as s:
        p = s.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    p = p or UserProfile(user_id=user.id)
    name = " ".join(x for x in (p.vorname, p.nachname) if x).strip() or (user.display_name or "")
    return {
        "antragsteller": {
            "name": name,
            "abteilung": p.abteilung or "",
            "amtsbezeichnung": p.amtsbezeichnung or "",
            "telefon": p.telefon or "",
            "adresse_privat": p.adresse_privat or "",
            "mitreisender_name": p.mitreisender_name_default or "",
        },
        "stammdaten": {
            "iban": p.iban or "",
            "bic": p.bic or "",
            "email": p.email or user.email or "",
            "abrechnende_dienststelle": p.abrechnende_dienststelle or "",
        },
        "konfiguration": bahncards_to_konfig_flags(p.bahncards),
    }


def pruefe_profil(profil: dict, fuer: str) -> None:
    """Wirft FachlicherFehler, wenn Pflichtangaben im Profil fehlen."""
    fehlend = [txt for k, txt in _PFLICHT_ANTRAG.items() if not profil["antragsteller"].get(k)]
    if fuer == "abrechnung_pdf":
        fehlend += [txt for k, txt in _PFLICHT_ABRECHNUNG_STAMM.items() if not profil["stammdaten"].get(k)]
    if fehlend:
        raise FachlicherFehler(
            "Profil unvollständig — bitte unter /profil ergänzen: " + ", ".join(fehlend),
            [{"loc": ["profil", f], "msg": "fehlt"} for f in fehlend],
        )


def antrag_validieren(data: dict, antragsteller: dict | None = None, bahncards: dict | None = None) -> ReiseantragData:
    """Profil-autoritativer Merge, Platzhalter-Prüfung, Pydantic-Validierung."""
    if antragsteller is not None or bahncards is not None:
        data = apply_profile_authoritative(data, antragsteller=antragsteller, bahncards=bahncards)
    platzhalter = find_placeholder(data)
    if platzhalter:
        raise FachlicherFehler(f"Platzhalter '{platzhalter}' im Antrag — bitte Profil ausfüllen.")
    ok, result = validate_reiseantrag(data)
    if not ok:
        raise FachlicherFehler(f"Validierungsfehler: {result}")
    return result


def abrechnung_validieren(data: dict) -> AbrechnungData:
    ok, result = validate_abrechnung(data)
    if not ok:
        raise FachlicherFehler(f"Validierungsfehler: {result}")
    result.berechnet = berechnung(result)
    return result


def _pdf_erzeugen(fill, *args) -> tuple[str, bytes]:
    temp_dir = tempfile.mkdtemp()
    try:
        path = fill(*args, temp_dir)
        return os.path.basename(path), Path(path).read_bytes()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def antrag_pdf(model: ReiseantragData) -> tuple[str, bytes]:
    """(Dateiname, PDF-Bytes) des ausgefüllten Antrags."""
    return _pdf_erzeugen(generator.fill_pdf, model.model_dump(), PDF_TEMPLATE_PATH)


def abrechnung_pdf(model: AbrechnungData) -> tuple[str, bytes]:
    """(Dateiname, PDF-Bytes) der ausgefüllten Abrechnung."""
    return _pdf_erzeugen(generator_abrechnung.fill_pdf, model, PDF_TEMPLATE_ABRECHNUNG_PATH)
