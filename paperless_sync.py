"""PDFs nach Paperless-ngx ablegen (plan-api-v1.md, Abschnitt 11).

Ablauf: ``einreihen()`` legt pro Reise und Art (antrag/abrechnung) eine Zeile in
``paperless_uploads`` an. Ein Hintergrund-Thread ruft jede Minute
``verarbeiten()`` auf: Upload über ``POST /api/documents/post_document/`` mit
dem Token des Users (dann gehört das Dokument ihm, und der KI-Workflow von
Paperless sieht seine Korrespondenten/Tags), danach Abfrage des Paperless-Tasks
bis SUCCESS/FAILURE. Fehler werden bis zu 5-mal mit wachsendem Abstand
wiederholt.

Ausgelöst wird automatisch beim Vermerken der Genehmigung (Antrag) und des
Geldeingangs (Abrechnung), wenn der User das im Profil eingeschaltet hat;
außerdem manuell über Dashboard und API.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

import requests

from db import SessionLocal
from models_db import Dienstreise, PaperlessUpload, UserProfile

logger = logging.getLogger(__name__)

ARTEN = ("antrag", "abrechnung")
MAX_VERSUCHE = 5
INTERVALL_SEKUNDEN = 60
TIMEOUT = 30
_TITEL = {"antrag": "Dienstreiseantrag", "abrechnung": "Reisekostenabrechnung"}


def basis_url() -> str:
    return os.environ.get("PAPERLESS_URL", "").rstrip("/")


def aktiv() -> bool:
    return bool(basis_url())


def _tag_name() -> str:
    return os.environ.get("PAPERLESS_TAG", "Dienstreise")


def _doctype_name(art: str) -> str:
    default = _TITEL[art]
    return os.environ.get(f"PAPERLESS_DOCTYPE_{art.upper()}", default)


class NichtEingerichtet(Exception):
    """Paperless ist nicht konfiguriert oder der User hat kein Token."""


def einreihen(user_id: int, reise_id: int, art: str, erzwingen: bool = False) -> str | None:
    """Reiht ein PDF zum Upload ein. Automatisch (``erzwingen=False``) nur, wenn
    der User „automatisch ablegen" eingeschaltet hat und noch kein Upload
    erfolgreich war; manuell immer. Gibt den neuen Status zurück oder None,
    wenn nichts eingereiht wurde."""
    if art not in ARTEN:
        raise ValueError(art)
    with SessionLocal() as s:
        profil = s.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if not aktiv() or profil is None or not profil.paperless_api_token:
            if erzwingen:
                raise NichtEingerichtet("Paperless ist nicht eingerichtet — Token im Profil hinterlegen.")
            return None
        if not erzwingen and not profil.paperless_auto:
            return None
        reise = s.query(Dienstreise).filter(Dienstreise.id == reise_id, Dienstreise.user_id == user_id).first()
        if reise is None:
            return None
        row = s.query(PaperlessUpload).filter_by(dienstreise_id=reise_id, art=art).first()
        if row is not None and row.status == "fertig" and not erzwingen:
            return None
        if row is None:
            row = PaperlessUpload(dienstreise_id=reise_id, art=art)
            s.add(row)
        row.status = "offen"
        row.versuche = 0
        row.naechster_versuch = datetime.utcnow()
        row.task_id = None
        row.meldung = None
        s.commit()
        logger.info("Paperless: %s von Reise %s eingereiht", art, reise_id)
        return "offen"


def status_je_reise(reise_ids: list[int]) -> dict[int, dict[str, PaperlessUpload]]:
    """{reise_id: {art: Upload}} für Dashboard und API."""
    if not reise_ids:
        return {}
    with SessionLocal() as s:
        rows = s.query(PaperlessUpload).filter(PaperlessUpload.dienstreise_id.in_(reise_ids)).all()
        s.expunge_all()
    out: dict[int, dict[str, PaperlessUpload]] = {}
    for r in rows:
        out.setdefault(r.dienstreise_id, {})[r.art] = r
    return out


# ---------- Abarbeitung ----------


def _headers(token: str) -> dict:
    # Keine feste API-Version: Paperless 3.x lehnt alte Versionen (z. B. 7) mit
    # 406 ab; ohne Angabe gilt der Standard der Instanz. Genutzt werden nur
    # stabile Felder (results/id, Task-UUID, status/related_document).
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def _id_fuer(http, token: str, endpoint: str, name: str) -> int | None:
    r = http.get(
        f"{basis_url()}/api/{endpoint}/", params={"name__iexact": name}, headers=_headers(token), timeout=TIMEOUT
    )
    r.raise_for_status()
    treffer = r.json().get("results") or []
    return treffer[0]["id"] if treffer else None


def _titel(reise: Dienstreise, art: str) -> str:
    datum = f" ({reise.start_datum:%d.%m.%Y})" if reise.start_datum else ""
    return f"{_TITEL[art]} {reise.titel}{datum}"[:128]


def _pdf_pfad(reise: Dienstreise, art: str) -> str | None:
    if art == "antrag":
        return reise.antrag_pdf_path
    return reise.abrechnung.abrechnung_pdf_path if reise.abrechnung else None


def _hochladen(http, row: PaperlessUpload, reise: Dienstreise, token: str) -> None:
    pfad = _pdf_pfad(reise, row.art)
    if not pfad or not os.path.isfile(pfad):
        raise FileNotFoundError(f"PDF für {row.art} fehlt")
    data: dict = {"title": _titel(reise, row.art)}
    if reise.start_datum:
        data["created"] = reise.start_datum.isoformat()
    tag = _id_fuer(http, token, "tags", _tag_name())
    if tag:
        data["tags"] = [tag]
    doctype = _id_fuer(http, token, "document_types", _doctype_name(row.art))
    if doctype:
        data["document_type"] = doctype
    with open(pfad, "rb") as f:
        r = http.post(
            f"{basis_url()}/api/documents/post_document/",
            headers=_headers(token),
            data=data,
            files={"document": (os.path.basename(pfad), f, "application/pdf")},
            timeout=TIMEOUT,
        )
    r.raise_for_status()
    row.task_id = str(r.json()).strip('"')[:64]
    row.status = "gesendet"
    row.meldung = None if tag else f"Tag '{_tag_name()}' fehlt in Paperless — ohne Tag abgelegt"
    row.naechster_versuch = datetime.utcnow() + timedelta(seconds=30)


def _dokument_id(task: dict) -> int | None:
    """Dokument-ID aus einem Paperless-Task — Paperless 2.x: ``related_document``,
    Paperless 3.x: ``related_document_ids`` bzw. ``result_data.document_id``."""
    kandidaten = [task.get("related_document"), *(task.get("related_document_ids") or [])]
    kandidaten.append((task.get("result_data") or {}).get("document_id"))
    for doc in kandidaten:
        if doc is not None and str(doc).isdigit():
            return int(doc)
    return None


def _task_pruefen(http, row: PaperlessUpload, token: str) -> None:
    r = http.get(f"{basis_url()}/api/tasks/", params={"task_id": row.task_id}, headers=_headers(token), timeout=TIMEOUT)
    r.raise_for_status()
    tasks = r.json()
    tasks = tasks.get("results", tasks) if isinstance(tasks, dict) else tasks
    if not tasks:
        row.naechster_versuch = datetime.utcnow() + timedelta(minutes=1)
        return
    t = tasks[0]
    status = (t.get("status") or "").upper()
    if status == "SUCCESS":
        row.status = "fertig"
        row.dokument_id = _dokument_id(t)
    elif status == "FAILURE":
        ergebnis = str(t.get("result") or t.get("result_message") or t.get("result_data") or "")
        if "duplicate" in ergebnis.lower():
            row.status = "fertig"
            row.meldung = "War bereits in Paperless vorhanden"
        else:
            row.status = "fehler"
            row.meldung = ergebnis[:500] or "Paperless meldet einen Fehler"
    else:
        row.naechster_versuch = datetime.utcnow() + timedelta(minutes=1)


def verarbeiten(http=requests, jetzt: datetime | None = None) -> int:
    """Ein Durchlauf über alle fälligen Zeilen. Gibt die Zahl der bearbeiteten zurück."""
    if not aktiv():
        return 0
    jetzt = jetzt or datetime.utcnow()
    n = 0
    with SessionLocal() as s:
        rows = (
            s.query(PaperlessUpload)
            .filter(PaperlessUpload.status.in_(("offen", "gesendet")), PaperlessUpload.naechster_versuch <= jetzt)
            .all()
        )
        for row in rows:
            reise = s.get(Dienstreise, row.dienstreise_id)
            profil = s.query(UserProfile).filter(UserProfile.user_id == reise.user_id).first() if reise else None
            token = profil.paperless_api_token if profil else None
            if reise is None or not token:
                row.status, row.meldung = "fehler", "Kein Paperless-Token im Profil"
                continue
            try:
                if row.status == "offen":
                    _hochladen(http, row, reise, token)
                else:
                    _task_pruefen(http, row, token)
            except Exception as e:  # Netzwerk, HTTP-Fehler, fehlendes PDF
                row.versuche += 1
                row.meldung = f"{type(e).__name__}: {str(e)[:400]}"
                if row.versuche >= MAX_VERSUCHE or isinstance(e, FileNotFoundError):
                    row.status = "fehler"
                else:
                    row.naechster_versuch = jetzt + timedelta(minutes=2**row.versuche)
                logger.warning("Paperless: Reise %s %s Versuch %s: %s", row.dienstreise_id, row.art, row.versuche, e)
            n += 1
        s.commit()
    return n


_thread: threading.Thread | None = None


def worker_starten() -> None:
    """Startet den Hintergrund-Thread einmal pro Prozess (gunicorn: 1 Worker)."""
    global _thread
    if not aktiv() or (_thread is not None and _thread.is_alive()):
        return

    def loop():
        while True:
            time.sleep(INTERVALL_SEKUNDEN)
            try:
                verarbeiten()
            except Exception:
                logger.exception("Paperless-Worker: Durchlauf fehlgeschlagen")

    _thread = threading.Thread(target=loop, name="paperless-sync", daemon=True)
    _thread.start()
    logger.info("Paperless-Worker gestartet (%s)", basis_url())
