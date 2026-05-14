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
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for
from sqlalchemy import select

from db import SessionLocal
from models_db import User, UserProfile

logger = logging.getLogger(__name__)


GUEST_FRIENDLY_ENDPOINTS = {
    "index",
    "abrechnung_index",
    "generate",
    "abrechnung_generate",
    "abrechnung_calc",
    "extract",
    "health_check",
    "get_example",
    "landing",
    "account_request_get",
    "account_request_post",
    "docs_view",
    "static",
}


def _trust_header() -> bool:
    return current_app.config.get("TRUST_REMOTE_USER_HEADER", False)


def _upsert_user(remote_user: str, email: str | None, display_name: str | None) -> User:
    """Idempotent: legt User an oder updated last_login_at + optional email/name."""
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
            session.flush()
            # leeres Profil anlegen, damit /profil nie 404'd
            session.add(UserProfile(user_id=user.id))
            session.commit()
            logger.info("Neuer User angelegt: remote_user=%s", remote_user)
        else:
            # Header-Updates uebernehmen (Authelia hat ggf. Display-Name geaendert)
            changed = False
            if email and user.email != email:
                user.email = email
                changed = True
            if display_name and user.display_name != display_name:
                user.display_name = display_name
                changed = True
            user.last_login_at = now
            session.commit()
            if changed:
                logger.info("User aktualisiert: remote_user=%s", remote_user)
        session.refresh(user)
        # Detach: g.current_user soll keine offene Session halten
        session.expunge(user)
        return user


def load_current_user() -> User | None:
    """Liest die Identitaet aus Authelia-Headern. Vor jedem Request aufrufen."""
    if not _trust_header():
        return None
    remote_user = request.headers.get("Remote-User", "").strip()
    if not remote_user:
        return None
    # Header sind ASCII per Spec; defensiv kuerzen.
    remote_user = remote_user[:128]
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
