from flask import Flask, render_template, request, send_file, jsonify, after_this_request, session, redirect, url_for
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import json
import shutil
import tempfile
import logging
import re
import generator
from models import validate_reiseantrag

# --- KONFIGURATION ---
PDF_TEMPLATE_PATH = os.environ.get("PDF_TEMPLATE_PATH", os.path.join("forms", "DR-Antrag_035_001Stand4-2025pdf.pdf"))
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5001))
HOST = os.environ.get("HOST", "0.0.0.0")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
RATE_LIMIT = os.environ.get("RATE_LIMIT", "10")
PASSPHRASE = os.environ.get("DR_PASSPHRASE", "")  # Leer = kein Schutz

# --- LOGGING ---
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- APP SETUP ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

# CSRF-Schutz
csrf = CSRFProtect(app)

# Rate Limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

# Prüfe ob Template existiert
if not os.path.exists(PDF_TEMPLATE_PATH):
    logger.warning(f"Template file not found at {PDF_TEMPLATE_PATH}")


_CITATION_RE = re.compile(r'\s*\[cite:[^\]]+\]', re.IGNORECASE)
_CITATION_RAW_RE = re.compile(r'\[cite_start\]|\[cite_end\]|\s*\[cite:[^\]]+\]', re.IGNORECASE)

def _strip_citations_raw(text: str) -> str:
    """Entfernt KI-Zitatmarker aus rohem JSON-Text vor dem Parsen."""
    return _CITATION_RAW_RE.sub('', text)

def _strip_citations(obj):
    """Entfernt KI-Zitatmarker wie [cite: 1, 2] rekursiv aus allen String-Werten."""
    if isinstance(obj, dict):
        return {k: _strip_citations(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_citations(i) for i in obj]
    if isinstance(obj, str):
        return _CITATION_RE.sub('', obj).strip()
    return obj


def _legal_urls():
    return dict(
        impressum_url=os.environ.get("IMPRESSUM_URL", "#"),
        datenschutz_url=os.environ.get("DATENSCHUTZ_URL", "#"),
    )


# --- AUTH ---
_OPEN_ENDPOINTS = {"health_check", "login", "logout", "static"}

@app.before_request
def require_auth():
    if not PASSPHRASE:
        return  # Kein Passwort konfiguriert → offen
    if request.endpoint in _OPEN_ENDPOINTS:
        return
    if not session.get("authenticated"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    # Auto-Login via URL-Token (z.B. aus Landing-Page-Link)
    url_token = request.args.get("token", "")
    if url_token and url_token == PASSPHRASE:
        session["authenticated"] = True
        logger.info(f"Auto-Login via URL-Token von {request.remote_addr}")
        return redirect(url_for("index"))

    error = False
    if request.method == "POST":
        if request.form.get("passphrase", "") == PASSPHRASE:
            session["authenticated"] = True
            logger.info(f"Erfolgreicher Login von {request.remote_addr}")
            return redirect(url_for("index"))
        error = True
        logger.warning(f"Fehlgeschlagener Login-Versuch von {request.remote_addr}")
    return render_template("login.html", error=error, **_legal_urls())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route('/', methods=['GET'])
def index():
    # Prefer local personalized prompt if it exists, otherwise fallback to generic
    prompt_file = "system_prompt.local.md" if os.path.exists("system_prompt.local.md") else "system_prompt.md"
    prompt_content = ""
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt_content = f.read()
    except Exception as e:
        prompt_content = f"Error loading prompt file: {e}"
        
    return render_template('index.html', prompt_content=prompt_content, **_legal_urls())


@app.route('/example', methods=['GET'])
def get_example():
    """Liefert das Beispiel-JSON für das Frontend."""
    example_path = "example_input.json"
    try:
        with open(example_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Beispiel-Datei nicht gefunden"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/generate', methods=['POST'])
@limiter.limit(f"{RATE_LIMIT} per minute")
def generate():
    try:
        # Get JSON from form
        json_text = request.form.get('json_data')
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
        
        # Generate PDF
        try:
            output_path = generator.fill_pdf(data, PDF_TEMPLATE_PATH, temp_dir)
            filename = os.path.basename(output_path)
            
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
            return send_file(output_path, as_attachment=True, download_name=filename)
            
        except Exception as e:
            shutil.rmtree(temp_dir)
            raise e
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON-Parsing-Fehler: {e}")
        return jsonify({"error": "Invalid JSON format"}), 400
    except Exception as e:
        logger.exception(f"Unerwarteter Fehler bei PDF-Generierung: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
@csrf.exempt
def health_check():
    """Health-Check Endpoint für Container/Monitoring."""
    return jsonify({
        "status": "healthy", 
        "template_exists": os.path.exists(PDF_TEMPLATE_PATH),
        "version": "0.1.0"
    }), 200


@app.errorhandler(429)
def ratelimit_handler(e):
    """Handler für Rate Limit Überschreitung."""
    logger.warning(f"Rate limit exceeded: {request.remote_addr}")
    return jsonify({"error": "Zu viele Anfragen. Bitte warte eine Minute."}), 429


if __name__ == '__main__':
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG_MODE})")
    app.run(host=HOST, port=PORT, debug=DEBUG_MODE)
