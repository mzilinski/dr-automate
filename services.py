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


# ---------- Persistenz und Lebenszyklus (Wizard + API) ----------

DATA_DIR = Path(os.environ.get("DR_AUTOMATE_DATA_DIR", "data"))

# Ab diesen Status ist der Antrag eingereicht/genehmigt und wird nicht still
# überschrieben (Wizard: neue Reise anlegen, API: 409).
ANTRAG_GESPERRT = ("genehmigt", "abgerechnet", "bezahlt")


class PersistError(Exception):
    """Reise gehört nicht dem User oder existiert nicht."""


class StatusKonflikt(Exception):
    """Aktion passt nicht zum Status der Reise (→ 409)."""


def parse_iso_date(value: str):
    """Akzeptiert ISO 'YYYY-MM-DD' oder deutsches 'DD.MM.YYYY', sonst None."""
    from datetime import datetime as _dt

    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return _dt.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def pdf_ablegen(inhalt: bytes, user_id: int, reise_id: int, filename: str) -> Path:
    """Schreibt ein PDF ins User-/Reise-Verzeichnis mit restriktiven Rechten (0700/0600)."""
    target_dir = DATA_DIR / "pdfs" / str(user_id) / str(reise_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Permissions explizit setzen — umask 022 würde sonst 0755 daraus machen.
    for d in (target_dir.parent, target_dir):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    target = target_dir / filename
    target.write_bytes(inhalt)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def _reise(s, user_id: int, reise_id: int):
    from models_db import Dienstreise

    reise = s.query(Dienstreise).filter(Dienstreise.id == reise_id, Dienstreise.user_id == user_id).first()
    if reise is None:
        raise PersistError(f"Dienstreise {reise_id} nicht gefunden")
    return reise


def antrag_speichern(
    user_id: int,
    reise_id: int | None,
    model: ReiseantragData,
    pdf: bytes | None,
    bei_sperre: str = "kopie",
) -> tuple[int, int | None]:
    """Legt eine Reise an oder ersetzt ihren Antrag. Gibt ``(reise_id, kopie_von)``
    zurück. Ist die Reise schon genehmigt, legt ``bei_sperre="kopie"`` (Wizard)
    eine neue Reise an, ``"ablehnen"`` (API) wirft StatusKonflikt."""
    from models_db import Dienstreise, DienstreiseStatus

    rd = model.reise_details
    titel = (rd.zweck or rd.zielort or "Dienstreise")[:200]
    kopie_von = None
    with SessionLocal() as s:
        reise = None
        if reise_id is not None:
            reise = _reise(s, user_id, reise_id)
            if reise.status.value in ANTRAG_GESPERRT:
                if bei_sperre == "ablehnen":
                    raise StatusKonflikt(f"Reise ist {reise.status.value} — der genehmigte Antrag bleibt unverändert.")
                kopie_von, reise = reise.id, None
        if reise is None:
            reise = Dienstreise(user_id=user_id, status=DienstreiseStatus.entwurf)
            s.add(reise)
        reise.titel = titel
        reise.zielort = rd.zielort
        reise.start_datum = parse_iso_date(rd.start_datum)
        reise.ende_datum = parse_iso_date(rd.ende_datum)
        reise.antrag_json = model.model_dump()
        s.flush()  # damit reise.id verfügbar ist
        if pdf is not None:
            reise.antrag_pdf_path = str(pdf_ablegen(pdf, user_id, reise.id, "antrag.pdf"))
        s.commit()
        return reise.id, kopie_von


def abrechnung_speichern(user_id: int, reise_id: int, model: AbrechnungData, pdf: bytes | None) -> int:
    """Speichert die (server-berechnete) Abrechnung zu einer Reise; Status → abgerechnet."""
    from datetime import datetime as _dt

    from models_db import Abrechnung, AbrechnungStatus, DienstreiseStatus

    with SessionLocal() as s:
        reise = _reise(s, user_id, reise_id)
        abr = s.query(Abrechnung).filter(Abrechnung.dienstreise_id == reise.id).first()
        if abr is None:
            abr = Abrechnung(dienstreise_id=reise.id, status=AbrechnungStatus.abgeschlossen)
            s.add(abr)
            s.flush()
        abr.abrechnung_json = model.model_dump()
        abr.status = AbrechnungStatus.abgeschlossen
        abr.generated_at = _dt.utcnow()
        if pdf is not None:
            abr.abrechnung_pdf_path = str(pdf_ablegen(pdf, user_id, reise.id, "abrechnung.pdf"))
        # bezahlt-Reisen NICHT auf abgerechnet zurückdrehen (User-Bestätigung
        # wiegt schwerer als ein erneuter PDF-Export).
        if reise.status != DienstreiseStatus.bezahlt:
            reise.status = DienstreiseStatus.abgerechnet
        s.commit()
        return abr.id


def _paperless(user_id: int, reise_id: int, art: str) -> None:
    """Genehmigter Antrag / bezahlte Abrechnung → Paperless, wenn im Profil
    eingeschaltet. Darf den eigentlichen Vorgang nie scheitern lassen."""
    import logging

    import paperless_sync

    try:
        paperless_sync.einreihen(user_id, reise_id, art)
    except Exception:
        logging.getLogger(__name__).exception("Paperless-Einreihen fehlgeschlagen")


def genehmigung_vermerken(user_id: int, reise_id: int, datum, aktenzeichen: str | None) -> None:
    from models_db import DienstreiseStatus

    with SessionLocal() as s:
        reise = _reise(s, user_id, reise_id)
        reise.genehmigung_datum = datum
        reise.genehmigung_aktenzeichen = (aktenzeichen or "").strip()[:100] or None
        if reise.status in (DienstreiseStatus.entwurf, DienstreiseStatus.eingereicht):
            reise.status = DienstreiseStatus.genehmigt
        s.commit()
    _paperless(user_id, reise_id, "antrag")


def bezahlt_vermerken(user_id: int, reise_id: int, datum) -> None:
    """Geldeingang vermerken — erst nach erzeugter Abrechnung."""
    from models_db import DienstreiseStatus

    with SessionLocal() as s:
        reise = _reise(s, user_id, reise_id)
        if reise.status not in (DienstreiseStatus.abgerechnet, DienstreiseStatus.bezahlt):
            raise StatusKonflikt("Geldeingang lässt sich erst nach erzeugter Abrechnung vermerken.")
        reise.bezahlt_datum = datum
        reise.status = DienstreiseStatus.bezahlt
        s.commit()
    _paperless(user_id, reise_id, "abrechnung")


def bezahlt_zuruecknehmen(user_id: int, reise_id: int) -> None:
    from models_db import DienstreiseStatus

    with SessionLocal() as s:
        reise = _reise(s, user_id, reise_id)
        reise.bezahlt_datum = None
        if reise.status == DienstreiseStatus.bezahlt:
            reise.status = DienstreiseStatus.abgerechnet
        s.commit()


def reise_loeschen(user_id: int, reise_id: int) -> None:
    """Reise samt Abrechnung (Cascade) und PDFs auf Disk entfernen."""
    with SessionLocal() as s:
        reise = _reise(s, user_id, reise_id)
        target_dir = DATA_DIR / "pdfs" / str(user_id) / str(reise.id)
        if target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        s.delete(reise)
        s.commit()


def reisen_liste(user_id: int, status: str | None = None) -> list:
    """Eigene Reisen (neueste zuerst), optional nach Status gefiltert."""
    from sqlalchemy.orm import joinedload

    from models_db import Dienstreise

    with SessionLocal() as s:
        q = s.query(Dienstreise).options(joinedload(Dienstreise.abrechnung)).filter(Dienstreise.user_id == user_id)
        if status:
            q = q.filter(Dienstreise.status == status)
        reisen = q.order_by(Dienstreise.created_at.desc()).all()
        s.expunge_all()
        return reisen


def reise_laden(user_id: int, reise_id: int):
    """Eine eigene Reise inkl. Abrechnung (detached) oder PersistError."""
    from sqlalchemy.orm import joinedload

    from models_db import Dienstreise

    with SessionLocal() as s:
        reise = (
            s.query(Dienstreise)
            .options(joinedload(Dienstreise.abrechnung))
            .filter(Dienstreise.id == reise_id, Dienstreise.user_id == user_id)
            .first()
        )
        if reise is None:
            raise PersistError(f"Dienstreise {reise_id} nicht gefunden")
        s.expunge_all()
        return reise
