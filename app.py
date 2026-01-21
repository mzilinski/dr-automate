from flask import Flask, render_template, request, send_file, jsonify, after_this_request
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import json
import shutil
import tempfile
import logging
import generator
from models import validate_reiseantrag

# --- KONFIGURATION ---
PDF_TEMPLATE_PATH = os.environ.get("PDF_TEMPLATE_PATH", os.path.join("forms", "DR-Antrag_035_001Stand4-2025pdf.pdf"))
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5001))
HOST = os.environ.get("HOST", "0.0.0.0")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
RATE_LIMIT = os.environ.get("RATE_LIMIT", "10")

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
        
    return render_template('index.html', prompt_content=prompt_content)


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
        
        # JSON parsen
        data = json.loads(json_text)
        
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
