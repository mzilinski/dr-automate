import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import bleach
import markdown as md
from flask import (
    Flask,
    abort,
    after_this_request,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import select
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail, Message
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

import ai_extract
import auth
import generator
import generator_abrechnung
import nrkvo_rates
from models import validate_abrechnung, validate_reiseantrag

# --- KONFIGURATION ---
PDF_TEMPLATE_PATH = os.environ.get("PDF_TEMPLATE_PATH", os.path.join("forms", "DR-Antrag_035_001Stand4-2025pdf.pdf"))
PDF_TEMPLATE_ABRECHNUNG_PATH = os.environ.get(
    "PDF_TEMPLATE_ABRECHNUNG_PATH", os.path.join("forms", "Reisekostenvordruck.pdf")
)
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5001))
HOST = os.environ.get("HOST", "0.0.0.0")  # nosec B104 — bind auf alle Interfaces ist für Container/Cloud-Deploys gewünscht
RATE_LIMIT = os.environ.get("RATE_LIMIT", "10")
# TRUST_REMOTE_USER_HEADER: nur in Produktion hinter Traefik auf `true` setzen.
# Default `false` schuetzt vor Header-Spoofing in lokalem/Test-Setup.
TRUST_REMOTE_USER_HEADER = os.environ.get("TRUST_REMOTE_USER_HEADER", "false").lower() == "true"
DATA_DIR = Path(os.environ.get("DR_AUTOMATE_DATA_DIR", "data"))
DOCS_DIR = Path(os.environ.get("DR_AUTOMATE_DOCS_DIR", "docs"))
ADMIN_EMAIL = os.environ.get("DR_AUTOMATE_ADMIN_EMAIL", "")
# Admin-Routen (/admin/...) sind nur fuer die hier gelisteten Remote-User
# erreichbar — Authelia kennt aktuell nur eine Gruppe ("adults"), daher
# enforcement per-User. Leer = niemand hat Admin-Zugang (sicheres default).
ADMIN_REMOTE_USERS: set[str] = {
    u.strip() for u in os.environ.get("ADMIN_REMOTE_USERS", "").split(",") if u.strip()
}
# Telegram-Notifications fuer Admin-Events (z.B. neue Account-Anfrage).
# Beide leer = Telegram-Versand deaktiviert. SMTP/Mail bleibt unabhaengig.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
# Upload-Limits fuer /extract-Endpunkt (PDF-Aufnahme).
MAX_UPLOAD_BYTES = int(os.environ.get("DR_AUTOMATE_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MiB
MAX_PDF_PAGES = int(os.environ.get("DR_AUTOMATE_MAX_PDF_PAGES", "50"))

# --- LOGGING ---
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- SECRET KEY ---
# Production: SECRET_KEY env var ist Pflicht (sonst sind Sessions fälschbar).
# Debug-Modus: ephemeren Key generieren, damit lokales Entwickeln ohne Setup funktioniert.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG_MODE:
        SECRET_KEY = secrets.token_hex(32)
        logger.warning(
            "SECRET_KEY ist nicht gesetzt — verwende ephemeren Key (Debug-Modus). Sessions überleben keinen Restart."
        )
    else:
        raise RuntimeError(
            "SECRET_KEY environment variable must be set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )

# --- APP SETUP ---
app = Flask(__name__)
# ProxyFix: nur aktivieren wenn wir hinter einem vertrauten Reverse-Proxy
# laufen (TRUST_REMOTE_USER_HEADER=true bedeutet sowieso "wir trauen den
# Authelia-Headern" → impliziert vertrauter Proxy). So gibt
# get_remote_address() die echte Client-IP statt der Proxy-IP zurueck,
# damit das Rate-Limit pro Client greift.
if TRUST_REMOTE_USER_HEADER:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["TRUST_REMOTE_USER_HEADER"] = TRUST_REMOTE_USER_HEADER
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEBUG_MODE,
)

# Flask-Mail fuer Account-Anfragen. Wenn kein MAIL_SERVER gesetzt ist, bleibt
# der Versand stiller no-op (Anfragen werden trotzdem in DB persistiert).
app.config.update(
    MAIL_SERVER=os.environ.get("MAIL_SERVER", ""),
    MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
    MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME", ""),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
    MAIL_DEFAULT_SENDER=os.environ.get("MAIL_DEFAULT_SENDER", "noreply@example.org"),
)
mail = Mail(app)

# CSRF-Schutz
csrf = CSRFProtect(app)

# Rate Limiting
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[], storage_uri="memory://")

# Prüfe ob Template existiert
if not os.path.exists(PDF_TEMPLATE_PATH):
    logger.warning(f"Template file not found at {PDF_TEMPLATE_PATH}")


_CITATION_RE = re.compile(r"\s*\[cite:[^\]]+\]", re.IGNORECASE)
_CITATION_RAW_RE = re.compile(r"\[cite_start\]|\[cite_end\]|\s*\[cite:[^\]]+\]", re.IGNORECASE)


def _strip_citations_raw(text: str) -> str:
    """Entfernt KI-Zitatmarker aus rohem JSON-Text vor dem Parsen."""
    return _CITATION_RAW_RE.sub("", text)


def _strip_citations(obj):
    """Entfernt KI-Zitatmarker wie [cite: 1, 2] rekursiv aus allen String-Werten."""
    if isinstance(obj, dict):
        return {k: _strip_citations(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_citations(i) for i in obj]
    if isinstance(obj, str):
        return _CITATION_RE.sub("", obj).strip()
    return obj


def _legal_urls():
    return {
        "impressum_url": os.environ.get("IMPRESSUM_URL", "#"),
        "datenschutz_url": os.environ.get("DATENSCHUTZ_URL", "#"),
    }


def _build_wizard_profile_seed(user) -> dict | None:
    """Liefert die Server-Profildaten im localStorage-Schema des Wizards.

    Mapping Server-Spalte → Wizard-Key:
      vorname + nachname  → name
      adresse_privat      → adresse (Wizard splittet bei Komma in strasse/plz_ort)
      mitreisender_name_default → mitreisender
      User.email          → email (kommt aus Authelia Remote-Email)
      alle anderen Felder identisch
    Gibt None zurueck, wenn kein Profil existiert (z.B. Erst-Login ohne Save).
    """
    if user is None:
        return None
    from db import SessionLocal
    from models_db import UserProfile

    with SessionLocal() as s:
        profile = s.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        if profile is None:
            return {
                "name": user.display_name or "",
                "email": user.email or "",
                "auto_save_dienstreisen": True,
            }
        full_name = " ".join(p for p in (profile.vorname, profile.nachname) if p).strip() or (user.display_name or "")
        return {
            "name": full_name,
            "abteilung": profile.abteilung or "",
            "telefon": profile.telefon or "",
            "adresse": profile.adresse_privat or "",
            "mitreisender": profile.mitreisender_name_default or "",
            "iban": profile.iban or "",
            "bic": profile.bic or "",
            # Profil-Email hat Vorrang, sonst Authelia-Email.
            "email": (profile.email or user.email or ""),
            "abrechnende_dienststelle": profile.abrechnende_dienststelle or "",
            "anordnende_dienststelle": profile.anordnende_dienststelle or "",
            "rkr_default": profile.rkr_default or "DR",
            # DeepSeek-Key wird BEWUSST NICHT ins Template geseedet — sonst
            # liegt er als Klartext im HTML und ist bei DOM-XSS sofort
            # exfiltrierbar. /extract holt ihn serverseitig aus user_profiles
            # als Fallback, wenn der X-DeepSeek-Key-Header leer ist. Frontend
            # bekommt nur den has_-Flag.
            "has_deepseek_api_key": bool(profile.deepseek_api_key),
            "auto_save_dienstreisen": bool(profile.auto_save_dienstreisen),
        }


def _common_template_ctx():
    user = getattr(g, "current_user", None)
    return {
        **_legal_urls(),
        "nrkvo_stand": nrkvo_rates.RATES_STAND,
        "current_user": user,
        "is_authenticated": user is not None,
        "authelia_logout_url": os.environ.get("AUTHELIA_LOGOUT_URL", "/"),
        "wizard_profile_seed": _build_wizard_profile_seed(user),
    }


def _load_system_prompt() -> str:
    """Lädt den Antrag-System-Prompt (lokal personalisierte Version bevorzugt)."""
    prompt_file = "system_prompt.local.md" if os.path.exists("system_prompt.local.md") else "system_prompt.md"
    try:
        with open(prompt_file, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error loading prompt file: {e}"


# --- AUTH ---
# Identitaet kommt aus Authelias `Remote-User`-Header (siehe auth.py).
# Es gibt kein lokales Login mehr — Authelia uebernimmt Login/Logout/2FA.


@app.before_request
def load_user():
    g.current_user = auth.load_current_user()


@app.route("/", methods=["GET"])
def index():
    """Antrag-Wizard. Oeffentlich erreichbar (Gast-Modus). Bei Auth zeigt
    das Template ein "Diese Reise speichern"-Banner."""
    return render_template("index.html", prompt_content=_load_system_prompt(), **_common_template_ctx())


@app.route("/landing", methods=["GET"])
def landing():
    """Startseite mit Wahl: 'Mit Account' / 'Ohne Account'.
    Authentifizierte User werden direkt aufs Dashboard geleitet."""
    if auth.is_authenticated():
        return redirect(url_for("dashboard"))
    return render_template("landing.html", **_common_template_ctx())


# --- DASHBOARD (Auth-only) ---


@app.route("/dashboard", methods=["GET"])
@auth.login_required
def dashboard():
    """Reise-Uebersicht des eingeloggten Users."""
    from sqlalchemy.orm import joinedload

    from db import SessionLocal
    from models_db import Dienstreise

    with SessionLocal() as session_db:
        reisen = (
            session_db.query(Dienstreise)
            .options(joinedload(Dienstreise.abrechnung))
            .filter(Dienstreise.user_id == g.current_user.id)
            .order_by(Dienstreise.created_at.desc())
            .all()
        )
        # Detach, damit kein lazy-load nach session-close
        session_db.expunge_all()
    return render_template("dashboard.html", reisen=reisen, **_common_template_ctx())


# --- DIENSTREISE-CRUD (Auth-only) ---


def _get_dienstreise_or_404(reise_id: int):
    """IDOR-Schutz: nur eigene Reisen ausliefern. Niemals ueber den Filter hinweg laden."""
    from db import SessionLocal
    from models_db import Dienstreise

    user = g.current_user
    if user is None:
        abort(401)
    s = SessionLocal()
    reise = s.query(Dienstreise).filter(Dienstreise.id == reise_id, Dienstreise.user_id == user.id).first()
    if reise is None:
        s.close()
        abort(404)
    return s, reise


def _parse_iso_date(value: str):
    """Akzeptiert ISO 'YYYY-MM-DD' oder deutsches 'DD.MM.YYYY'.

    Beide Formate werden gleichberechtigt versucht — strptime liefert
    None zurueck wenn nichts passt.
    """
    from datetime import datetime as _dt

    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return _dt.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _persist_antrag(reise_id_str: str, data: dict, result, pdf_path: str | None) -> int:
    """Erstellt oder aktualisiert eine Dienstreise. Gibt die ID zurueck.

    ``data`` ist das schon validierte und citation-bereinigte Antrag-JSON,
    ``result`` das Pydantic-Modell (fuer Plain-Felder wie Zielort/Datum).
    """
    from datetime import datetime as _dt

    from db import SessionLocal
    from models_db import Dienstreise, DienstreiseStatus

    user = g.current_user
    reise_id = int(reise_id_str) if reise_id_str and reise_id_str.isdigit() else None

    zielort = result.reise_details.zielort if hasattr(result, "reise_details") else None
    zweck = result.reise_details.zweck if hasattr(result, "reise_details") else None
    titel = (zweck or zielort or "Dienstreise")[:200]

    start_d = _parse_iso_date(result.reise_details.start_datum) if hasattr(result, "reise_details") else None
    if not start_d and hasattr(result, "reise_details"):
        try:
            start_d = _dt.strptime(result.reise_details.start_datum, "%d.%m.%Y").date()
        except (ValueError, AttributeError):
            start_d = None
    end_d = None
    if hasattr(result, "reise_details"):
        try:
            end_d = _dt.strptime(result.reise_details.ende_datum, "%d.%m.%Y").date()
        except (ValueError, AttributeError):
            end_d = None

    persistent_pdf_path = None
    if pdf_path:
        target_dir = DATA_DIR / "pdfs" / str(user.id)
        target_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as s:
        if reise_id is not None:
            reise = s.query(Dienstreise).filter(Dienstreise.id == reise_id, Dienstreise.user_id == user.id).first()
            if reise is None:
                abort(404)
            reise.titel = titel
            reise.zielort = zielort
            reise.start_datum = start_d
            reise.ende_datum = end_d
            reise.antrag_json = data
        else:
            reise = Dienstreise(
                user_id=user.id,
                titel=titel,
                zielort=zielort,
                start_datum=start_d,
                ende_datum=end_d,
                antrag_json=data,
                status=DienstreiseStatus.entwurf,
            )
            s.add(reise)
            s.flush()  # damit reise.id verfuegbar ist

        if pdf_path:
            persistent_pdf_path = _persist_pdf(pdf_path, user.id, reise.id, "antrag.pdf")
            reise.antrag_pdf_path = str(persistent_pdf_path)

        s.commit()
        return reise.id


def _persist_pdf(src_pdf: str, user_id: int, reise_id: int, filename: str) -> Path:
    """Kopiert PDF in das User-/Reise-Verzeichnis mit restriktiven Perms (0700/0600)."""
    target_dir = DATA_DIR / "pdfs" / str(user_id) / str(reise_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Permissions explizit setzen — umask 022 wuerde sonst 0755 daraus machen.
    try:
        os.chmod(target_dir.parent, 0o700)  # /pdfs/<user_id>
        os.chmod(target_dir, 0o700)  # /pdfs/<user_id>/<reise_id>
    except OSError:
        pass
    target = target_dir / filename
    shutil.copy2(src_pdf, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def _persist_abrechnung(reise_id_str: str, data: dict, pdf_path: str | None) -> int | None:
    """Persistiert die Abrechnung zu einer bestehenden Dienstreise."""
    from datetime import datetime as _dt

    from db import SessionLocal
    from models_db import Abrechnung, AbrechnungStatus, Dienstreise, DienstreiseStatus

    if not reise_id_str or not reise_id_str.isdigit():
        return None
    reise_id = int(reise_id_str)
    user = g.current_user

    with SessionLocal() as s:
        reise = s.query(Dienstreise).filter(Dienstreise.id == reise_id, Dienstreise.user_id == user.id).first()
        if reise is None:
            abort(404)
        abr = s.query(Abrechnung).filter(Abrechnung.dienstreise_id == reise.id).first()
        if abr is None:
            abr = Abrechnung(dienstreise_id=reise.id, status=AbrechnungStatus.abgeschlossen)
            s.add(abr)
            s.flush()
        abr.abrechnung_json = data
        abr.status = AbrechnungStatus.abgeschlossen
        abr.generated_at = _dt.utcnow()

        if pdf_path:
            persistent = _persist_pdf(pdf_path, user.id, reise.id, "abrechnung.pdf")
            abr.abrechnung_pdf_path = str(persistent)

        # bezahlt-Reisen NICHT auf abgerechnet zurueckdrehen (User-Bestaetigung
        # wiegt schwerer als ein erneuter PDF-Export).
        if reise.status != DienstreiseStatus.bezahlt:
            reise.status = DienstreiseStatus.abgerechnet
        s.commit()
        return abr.id


@app.route("/dienstreisen/<int:reise_id>/antrag-json", methods=["GET"])
@auth.login_required
def dienstreise_antrag_json(reise_id: int):
    """Pre-Fill fuer den Wizard. Liefert das gespeicherte Antrag-JSON."""
    s, reise = _get_dienstreise_or_404(reise_id)
    try:
        return jsonify(
            {
                "id": reise.id,
                "titel": reise.titel,
                "status": reise.status.value,
                "genehmigung_datum": reise.genehmigung_datum.isoformat() if reise.genehmigung_datum else None,
                "genehmigung_aktenzeichen": reise.genehmigung_aktenzeichen,
                "antrag_json": reise.antrag_json,
            }
        )
    finally:
        s.close()


@app.route("/dienstreisen/<int:reise_id>/abrechnung-json", methods=["GET"])
@auth.login_required
def dienstreise_abrechnung_json(reise_id: int):
    """Pre-Fill fuer den Abrechnungs-Wizard."""
    s, reise = _get_dienstreise_or_404(reise_id)
    try:
        abr = reise.abrechnung
        return jsonify(
            {
                "id": reise.id,
                "antrag_json": reise.antrag_json,
                "abrechnung_json": abr.abrechnung_json if abr else None,
                "genehmigung_datum": reise.genehmigung_datum.isoformat() if reise.genehmigung_datum else None,
                "genehmigung_aktenzeichen": reise.genehmigung_aktenzeichen,
            }
        )
    finally:
        s.close()


@app.route("/dienstreisen/<int:reise_id>/genehmigung", methods=["GET"])
@auth.login_required
def dienstreise_genehmigung_form(reise_id: int):
    s, reise = _get_dienstreise_or_404(reise_id)
    s.close()
    return render_template("dienstreise_genehmigung.html", reise=reise, **_common_template_ctx())


@app.route("/dienstreisen/<int:reise_id>/genehmigung", methods=["POST"])
@auth.login_required
def dienstreise_genehmigung_save(reise_id: int):
    from models_db import DienstreiseStatus

    s, reise = _get_dienstreise_or_404(reise_id)
    try:
        datum_raw = (request.form.get("genehmigung_datum") or "").strip()
        aktenzeichen = (request.form.get("genehmigung_aktenzeichen") or "").strip()[:100] or None
        d = _parse_iso_date(datum_raw)
        if d is None:
            flash("Bitte ein gültiges Genehmigungs-Datum angeben.", "error")
            return redirect(url_for("dienstreise_genehmigung_form", reise_id=reise_id))
        reise.genehmigung_datum = d
        reise.genehmigung_aktenzeichen = aktenzeichen
        if reise.status == DienstreiseStatus.entwurf or reise.status == DienstreiseStatus.eingereicht:
            reise.status = DienstreiseStatus.genehmigt
        s.commit()
        flash("Genehmigung vermerkt.", "success")
    finally:
        s.close()
    if request.form.get("next") == "abrechnung":
        return redirect(url_for("abrechnung_index", dienstreise=reise_id))
    return redirect(url_for("dashboard"))


@app.route("/api/route", methods=["POST"])
@limiter.limit("30 per hour")
def api_route():
    """Schaetzt PKW-Entfernung via OpenStreetMap-Nominatim + OSRM.

    Form / JSON-Felder:
      from: Start-Adresse (frei-Text, z.B. "Lingen, Am Biener Esch 11")
      to:   Ziel-Adresse

    Returns: { km: float, duration_min: int, source: "OSM/OSRM" }
    Datenquelle ist OpenStreetMap (Nominatim) + OSRM Public-Demo. Beide
    sind ohne Account nutzbar, Demo-Server hat aber keine SLA — als
    "Schaetzung" deklarieren, nicht als verbindlicher Wert.
    """
    import routing as _routing

    src = (request.form.get("from") or (request.get_json(silent=True) or {}).get("from") or "").strip()
    dst = (request.form.get("to") or (request.get_json(silent=True) or {}).get("to") or "").strip()
    if not src or not dst:
        return jsonify({"error": "from/to Adressen erforderlich"}), 400
    try:
        result = _routing.route_km(src, dst)
        return jsonify({**result, "source": "OpenStreetMap / OSRM"})
    except _routing.RoutingError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:  # pragma: no cover
        logger.exception("Routing-API unerwarteter Fehler")
        return jsonify({"error": "Interner Fehler bei der Entfernungs-Abfrage"}), 500


@app.route("/dienstreisen/<int:reise_id>/bezahlt", methods=["POST"])
@auth.login_required
def dienstreise_bezahlt(reise_id: int):
    """Markiert eine Reise als bezahlt (Geldeingang bestaetigt).
    Form-Feld 'bezahlt_datum' (YYYY-MM-DD) optional; default heute.
    Form-Feld 'unmark=1' setzt zurueck auf abgerechnet.
    """
    from datetime import date as _date

    from models_db import DienstreiseStatus

    s, reise = _get_dienstreise_or_404(reise_id)
    try:
        if request.form.get("unmark") == "1":
            reise.bezahlt_datum = None
            if reise.status == DienstreiseStatus.bezahlt:
                reise.status = DienstreiseStatus.abgerechnet
            flash("Geldeingang-Markierung entfernt.", "success")
        else:
            raw = (request.form.get("bezahlt_datum") or "").strip()
            d = _parse_iso_date(raw) if raw else _date.today()
            if d is None:
                flash("Ungültiges Datum.", "error")
                return redirect(url_for("dashboard"))
            reise.bezahlt_datum = d
            reise.status = DienstreiseStatus.bezahlt
            flash(f"Geldeingang vermerkt ({d.strftime('%d.%m.%Y')}).", "success")
        s.commit()
    finally:
        s.close()
    return redirect(url_for("dashboard"))


@app.route("/dienstreisen/<int:reise_id>/antrag.pdf", methods=["GET"])
@auth.login_required
def dienstreise_antrag_pdf(reise_id: int):
    s, reise = _get_dienstreise_or_404(reise_id)
    path = reise.antrag_pdf_path
    antrag_json = reise.antrag_json
    s.close()
    if not path or not os.path.isfile(path):
        abort(404)
    # Schoener Dateiname aus den gespeicherten JSON-Daten ableiten
    # (Format: YYYYMMDD_DR-Antrag_Stadt_Thema.pdf).
    try:
        download_name = generator.generate_output_filename(antrag_json or {})
    except Exception:
        download_name = f"DR-Antrag-{reise_id}.pdf"
    return send_file(path, as_attachment=True, download_name=download_name)


@app.route("/dienstreisen/<int:reise_id>/abrechnung.pdf", methods=["GET"])
@auth.login_required
def dienstreise_abrechnung_pdf(reise_id: int):
    s, reise = _get_dienstreise_or_404(reise_id)
    path = reise.abrechnung.abrechnung_pdf_path if reise.abrechnung else None
    abr_json = reise.abrechnung.abrechnung_json if reise.abrechnung else None
    s.close()
    if not path or not os.path.isfile(path):
        abort(404)
    try:
        # generator_abrechnung erwartet ein AbrechnungData-Pydantic-Modell.
        is_valid, model = validate_abrechnung(abr_json or {})
        if is_valid:
            download_name = generator_abrechnung.generate_output_filename(model)
        else:
            raise ValueError("invalid abrechnung-json")
    except Exception:
        download_name = f"DR-Abrechnung-{reise_id}.pdf"
    return send_file(path, as_attachment=True, download_name=download_name)


# --- PROFIL (Auth-only) ---


_PROFIL_FIELDS_TEXT = {
    "vorname",
    "nachname",
    "abteilung",
    "telefon",
    "email",
    "adresse_privat",
    "iban",
    "bic",
    "mitreisender_name_default",
    "rkr_default",
    "abrechnende_dienststelle",
    "anordnende_dienststelle",
    "ai_provider_default",
}


def _profile_to_dict(profile, include_secrets: bool = False) -> dict:
    """Default: Secrets (Keys) werden NICHT mitgeliefert, nur als bool ``has_deepseek_api_key``.

    Auf ``include_secrets=True`` liefert die Funktion auch den Klar-Key zurueck —
    fuer Anwendungsfaelle wie der Wizard, der den Key per Header weiterleiten will.
    """
    base = {f: getattr(profile, f, None) or "" for f in _PROFIL_FIELDS_TEXT}
    base["bahncards"] = profile.bahncards if profile and profile.bahncards else {}
    base["has_deepseek_api_key"] = bool(getattr(profile, "deepseek_api_key", None))
    base["auto_save_dienstreisen"] = bool(getattr(profile, "auto_save_dienstreisen", True))
    if include_secrets:
        base["deepseek_api_key"] = getattr(profile, "deepseek_api_key", None) or ""
    return base


@app.route("/profil", methods=["GET"])
@auth.login_required
def profil_view():
    from db import SessionLocal
    from models_db import UserProfile

    with SessionLocal() as s:
        profile = s.query(UserProfile).filter(UserProfile.user_id == g.current_user.id).first()
        if profile is None:
            profile = UserProfile(user_id=g.current_user.id)
            s.add(profile)
            s.commit()
            s.refresh(profile)
        s.expunge_all()
    return render_template("profil.html", profile=profile, **_common_template_ctx())


@app.route("/profil", methods=["POST"])
@auth.login_required
def profil_save():
    from db import SessionLocal
    from models_db import UserProfile

    with SessionLocal() as s:
        profile = s.query(UserProfile).filter(UserProfile.user_id == g.current_user.id).first()
        if profile is None:
            profile = UserProfile(user_id=g.current_user.id)
            s.add(profile)
        for field in _PROFIL_FIELDS_TEXT:
            val = (request.form.get(field) or "").strip()
            setattr(profile, field, val[:500] if val else None)
        # DeepSeek-API-Key: Leave-empty-to-keep — leerer Submit ueberschreibt
        # einen bestehenden Key NICHT (typische Pattern fuer Password-Felder).
        # Loeschen geht via separatem Checkbox "clear_deepseek_api_key".
        if request.form.get("clear_deepseek_api_key") == "1":
            profile.deepseek_api_key = None
        else:
            new_key = (request.form.get("deepseek_api_key") or "").strip()
            if new_key:
                profile.deepseek_api_key = new_key[:200]
        # Auto-Save-Flag: Checkbox kommt nur wenn aktiv im Form an;
        # fehlt sie → User hat sie abgewaehlt → false.
        profile.auto_save_dienstreisen = request.form.get("auto_save_dienstreisen") == "1"
        # BahnCards als simple flag-Sammlung
        bcs = {
            "bcb_1": request.form.get("bahncard_bcb_1") == "1",
            "bcb_2": request.form.get("bahncard_bcb_2") == "1",
            "bc25_1": request.form.get("bahncard_bc25_1") == "1",
            "bc25_2": request.form.get("bahncard_bc25_2") == "1",
            "bc50_1": request.form.get("bahncard_bc50_1") == "1",
            "bc50_2": request.form.get("bahncard_bc50_2") == "1",
            "bc100_1": request.form.get("bahncard_bc100_1") == "1",
            "bc100_2": request.form.get("bahncard_bc100_2") == "1",
            "grosskunde_1": request.form.get("grosskunde_1") == "1",
            "grosskunde_2": request.form.get("grosskunde_2") == "1",
        }
        profile.bahncards = bcs
        s.commit()
    flash("Profil gespeichert.", "success")
    return redirect(url_for("profil_view"))


@app.route("/profil/json", methods=["GET"])
@auth.login_required
def profil_json():
    """Liefert das Profil als JSON fuer Wizard-Pre-Fill.

    Der DeepSeek-Key wird NICHT als Klartext ausgeliefert — nur als
    ``has_deepseek_api_key: bool``. Wer den Key explizit braucht, ruft
    ``/profil/json?include_secrets=1`` auf; das ist der einzige Pfad,
    auf dem der Klar-Key den Server verlaesst — und auch nur in eine
    authenticated Session des Owners.
    """
    from db import SessionLocal
    from models_db import UserProfile

    include_secrets = request.args.get("include_secrets") == "1"
    with SessionLocal() as s:
        profile = s.query(UserProfile).filter(UserProfile.user_id == g.current_user.id).first()
        if profile is None:
            return jsonify({})
        return jsonify(_profile_to_dict(profile, include_secrets=include_secrets))


@app.route("/dienstreisen/<int:reise_id>/delete", methods=["POST"])
@auth.login_required
def dienstreise_delete(reise_id: int):
    s, reise = _get_dienstreise_or_404(reise_id)
    try:
        # PDFs auf Disk mit aufraeumen
        target_dir = DATA_DIR / "pdfs" / str(g.current_user.id) / str(reise.id)
        if target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        s.delete(reise)
        s.commit()
        flash("Reise gelöscht.", "success")
    finally:
        s.close()
    return redirect(url_for("dashboard"))


# --- ADMIN-NOTIFICATIONS ---


def _send_telegram(text: str) -> None:
    """Schickt eine Telegram-Nachricht an den konfigurierten Admin-Chat.

    No-Op wenn TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID leer ist.
    Schluckt alle Fehler — der primaere Request-Pfad (z.B.
    Account-Anfrage) darf nicht abreissen, nur weil Telegram down ist.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import requests  # local import: vermeidet Hard-Dep im Modul-Header

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            logger.warning(
                "Telegram-Send fehlgeschlagen: HTTP %s — %s", resp.status_code, resp.text[:200]
            )
    except Exception:  # pragma: no cover
        logger.exception("Telegram-Send Exception")


# --- ACCOUNT-ANFRAGE (Public) ---


@app.route("/account/request", methods=["GET"])
def account_request_get():
    return render_template("account_request.html", **_common_template_ctx())


@app.route("/account/request", methods=["POST"])
@limiter.limit("3 per hour")
def account_request_post():
    from db import SessionLocal
    from models_db import AccountRequest

    # Honeypot: Feld 'website' ist fuer Bots gedacht. Mensch sieht es nicht.
    if request.form.get("website", "").strip():
        logger.warning("Account-Anfrage: Honeypot-Treffer von %s", request.remote_addr)
        return redirect(url_for("landing"))

    email = (request.form.get("email", "") or "").strip()[:254]
    display_name = (request.form.get("display_name", "") or "").strip()[:200]
    begruendung = (request.form.get("begruendung", "") or "").strip()[:2000]

    if not email or "@" not in email or not display_name:
        flash("Bitte Name und gültige E-Mail angeben.", "error")
        return redirect(url_for("account_request_get"))

    # Anti-Spam: leere oder ein-Wort-Begründungen filtern. Echte Anfragen
    # erklären in mindestens einem ganzen Satz, warum sie Zugang brauchen.
    if len(begruendung) < 20:
        logger.info(
            "Account-Anfrage abgelehnt: Begründung zu kurz (%d Zeichen) von %s",
            len(begruendung), request.remote_addr,
        )
        flash(
            "Bitte beschreibe in mindestens 20 Zeichen, warum du dr-automate nutzen möchtest.",
            "error",
        )
        return redirect(url_for("account_request_get"))

    with SessionLocal() as session_db:
        req = AccountRequest(
            email=email,
            display_name=display_name,
            begruendung=begruendung,
            remote_addr=request.remote_addr,
        )
        session_db.add(req)
        session_db.commit()
        req_id = req.id

    if ADMIN_EMAIL and app.config["MAIL_SERVER"]:
        try:
            mail.send(
                Message(
                    subject=f"[dr-automate] Account-Anfrage von {display_name}",
                    recipients=[ADMIN_EMAIL],
                    body=(
                        f"Anfrage-ID: {req_id}\n"
                        f"Name: {display_name}\n"
                        f"E-Mail: {email}\n"
                        f"Quell-IP: {request.remote_addr}\n\n"
                        f"Begründung:\n{begruendung}\n"
                    ),
                )
            )
        except Exception:  # pragma: no cover
            logger.exception("Account-Anfrage-Mail an Admin fehlgeschlagen")

    # Telegram parallel zur Mail (eigener Helper, fail-silent).
    from html import escape as _e

    admin_url = url_for("admin_account_requests", _external=True)
    _send_telegram(
        "🔔 <b>dr-automate</b>: neue Account-Anfrage\n\n"
        f"<b>Name:</b> {_e(display_name)}\n"
        f"<b>E-Mail:</b> {_e(email)}\n"
        f"<b>Quell-IP:</b> {_e(request.remote_addr or '?')}\n"
        f"<b>Anfrage-ID:</b> {req_id}\n\n"
        f"<b>Begründung:</b>\n{_e(begruendung) or '<i>(keine)</i>'}\n\n"
        f"➡️ <a href=\"{admin_url}\">Anfragen verwalten</a>"
    )

    flash("Anfrage abgesendet. Wir melden uns per E-Mail, sobald der Account freigeschaltet ist.", "success")
    return redirect(url_for("landing"))


# --- ADMIN: ACCOUNT-REQUESTS-LISTE ---


def _require_admin() -> None:
    """Authelia liefert via login_required schon einen User; zusaetzlich
    pruefen wir ob der explizit als Admin markiert ist."""
    user = getattr(g, "current_user", None)
    if user is None:
        abort(401)
    if user.remote_user not in ADMIN_REMOTE_USERS:
        logger.warning(
            "Admin-Zugriff verweigert fuer remote_user=%s (nicht in ADMIN_REMOTE_USERS)",
            user.remote_user,
        )
        abort(403)


@app.route("/admin/account-requests", methods=["GET"])
@auth.login_required
def admin_account_requests():
    _require_admin()
    from db import SessionLocal
    from models_db import AccountRequest

    with SessionLocal() as session_db:
        # Pending zuerst (alteste zuerst), dann erledigte zur Referenz.
        rows = session_db.execute(
            select(AccountRequest).order_by(AccountRequest.fulfilled, AccountRequest.created_at)
        ).scalars().all()
        items = [
            {
                "id": r.id,
                "display_name": r.display_name,
                "email": r.email,
                "begruendung": r.begruendung,
                "remote_addr": r.remote_addr,
                "created_at": r.created_at,
                "fulfilled": r.fulfilled,
                "fulfilled_at": r.fulfilled_at,
            }
            for r in rows
        ]
    return render_template(
        "admin_account_requests.html",
        items=items,
        **_common_template_ctx(),
    )


@app.route("/admin/account-requests/<int:req_id>/fulfill", methods=["POST"])
@auth.login_required
def admin_account_request_fulfill(req_id: int):
    _require_admin()
    from db import SessionLocal
    from models_db import AccountRequest

    with SessionLocal() as session_db:
        req = session_db.get(AccountRequest, req_id)
        if req is None:
            flash(f"Anfrage #{req_id} nicht gefunden.", "error")
        else:
            req.fulfilled = True
            req.fulfilled_at = datetime.utcnow()
            session_db.commit()
            flash(f"Anfrage #{req_id} ({req.display_name}) als erledigt markiert.", "success")
    return redirect(url_for("admin_account_requests"))


@app.route("/admin/account-requests/<int:req_id>/delete", methods=["POST"])
@auth.login_required
def admin_account_request_delete(req_id: int):
    _require_admin()
    from db import SessionLocal
    from models_db import AccountRequest

    with SessionLocal() as session_db:
        req = session_db.get(AccountRequest, req_id)
        if req is None:
            flash(f"Anfrage #{req_id} nicht gefunden.", "error")
        else:
            display_name = req.display_name
            session_db.delete(req)
            session_db.commit()
            flash(f"Anfrage #{req_id} ({display_name}) geloescht.", "success")
    return redirect(url_for("admin_account_requests"))


# --- DOCS (Public) ---


_BLEACH_ALLOWED_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "strong",
        "em",
        "code",
        "pre",
        "blockquote",
        "ul",
        "ol",
        "li",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "div",
        "span",
    }
)
_BLEACH_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel", "target"],
    "code": ["class"],  # fuer fenced_code language classes
    "th": ["align"],
    "td": ["align"],
    "h1": ["id"],
    "h2": ["id"],
    "h3": ["id"],
    "h4": ["id"],
    "h5": ["id"],
    "h6": ["id"],
}
_BLEACH_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})


@app.route("/docs/", defaults={"slug": "getting-started"}, methods=["GET"])
@app.route("/docs/<slug>", methods=["GET"])
def docs_view(slug: str):
    # Whitelist: nur Slugs ohne Pfad-Tricks.
    if not re.fullmatch(r"[a-z0-9_-]+", slug):
        abort(404)
    path = DOCS_DIR / f"{slug}.md"
    if not path.is_file():
        abort(404)
    text = path.read_text(encoding="utf-8")
    # Markdown -> HTML mit Standard-Extensions (Tabellen, Fenced Code).
    raw_html = md.markdown(text, extensions=["fenced_code", "tables", "toc", "sane_lists"])
    # Defense-in-depth: Markdown-Quelle ist zwar Repo-Code (vertraut), aber wir
    # sanitisieren trotzdem mit einer Allowlist, damit ein versehentlich
    # eingeschmuggelter <script>-Tag in einer docs/*.md nicht direkt zu
    # Stored-XSS wird. Ohne Bleach waere /docs/<slug> ein offener
    # Vertrauensanker auf einer public-Route.
    body = bleach.clean(
        raw_html,
        tags=_BLEACH_ALLOWED_TAGS,
        attributes=_BLEACH_ALLOWED_ATTRIBUTES,
        protocols=_BLEACH_ALLOWED_PROTOCOLS,
        strip=True,
    )
    pages = sorted(p.stem for p in DOCS_DIR.glob("*.md")) if DOCS_DIR.is_dir() else []
    return render_template(
        "docs.html",
        body=body,
        slug=slug,
        pages=pages,
        **_common_template_ctx(),
    )


@app.route("/example", methods=["GET"])
def get_example():
    """Liefert das Beispiel-JSON für das Frontend."""
    example_path = "example_input.json"
    try:
        with open(example_path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Beispiel-Datei nicht gefunden"}), 404
    except Exception:
        logger.exception("Fehler beim Laden des Beispiel-JSON")
        return jsonify({"error": "Interner Fehler beim Laden des Beispiels."}), 500


@app.route("/generate", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT} per minute")
def generate():
    try:
        # Get JSON from form
        json_text = request.form.get("json_data")
        if not json_text:
            logger.warning("Request ohne JSON-Daten erhalten")
            return jsonify({"error": "No JSON data provided"}), 400

        # KI-Zitatmarker aus Rohtext entfernen (z.B. [cite_start], [cite: 1] von Gemini/NotebookLM)
        json_text = _strip_citations_raw(json_text)

        # JSON parsen
        data = json.loads(json_text)

        # KI-Zitatmarker aus String-Werten entfernen (Restbereinigung)
        data = _strip_citations(data)

        # Strikte Validierung mit Pydantic
        is_valid, result = validate_reiseantrag(data)
        if not is_valid:
            logger.warning(f"Ungültige JSON-Struktur: {result}")
            return jsonify({"error": f"Validierungsfehler: {result}"}), 400

        # Create temporary directory for output
        temp_dir = tempfile.mkdtemp()

        # Generate PDF mit dem validierten Modell (inkl. Pydantic-Defaults)
        try:
            output_path = generator.fill_pdf(result.model_dump(), PDF_TEMPLATE_PATH, temp_dir)
            filename = os.path.basename(output_path)

            # Optional persistieren: nur fuer eingeloggte User und nur wenn das
            # Frontend ``save_to_account=1`` mitschickt. Header ``X-Dienstreise-Id``
            # in der Response laesst das Frontend wissen, welche Reise verknuepft wurde.
            response_headers = {}
            if auth.is_authenticated() and request.form.get("save_to_account") == "1":
                try:
                    reise_id = _persist_antrag(request.form.get("dienstreise_id", ""), data, result, output_path)
                    response_headers["X-Dienstreise-Id"] = str(reise_id)
                    logger.info("Antrag in DB persistiert: reise_id=%s user=%s", reise_id, g.current_user.id)
                except Exception:
                    logger.exception("Persistenz fehlgeschlagen — PDF wird trotzdem ausgeliefert")

            # Send file to user
            # We use after_this_request to cleanup the temp dir
            @after_this_request
            def remove_temp_file(response):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    app.logger.error(f"Error removing temp dir: {e}")
                return response

            logger.info(f"PDF erfolgreich generiert: {filename}")
            resp = send_file(output_path, as_attachment=True, download_name=filename)
            for k, v in response_headers.items():
                resp.headers[k] = v
            return resp

        except Exception as e:
            shutil.rmtree(temp_dir)
            raise e

    except json.JSONDecodeError as e:
        logger.error(f"JSON-Parsing-Fehler: {e}")
        return jsonify({"error": "Invalid JSON format"}), 400
    except Exception:
        logger.exception("Unerwarteter Fehler bei Antrag-PDF-Generierung")
        return jsonify({"error": "Interner Fehler bei der PDF-Generierung."}), 500


@app.route("/extract", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT} per minute")
def extract():
    """Extrahiert aus Freitext via DeepSeek das Antrag-JSON (BYOK).

    Erwartet:
      Header 'X-DeepSeek-Key': vom User bereitgestellter API-Key (nie geloggt, nie persistiert).
      Form 'freitext':         Ausschreibung/E-Mail/Notiz.
      Form 'sonderwuensche':   optional, wird an die User-Message angehängt.
    """
    api_key = request.headers.get("X-DeepSeek-Key", "")
    # Fallback: wenn der Header leer ist UND der User authentifiziert ist,
    # holen wir den Key aus dem verschluesselten Server-Profil.
    if not api_key and auth.is_authenticated():
        from db import SessionLocal
        from models_db import UserProfile

        with SessionLocal() as s:
            profile = s.query(UserProfile).filter(UserProfile.user_id == g.current_user.id).first()
            if profile and profile.deepseek_api_key:
                api_key = profile.deepseek_api_key
    freitext = request.form.get("freitext", "")
    sonderwuensche = request.form.get("sonderwuensche", "")

    # Optionaler PDF-Upload: Text aus dem PDF wird an freitext angehaengt.
    # MIME-Whitelist (application/pdf), Magic-Byte-Check, MAX_UPLOAD_PDF_BYTES
    # zusaetzlich zum globalen MAX_CONTENT_LENGTH.
    pdf_file = request.files.get("pdf")
    if pdf_file and pdf_file.filename:
        if (pdf_file.mimetype or "").lower() not in ("application/pdf", "application/x-pdf"):
            return jsonify({"error": "Nur PDF-Dateien werden unterstützt."}), 400
        head = pdf_file.stream.read(5)
        pdf_file.stream.seek(0)
        if not head.startswith(b"%PDF-"):
            return jsonify({"error": "Datei ist kein gültiges PDF."}), 400
        try:
            import pypdf

            reader = pypdf.PdfReader(pdf_file.stream)
            if len(reader.pages) > MAX_PDF_PAGES:
                return jsonify({"error": f"PDF zu lang (max {MAX_PDF_PAGES} Seiten)."}), 400
            pdf_text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
            if not pdf_text:
                return jsonify({"error": "Aus dem PDF konnte kein Text extrahiert werden (Scan ohne OCR?)."}), 400
            # PDF-Text VOR den manuell eingegebenen Freitext setzen (Ausschreibung
            # ist der Haupt-Input, ggf. Anmerkungen aus dem Textfeld danach).
            freitext = pdf_text if not freitext else f"{pdf_text}\n\n--- Zusatz-Notizen ---\n{freitext}"
            logger.info("PDF-Extraktion: %d Seiten, %d Zeichen Text", len(reader.pages), len(pdf_text))
        except Exception as e:
            logger.warning("PDF-Parsing fehlgeschlagen: %s", e)
            return jsonify({"error": "PDF konnte nicht gelesen werden."}), 400

    if not freitext.strip():
        return jsonify({"error": "Bitte Freitext oder PDF angeben."}), 400

    try:
        result = ai_extract.call_deepseek(
            freitext=freitext,
            api_key=api_key,
            system_prompt=_load_system_prompt(),
            sonderwuensche=sonderwuensche,
        )
        # Citation-Marker bereinigen (manche LLMs lassen sich davon nicht abhalten).
        result = _strip_citations(result)
        logger.info("AI-Extraktion erfolgreich")
        return jsonify(result)
    except ai_extract.AIExtractError as e:
        # Bewusst kein Logging von freitext/api_key — nur Statusmeldung.
        logger.warning(f"AI-Extraktion fehlgeschlagen: HTTP {e.status_code} — {e}")
        return jsonify({"error": str(e)}), e.status_code
    except Exception as e:
        logger.exception(f"AI-Extraktion unerwarteter Fehler: {type(e).__name__}")
        return jsonify({"error": "Interner Fehler bei der AI-Extraktion"}), 500


@app.route("/abrechnung", methods=["GET"])
def abrechnung_index():
    """Wizard-UI für die Reisekostenabrechnung."""
    return render_template("abrechnung.html", **_common_template_ctx())


@app.route("/abrechnung/generate", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT} per minute")
def abrechnung_generate():
    """Erzeugt das ausgefüllte Abrechnungs-PDF."""
    try:
        json_text = request.form.get("json_data")
        if not json_text:
            logger.warning("Abrechnung: Request ohne JSON-Daten erhalten")
            return jsonify({"error": "No JSON data provided"}), 400

        data = json.loads(json_text)

        is_valid, result = validate_abrechnung(data)
        if not is_valid:
            logger.warning(f"Abrechnung: Ungültige JSON-Struktur: {result}")
            return jsonify({"error": f"Validierungsfehler: {result}"}), 400

        # Server-autoritative Berechnung: das vom Wizard mitgeschickte 'berechnet'
        # wird verworfen und neu gerechnet, damit Kürzungen (Verpflegung) und
        # Netto-Tagegeld im PDF garantiert mit der NRKVO-Logik übereinstimmen.
        from abrechnung_calc import berechnung

        result.berechnet = berechnung(result)

        temp_dir = tempfile.mkdtemp()
        try:
            output_path = generator_abrechnung.fill_pdf(result, PDF_TEMPLATE_ABRECHNUNG_PATH, temp_dir)
            filename = os.path.basename(output_path)

            response_headers = {}
            if auth.is_authenticated() and request.form.get("save_to_account") == "1":
                try:
                    abr_id = _persist_abrechnung(request.form.get("dienstreise_id", ""), data, output_path)
                    if abr_id is not None:
                        response_headers["X-Abrechnung-Id"] = str(abr_id)
                        logger.info("Abrechnung in DB persistiert: abr_id=%s user=%s", abr_id, g.current_user.id)
                except Exception:
                    logger.exception("Abrechnung-Persistenz fehlgeschlagen — PDF wird trotzdem ausgeliefert")

            @after_this_request
            def remove_temp_file(response):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    app.logger.error(f"Error removing temp dir: {e}")
                return response

            logger.info(f"Abrechnungs-PDF erfolgreich generiert: {filename}")
            resp = send_file(output_path, as_attachment=True, download_name=filename)
            for k, v in response_headers.items():
                resp.headers[k] = v
            return resp
        except Exception as e:
            shutil.rmtree(temp_dir)
            raise e

    except json.JSONDecodeError as e:
        logger.error(f"Abrechnung: JSON-Parsing-Fehler: {e}")
        return jsonify({"error": "Invalid JSON format"}), 400
    except Exception:
        logger.exception("Abrechnung: Unerwarteter Fehler bei PDF-Generierung")
        return jsonify({"error": "Interner Fehler bei der Abrechnungs-PDF-Generierung."}), 500


@app.route("/abrechnung/calc", methods=["POST"])
@limiter.limit(f"{RATE_LIMIT} per minute")
def abrechnung_calc():
    """Liefert die autoritative Berechnung für den Wizard.

    Das Frontend rechnet live in JS, dieser Endpoint dient als Server-Check
    und für komplexere Fälle, in denen das Frontend zu konservativ rechnet.
    """
    from abrechnung_calc import berechnung

    try:
        json_text = request.form.get("json_data") or request.get_data(as_text=True)
        data = json.loads(json_text)
        is_valid, result = validate_abrechnung(data)
        if not is_valid:
            return jsonify({"error": f"Validierungsfehler: {result}"}), 400
        b = berechnung(result)
        return jsonify(b.model_dump())
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON format"}), 400
    except Exception:
        logger.exception("Abrechnung-Calc-Fehler")
        return jsonify({"error": "Interner Fehler bei der Berechnung."}), 500


@app.route("/health", methods=["GET"])
@csrf.exempt
def health_check():
    """Health-Check Endpoint für Container/Monitoring."""
    return jsonify({"status": "healthy", "template_exists": os.path.exists(PDF_TEMPLATE_PATH), "version": "0.1.0"}), 200


@app.after_request
def _set_security_headers(response):
    """Setzt defensive Browser-Header.

    CSP erlaubt 'unsafe-inline' fuer scripts/styles, weil unsere Templates
    inline-Skripte und -Styles enthalten — strikte CSP wuerde nonce-based
    Refactoring der ~1500 Zeilen Wizard-JS erfordern. Trotzdem wirksam
    gegen externe-Script-Injection und data:-URI-Tricks.
    """
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "object-src 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
    )
    return response


@app.errorhandler(429)
def ratelimit_handler(e):
    """Handler für Rate Limit Überschreitung."""
    logger.warning(f"Rate limit exceeded: {request.remote_addr}")
    return jsonify({"error": "Zu viele Anfragen. Bitte warte eine Minute."}), 429


@app.errorhandler(413)
def too_large_handler(e):
    """Handler fuer Upload-Limit-Ueberschreitung (PDF-Upload)."""
    return jsonify({"error": f"Datei zu gross (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."}), 413


if __name__ == "__main__":
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG_MODE})")
    app.run(host=HOST, port=PORT, debug=DEBUG_MODE)
