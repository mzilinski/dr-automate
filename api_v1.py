"""REST-API v1 (plan-api-v1.md).

Authentifizierung ausschließlich per persönlichem API-Key
(``Authorization: Bearer dra_…``). Authelia-Header und Browser-Sessions
werden hier ignoriert, CSRF ist aus (Bearer-Header schickt kein Browser von
selbst mit). Fehler kommen als ``application/problem+json`` (RFC 9457).
"""

from __future__ import annotations

import io
import logging
from functools import wraps

from flask import Blueprint, Flask, g, jsonify, request, send_file
from flask_limiter.util import get_remote_address
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import HTTPException

import api_keys
import api_models as am
import services
from extensions import limiter
from ki_kontext import _ki_kontext, _load_system_prompt, _wohnort

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


class ApiProblem(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None, typ: str = "fehler", **extra):
        super().__init__(title)
        self.args_ = (status, title, detail)
        self.typ = typ
        self.extra = extra


@bp.errorhandler(ApiProblem)
def _api_problem(e: ApiProblem):
    status, title, detail = e.args_
    return problem(status, title, detail, typ=e.typ, **e.extra)


@bp.errorhandler(ValidationError)
def _validation_error(e: ValidationError):
    # Nur Ort + Meldung, nie die Eingabewerte zurückspiegeln.
    fehler = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors(include_url=False)]
    return problem(422, "Ungültige Eingabe", typ="validation", errors=fehler)


@bp.errorhandler(services.FachlicherFehler)
def _fachlicher_fehler(e: services.FachlicherFehler):
    return problem(422, "Nicht verarbeitbar", str(e), typ="fachlich", errors=e.errors)


def body(model: type[BaseModel]):
    """JSON-Body lesen und gegen ein v1-Modell validieren."""
    if not request.is_json:
        raise ApiProblem(415, "Content-Type muss application/json sein", typ="format")
    data = request.get_json(silent=True)
    if data is None:
        raise ApiProblem(400, "Ungültiges JSON", typ="format")
    return model.model_validate(data)


def pdf_antwort(dateiname: str, inhalt: bytes):
    return send_file(io.BytesIO(inhalt), mimetype="application/pdf", as_attachment=True, download_name=dateiname)


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


# ---------- Schema und Prompt ----------


@bp.get("/schema/antrag")
@api_view(None)
def schema_antrag():
    return jsonify(am.AntragV1.model_json_schema())


@bp.get("/schema/abrechnung")
@api_view(None)
def schema_abrechnung():
    return jsonify(am.AbrechnungV1.model_json_schema())


@bp.get("/prompt")
@api_view(None)
def prompt():
    """System-Prompt für eigene Extraktion (z. B. im MCP-Client) plus der
    Kontextblock für den Key-Inhaber (heutiges Datum, PLZ/Ort). Die Ausgabe
    der KI entspricht ``reise_details``/``bemerkungen``/``angaben`` des Antrags v1."""
    profil = services.profil_daten(g.api_user)
    return jsonify(
        {
            "system_prompt": _load_system_prompt(),
            "kontext": _ki_kontext("", _wohnort(profil["antragsteller"]["adresse_privat"])),
            "hinweis": "Kontext an den Eingabetext anhängen; Verkehrsmittel-Zeilen ggf. ergänzen.",
        }
    )


# ---------- Zustandslos ----------


@bp.post("/antrag/pdf")
@api_view("berechnen", LIMIT_PDF)
def antrag_pdf():
    antrag = body(am.AntragV1)
    profil = services.profil_daten(g.api_user)
    services.pruefe_profil(profil, "antrag")
    model = services.antrag_validieren(am.antrag_to_internal(antrag, profil))
    return pdf_antwort(*services.antrag_pdf(model))


@bp.post("/abrechnung/berechnung")
@api_view("berechnen", LIMIT_SCHREIBEN)
def abrechnung_berechnung():
    abr = body(am.AbrechnungV1)
    model = services.abrechnung_validieren(am.abrechnung_to_internal(abr, services.profil_daten(g.api_user)))
    return jsonify(am.BerechnungV1.model_validate(model.berechnet.model_dump()).model_dump())


@bp.post("/abrechnung/pdf")
@api_view("berechnen", LIMIT_PDF)
def abrechnung_pdf():
    abr = body(am.AbrechnungV1)
    profil = services.profil_daten(g.api_user)
    services.pruefe_profil(profil, "abrechnung_pdf")
    model = services.abrechnung_validieren(am.abrechnung_to_internal(abr, profil))
    return pdf_antwort(*services.abrechnung_pdf(model))


@bp.post("/entfernung")
@api_view("berechnen", LIMIT_ENTFERNUNG)
def entfernung():
    import routing

    e = body(am.EntfernungV1)
    try:
        r = routing.route_km(e.von, e.nach)
    except routing.RoutingError as err:
        raise ApiProblem(422, "Entfernung nicht ermittelbar", str(err), typ="routing") from None
    return jsonify({"km": r["km"], "minuten": r["duration_min"], "quelle": "OpenStreetMap / OSRM"})


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
