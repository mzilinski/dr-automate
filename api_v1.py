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


@bp.get("/openapi.json")
@limiter.limit(LIMIT_LESEN, key_func=get_remote_address)
def openapi():
    import api_openapi

    return jsonify(api_openapi.spec())


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


@bp.post("/extract")
@api_view("extract", LIMIT_EXTRACT)
def extract():
    """KI-Extraktion über DeepSeek mit dem Key aus dem Server-Profil.
    JSON-Body (ExtractV1) oder multipart mit ``pdf`` und optional ``daten``
    (ExtractV1 als JSON-String). Ergebnis ist ein Entwurf — Beförderung
    ergänzen und prüfen, dann POST /reisen."""
    import json as _json
    import os

    import ai_extract
    import pdf_text
    from db import SessionLocal
    from ki_kontext import _strip_citations
    from models_db import UserProfile

    pdf = request.files.get("pdf")
    if pdf is not None:
        roh = request.form.get("daten") or "{}"
        try:
            ex = am.ExtractV1.model_validate(_json.loads(roh))
        except ValueError:
            raise ApiProblem(400, "Feld 'daten' ist kein gültiges JSON", typ="format") from None
    else:
        ex = body(am.ExtractV1)

    freitext = ex.freitext
    if pdf is not None:
        inhalt = pdf.stream.read()
        if not inhalt.startswith(b"%PDF-"):
            raise ApiProblem(422, "Datei ist kein PDF", typ="format")
        try:
            text = pdf_text.extract(inhalt, max_pages=int(os.environ.get("DR_AUTOMATE_MAX_PDF_PAGES", "50")))
        except pdf_text.PdfTextError as e:
            raise ApiProblem(e.status_code, "PDF nicht lesbar", str(e), typ="pdf") from None
        freitext = text if not freitext else f"{text}\n\n--- Zusatz-Notizen ---\n{freitext}"
    if not freitext.strip():
        raise ApiProblem(422, "Kein Text", "freitext oder pdf angeben.", typ="validation")

    with SessionLocal() as s:
        p = s.query(UserProfile).filter(UserProfile.user_id == g.api_user.id).first()
        key = p.deepseek_api_key if p else None
    if not key:
        raise ApiProblem(422, "Kein DeepSeek-Key im Profil", "Unter /profil hinterlegen.", typ="fachlich")

    reise = {k: v.model_dump() for k, v in (("hinreise", ex.hinreise), ("rueckreise", ex.rueckreise)) if v}
    profil = services.profil_daten(g.api_user)
    kontext = _ki_kontext(_json.dumps(reise), _wohnort(profil["antragsteller"]["adresse_privat"]))
    try:
        ki = ai_extract.call_deepseek(
            freitext=f"{freitext}\n\n{kontext}",
            api_key=key,
            system_prompt=_load_system_prompt(),
            sonderwuensche=ex.hinweise,
        )
    except ai_extract.AIExtractError as e:
        raise ApiProblem(e.status_code, "KI-Extraktion fehlgeschlagen", str(e), typ="ki") from None
    return jsonify(
        {
            "antrag_entwurf": am.extrakt_v1(_strip_citations(ki)),
            "hinweis": "KI-Entwurf: prüfen, befoerderung ergänzen, dann POST /api/v1/reisen.",
        }
    )


# ---------- Reisen ----------

_STATUS = ("entwurf", "eingereicht", "genehmigt", "abgerechnet", "bezahlt", "verworfen")


def _reise(reise_id: int):
    try:
        return services.reise_laden(g.api_user.id, reise_id)
    except services.PersistError:
        raise ApiProblem(404, "Reise nicht gefunden", typ="nicht-gefunden") from None


def _konflikt(e: Exception):
    return ApiProblem(409, "Statuskonflikt", str(e), typ="status")


def _datum(raw: str, feld: str):
    d = services.parse_iso_date(raw.strip())
    if d is None:
        raise ApiProblem(
            422,
            "Ungültige Eingabe",
            typ="validation",
            errors=[{"loc": [feld], "msg": "Datum DD.MM.YYYY oder YYYY-MM-DD"}],
        )
    return d


@bp.get("/reisen")
@api_view("reisen:read")
def reisen_liste():
    status = request.args.get("status") or None
    if status and status not in _STATUS:
        raise ApiProblem(422, "Unbekannter Status", f"Erlaubt: {', '.join(_STATUS)}", typ="validation")
    return jsonify({"reisen": [am.reise_v1(r) for r in services.reisen_liste(g.api_user.id, status)]})


@bp.post("/reisen")
@api_view("reisen:write", LIMIT_PDF)
def reise_anlegen():
    antrag = body(am.AntragV1)
    profil = services.profil_daten(g.api_user)
    services.pruefe_profil(profil, "antrag")
    model = services.antrag_validieren(am.antrag_to_internal(antrag, profil))
    _, pdf = services.antrag_pdf(model)
    reise_id, _ = services.antrag_speichern(g.api_user.id, None, model, pdf)
    resp = jsonify(am.reise_v1(services.reise_laden(g.api_user.id, reise_id), mit_daten=True))
    resp.status_code = 201
    resp.headers["Location"] = f"{PREFIX}/reisen/{reise_id}"
    return resp


@bp.get("/reisen/<int:reise_id>")
@api_view("reisen:read")
def reise_lesen(reise_id: int):
    import paperless_sync

    d = am.reise_v1(_reise(reise_id), mit_daten=True)
    d["paperless"] = am.paperless_v1(paperless_sync.status_je_reise([reise_id]).get(reise_id, {}))
    return jsonify(d)


@bp.post("/reisen/<int:reise_id>/paperless")
@api_view("reisen:write", LIMIT_SCHREIBEN)
def reise_paperless(reise_id: int):
    """PDF an Paperless senden (asynchron, Status über GET /reisen/{id})."""
    import paperless_sync

    r = _reise(reise_id)
    art = body(am.PaperlessV1).art
    vorhanden = r.antrag_pdf_path if art == "antrag" else (r.abrechnung and r.abrechnung.abrechnung_pdf_path)
    if not vorhanden:
        raise ApiProblem(409, "Kein PDF vorhanden", f"Für '{art}' gibt es noch kein PDF.", typ="status")
    try:
        paperless_sync.einreihen(g.api_user.id, reise_id, art, erzwingen=True)
    except paperless_sync.NichtEingerichtet as e:
        raise ApiProblem(422, "Paperless nicht eingerichtet", str(e), typ="fachlich") from None
    resp = jsonify(am.paperless_v1(paperless_sync.status_je_reise([reise_id]).get(reise_id, {})))
    resp.status_code = 202
    return resp


@bp.put("/reisen/<int:reise_id>/antrag")
@api_view("reisen:write", LIMIT_PDF)
def reise_antrag_ersetzen(reise_id: int):
    _reise(reise_id)
    antrag = body(am.AntragV1)
    profil = services.profil_daten(g.api_user)
    services.pruefe_profil(profil, "antrag")
    model = services.antrag_validieren(am.antrag_to_internal(antrag, profil))
    _, pdf = services.antrag_pdf(model)
    try:
        services.antrag_speichern(g.api_user.id, reise_id, model, pdf, bei_sperre="ablehnen")
    except services.StatusKonflikt as e:
        raise _konflikt(e) from None
    return jsonify(am.reise_v1(services.reise_laden(g.api_user.id, reise_id), mit_daten=True))


def _pdf_datei(pfad: str | None, name: str):
    import os

    if not pfad or not os.path.isfile(pfad):
        raise ApiProblem(404, "PDF nicht vorhanden", typ="nicht-gefunden")
    with open(pfad, "rb") as f:
        return pdf_antwort(name, f.read())


@bp.get("/reisen/<int:reise_id>/antrag.pdf")
@api_view("reisen:read", LIMIT_PDF)
def reise_antrag_pdf(reise_id: int):
    r = _reise(reise_id)
    return _pdf_datei(r.antrag_pdf_path, f"DR-Antrag-{r.id}.pdf")


@bp.get("/reisen/<int:reise_id>/abrechnung.pdf")
@api_view("reisen:read", LIMIT_PDF)
def reise_abrechnung_pdf(reise_id: int):
    r = _reise(reise_id)
    return _pdf_datei(r.abrechnung.abrechnung_pdf_path if r.abrechnung else None, f"DR-Abrechnung-{r.id}.pdf")


@bp.post("/reisen/<int:reise_id>/genehmigung")
@api_view("reisen:write", LIMIT_SCHREIBEN)
def reise_genehmigung(reise_id: int):
    _reise(reise_id)
    gen = body(am.GenehmigungV1)
    services.genehmigung_vermerken(g.api_user.id, reise_id, _datum(gen.datum, "datum"), gen.aktenzeichen)
    return jsonify(am.reise_v1(services.reise_laden(g.api_user.id, reise_id)))


@bp.put("/reisen/<int:reise_id>/abrechnung")
@api_view("reisen:write", LIMIT_PDF)
def reise_abrechnung(reise_id: int):
    r = _reise(reise_id)
    abr = body(am.AbrechnungV1)
    profil = services.profil_daten(g.api_user)
    services.pruefe_profil(profil, "abrechnung_pdf")
    daten = am.abrechnung_to_internal(abr, profil)
    if not daten["anordnung"]["datum"] and r.genehmigung_datum:
        daten["anordnung"]["datum"] = r.genehmigung_datum.strftime("%d.%m.%Y")
    model = services.abrechnung_validieren(daten)
    _, pdf = services.abrechnung_pdf(model)
    services.abrechnung_speichern(g.api_user.id, reise_id, model, pdf)
    return jsonify(am.reise_v1(services.reise_laden(g.api_user.id, reise_id), mit_daten=True))


@bp.post("/reisen/<int:reise_id>/bezahlt")
@api_view("reisen:write", LIMIT_SCHREIBEN)
def reise_bezahlt(reise_id: int):
    from datetime import date

    _reise(reise_id)
    bez = body(am.BezahltV1) if request.content_length else am.BezahltV1()
    datum = _datum(bez.datum, "datum") if bez.datum else date.today()
    try:
        services.bezahlt_vermerken(g.api_user.id, reise_id, datum)
    except services.StatusKonflikt as e:
        raise _konflikt(e) from None
    return jsonify(am.reise_v1(services.reise_laden(g.api_user.id, reise_id)))


@bp.delete("/reisen/<int:reise_id>")
@api_view("reisen:write", LIMIT_SCHREIBEN)
def reise_loeschen(reise_id: int):
    _reise(reise_id)
    services.reise_loeschen(g.api_user.id, reise_id)
    return "", 204


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
