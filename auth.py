"""
Authelia-ForwardAuth-Integration fuer dr-automate.

Wenn ``TRUST_REMOTE_USER_HEADER=true`` gesetzt ist (Produktion hinter Traefik),
lesen wir die Identitaet aus den HTTP-Headern, die Authelia gesetzt hat:

    Remote-User    — eindeutiger Benutzername (Authelia-Key)
    Remote-Email   — E-Mail
    Remote-Name    — Display-Name
    Remote-Groups  — Komma-separierte Gruppen-Liste

Trust-Boundary: Default ist ``false``, damit ein lokal gestarteter
Server (oder ein Test) den Header NICHT respektiert. Sonst koennte
jeder mit ``curl -H 'Remote-User: malte' http://localhost:5001/dashboard``
fremde Identitaeten annehmen.

In Produktion garantiert Traefik, dass externe Clients diese Header
NICHT senden koennen — sie werden von der ForwardAuth-Middleware ueber-
schrieben.

Identitaet nur auf geschuetzten Pfaden: Gast-Pfade (/, /generate, /extract,
...) sind in Authelia per ``bypass`` offen, und dort schickt Authelia die
``Remote-*``-Header auch fuer Sessions, die erst den ersten Faktor (Passwort)
haben (Authelia 4.39: ``isAuthzResult`` → Bypass = authorized,
``handleAuthzAuthorizedStandard`` setzt die Header unabhaengig vom Level).
Die App vertraut den Headern deshalb nur auf ``GESCHUETZTE_PFADE`` — dort
verlangt Authelia two_factor. Eine Allowlist statt der Bypass-Liste, damit
ein spaeter ergaenzter Bypass kein Loch reisst. Eingeloggte Nutzer landen ueber
eine Weiterleitung von den Gast-Seiten auf ``/konto/…``.

Zusaetzlich prueft ``DR_AUTOMATE_ALLOWED_GROUPS`` (komma-separiert)
``Remote-Groups``; wer keine der Gruppen hat, wird als Gast behandelt.
Leer = keine Pruefung (Dev/Tests).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import api_keys
from db import SessionLocal
from models_db import User, UserProfile

logger = logging.getLogger(__name__)


# Nur hier wird Remote-User vertraut (Authelia: two_factor, kein Bypass).
GESCHUETZTE_PFADE = ("/konto", "/dashboard", "/dienstreisen", "/profil", "/admin")


def pfad_geschuetzt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in GESCHUETZTE_PFADE)


# last_login_at hoechstens so oft schreiben — sonst committet jeder Request.
LAST_LOGIN_GRANULARITY = timedelta(minutes=15)


def _trust_header() -> bool:
    return current_app.config.get("TRUST_REMOTE_USER_HEADER", False)


def allowed_groups() -> set[str]:
    raw = current_app.config.get("ALLOWED_GROUPS")
    if raw is None:
        raw = os.environ.get("DR_AUTOMATE_ALLOWED_GROUPS", "")
    return {g.strip() for g in raw.split(",") if g.strip()}


def request_groups() -> set[str]:
    """Authelia-Gruppen des aktuellen Requests (leer ohne vertrauten Header)."""
    if not _trust_header():
        return set()
    return {g.strip() for g in request.headers.get("Remote-Groups", "").split(",") if g.strip()}


def _upsert_user(remote_user: str, email: str | None, display_name: str | None, api_berechtigt: bool = False) -> User:
    """Idempotent: legt User an oder aktualisiert email/name/last_login_at.

    Schreibt nur, wenn sich etwas geaendert hat oder der letzte Login laenger
    als ``LAST_LOGIN_GRANULARITY`` zurueckliegt. Mit ``api_berechtigt`` (User
    ist in einer API-Gruppe) wird ``api_berechtigt_bis`` verlaengert. Zwei parallele Erst-Requests
    (IntegrityError auf remote_user) loesen sich ueber erneutes Lesen auf.
    """
    with SessionLocal() as session:
        user = session.execute(select(User).where(User.remote_user == remote_user)).scalar_one_or_none()
        now = datetime.utcnow()
        api_bis = now + api_keys.BERECHTIGUNG_DAUER if api_berechtigt else None
        if user is None:
            user = User(
                remote_user=remote_user,
                email=email,
                display_name=display_name,
                last_login_at=now,
                api_berechtigt_bis=api_bis,
            )
            session.add(user)
            try:
                session.flush()
                # leeres Profil anlegen, damit /profil nie 404'd
                session.add(UserProfile(user_id=user.id))
                session.commit()
                logger.info("Neuer User angelegt: remote_user=%s", remote_user)
            except IntegrityError:
                session.rollback()
                user = session.execute(select(User).where(User.remote_user == remote_user)).scalar_one()
        else:
            # Header-Updates uebernehmen (Authelia hat ggf. Display-Name geaendert)
            changed = False
            if email and user.email != email:
                user.email = email
                changed = True
            if display_name and user.display_name != display_name:
                user.display_name = display_name
                changed = True
            stale = user.last_login_at is None or now - user.last_login_at > LAST_LOGIN_GRANULARITY
            if stale:
                user.last_login_at = now
            if api_bis and (
                user.api_berechtigt_bis is None
                or api_bis - user.api_berechtigt_bis > api_keys.BERECHTIGUNG_GRANULARITAET
            ):
                user.api_berechtigt_bis = api_bis
                stale = True
            if changed or stale:
                session.commit()
            if changed:
                logger.info("User aktualisiert: remote_user=%s", remote_user)
        session.refresh(user)
        # Detach: g.current_user soll keine offene Session halten
        session.expunge(user)
        return user


def load_current_user() -> User | None:
    """Liest die Identitaet aus Authelia-Headern. Vor jedem Request aufrufen."""
    # Gast-Pfade (inkl. /api/v1, das per Bearer-Key authentifiziert) nie.
    if not _trust_header() or not pfad_geschuetzt(request.path):
        return None
    remote_user = request.headers.get("Remote-User", "").strip()
    if not remote_user:
        return None
    # Header sind ASCII per Spec; defensiv kuerzen.
    remote_user = remote_user[:128]
    gruppen = request_groups()
    erlaubt = allowed_groups()
    if erlaubt and not gruppen & erlaubt:
        logger.info("Remote-User %s ohne dr-automate-Gruppe — Gast-Modus", remote_user)
        return None
    email = (request.headers.get("Remote-Email", "") or "").strip()[:254] or None
    display_name = (request.headers.get("Remote-Name", "") or "").strip()[:200] or None
    try:
        return _upsert_user(remote_user, email, display_name, api_berechtigt=bool(gruppen & api_keys.api_groups()))
    except Exception:  # pragma: no cover
        logger.exception("User-Upsert fehlgeschlagen fuer remote_user=%s", remote_user)
        return None


def session_auf_gastpfad() -> bool:
    """Bringt ein Request auf einem Gast-Pfad eine Authelia-Session einer
    erlaubten Gruppe mit? Dann leitet die App GET-Seiten nach /konto/… um, wo
    Authelia den zweiten Faktor verlangt. Die Header selbst werden hier NICHT
    als Identitaet verwendet (Level unbekannt)."""
    if not _trust_header() or pfad_geschuetzt(request.path):
        return False
    if not request.headers.get("Remote-User", "").strip():
        return False
    erlaubt = allowed_groups()
    return not erlaubt or bool(request_groups() & erlaubt)


def login_required(view):
    """Decorator: verlangt eingeloggten User, sonst 401/redirect zu Authelia."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if user is None:
            if request.accept_mimetypes.accept_html and request.method == "GET":
                # Authelia matched die Rule eigentlich schon — wir landen hier
                # nur, wenn TRUST_REMOTE_USER_HEADER=false ist (Dev-Modus).
                return redirect(url_for("landing"))
            abort(401)
        return view(*args, **kwargs)

    return wrapper


def is_authenticated() -> bool:
    return getattr(g, "current_user", None) is not None
