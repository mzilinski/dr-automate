"""REST-API v1 (plan-api-v1.md).

Authentifizierung ausschließlich per persönlichem API-Key
(``Authorization: Bearer dra_…``). Authelia-Header und Browser-Sessions
werden hier ignoriert, CSRF ist aus (Bearer-Header schickt kein Browser von
selbst mit). Fehler kommen als ``application/problem+json`` (RFC 9457).
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, Flask, g, jsonify, request
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException

import api_keys
from extensions import limiter

logger = logging.getLogger(__name__)

PREFIX = "/api/v1"
bp = Blueprint("api_v1", __name__, url_prefix=PREFIX)

# Rate-Limits je Key (plan-api-v1.md, Abschnitt 5)
LIMIT_LESEN = "120 per minute"
LIMIT_SCHREIBEN = "30 per minute"
LIMIT_PDF = "20 per minute"
LIMIT_EXTRACT = "10 per minute"
LIMIT_ENTFERNUNG = "30 per hour"
LIMIT_AUTH_FEHLER = "10 per minute"

_PROBLEM_TYPE = "https://dr-automate.zilinski.eu/docs/api#"


def problem(status: int, title: str, detail: str | None = None, *, typ: str = "fehler", **extra):
    body = {"type": _PROBLEM_TYPE + typ, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body.update(extra)
    resp = jsonify(body)
    resp.status_code = status
    resp.mimetype = "application/problem+json"
    return resp


def _bearer() -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth[:7].lower() == "bearer " else ""


def key_func() -> str:
    """Rate-Limit je Key-Präfix (ohne DB-Zugriff), sonst je Client-IP."""
    prefix = api_keys.prefix_of(_bearer())
    return f"apikey:{prefix}" if prefix else get_remote_address()


def api_view(scope: str | None, limit: str = LIMIT_LESEN):
    """Authentifiziert per Bearer-Key, prüft den Scope und begrenzt die Rate.

    ``scope=None``: gültiger Key genügt (z. B. /me). Fehlgeschlagene
    Authentifizierungen zählen zusätzlich je IP (Brute-Force-Bremse)."""

    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            result = api_keys.authenticate(_bearer())
            if result is None:
                return problem(
                    401,
                    "Nicht authentifiziert",
                    "Gültigen API-Key als 'Authorization: Bearer dra_…' mitsenden.",
                    typ="auth",
                )
            g.api_user, g.api_key = result
            if scope and scope not in g.api_key.scopes:
                return problem(403, "Berechtigung fehlt", f"Der Key hat den Scope '{scope}' nicht.", typ="scope")
            logger.info("API %s %s key=%s user=%s", request.method, request.path, g.api_key.id, g.api_user.id)
            return view(*args, **kwargs)

        limited = limiter.limit(limit, key_func=key_func)(wrapper)
        return limiter.limit(
            LIMIT_AUTH_FEHLER, key_func=get_remote_address, deduct_when=lambda r: r.status_code == 401
        )(limited)

    return deco


@bp.before_request
def _api_kontext():
    # Nie die Web-Identität übernehmen (auth.load_current_user lässt /api/v1 aus).
    g.current_user = None
    g.api_user = None
    g.api_key = None


@bp.get("/me")
@api_view(None)
def me():
    u, k = g.api_user, g.api_key
    return jsonify(
        {
            "user": {"name": u.remote_user, "display_name": u.display_name},
            "key": {
                "name": k.name,
                "prefix": k.prefix,
                "scopes": k.scopes,
                "expires_at": k.expires_at.isoformat() + "Z",
                "last_used_at": k.last_used_at.isoformat() + "Z" if k.last_used_at else None,
            },
            "api_berechtigt_bis": u.api_berechtigt_bis.isoformat() + "Z" if u.api_berechtigt_bis else None,
        }
    )


def init_app(app: Flask, csrf) -> None:
    app.register_blueprint(bp)
    csrf.exempt(bp)

    @app.errorhandler(HTTPException)
    def _api_http_error(e: HTTPException):
        # Nur unter /api/v1 als Problem-JSON; sonst Flasks Standardseite.
        if not request.path.startswith(PREFIX + "/"):
            return e
        headers = {}
        if e.code == 429:
            headers["Retry-After"] = "60"
        resp = problem(e.code or 500, e.name, e.description if e.code != 404 else None)
        resp.headers.update(headers)
        return resp
