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

Gast-Pfade (/, /generate, ...) sind in Authelia per ``bypass`` offen; ein
dort angemeldeter Nutzer bringt trotzdem seine Header mit. Damit nicht jede
Authelia-Rolle (z. B. ``household``) hier Accounts anlegt, prueft
``DR_AUTOMATE_ALLOWED_GROUPS`` (komma-separiert) ``Remote-Groups``; wer
keine der Gruppen hat, wird als Gast behandelt. Leer = keine Pruefung
(Dev/Tests).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models_db import User, UserProfile

logger = logging.getLogger(__name__)


# Requests ohne Identitaetsbedarf: kein DB-Zugriff (SQLite-Schreiblast).
SKIP_USER_ENDPOINTS = {"static", "health_check"}

# last_login_at hoechstens so oft schreiben — sonst committet jeder Request.
LAST_LOGIN_GRANULARITY = timedelta(minutes=15)


def _trust_header() -> bool:
    return current_app.config.get("TRUST_REMOTE_USER_HEADER", False)


def allowed_groups() -> set[str]:
    raw = current_app.config.get("ALLOWED_GROUPS")
    if raw is None:
        raw = os.environ.get("DR_AUTOMATE_ALLOWED_GROUPS", "")
    return {g.strip() for g in raw.split(",") if g.strip()}


def _upsert_user(remote_user: str, email: str | None, display_name: str | None) -> User:
    """Idempotent: legt User an oder aktualisiert email/name/last_login_at.

    Schreibt nur, wenn sich etwas geaendert hat oder der letzte Login laenger
    als ``LAST_LOGIN_GRANULARITY`` zurueckliegt. Zwei parallele Erst-Requests
    (IntegrityError auf remote_user) loesen sich ueber erneutes Lesen auf.
    """
    with SessionLocal() as session:
        user = session.execute(select(User).where(User.remote_user == remote_user)).scalar_one_or_none()
        now = datetime.utcnow()
        if user is None:
            user = User(
                remote_user=remote_user,
                email=email,
                display_name=display_name,
                last_login_at=now,
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
    if not _trust_header() or request.endpoint in SKIP_USER_ENDPOINTS:
        return None
    remote_user = request.headers.get("Remote-User", "").strip()
    if not remote_user:
        return None
    # Header sind ASCII per Spec; defensiv kuerzen.
    remote_user = remote_user[:128]
    erlaubt = allowed_groups()
    if erlaubt:
        gruppen = {g.strip() for g in request.headers.get("Remote-Groups", "").split(",") if g.strip()}
        if not gruppen & erlaubt:
            logger.info("Remote-User %s ohne dr-automate-Gruppe — Gast-Modus", remote_user)
            return None
    email = (request.headers.get("Remote-Email", "") or "").strip()[:254] or None
    display_name = (request.headers.get("Remote-Name", "") or "").strip()[:200] or None
    try:
        return _upsert_user(remote_user, email, display_name)
    except Exception:  # pragma: no cover
        logger.exception("User-Upsert fehlgeschlagen fuer remote_user=%s", remote_user)
        return None


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
