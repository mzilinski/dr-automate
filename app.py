from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import os
import io
import json
import shutil
import tempfile
import generator

app = Flask(__name__)

# Constants
PDF_TEMPLATE_PATH = os.path.join("forms", "DR-Antrag_035_001Stand4-2025pdf.pdf")

# Ensure forms directory exists if valid path provided
if not os.path.exists(PDF_TEMPLATE_PATH):
    print(f"Warning: Template file not found at {PDF_TEMPLATE_PATH}")

@app.route('/', methods=['GET'])
def index():
    # Prefer local personalized prompt if it exists, otherwise fallback to generic
    prompt_file = "system_prompt.md.local" if os.path.exists("system_prompt.md.local") else "system_prompt.md"
    prompt_content = ""
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt_content = f.read()
    except Exception as e:
        prompt_content = f"Error loading prompt file: {e}"
        
    return render_template('index.html', prompt_content=prompt_content)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        # Get JSON from form
        json_text = request.form.get('json_data')
        if not json_text:
            return jsonify({"error": "No JSON data provided"}), 400
            
        data = json.loads(json_text)
        
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
                
            return send_file(output_path, as_attachment=True, download_name=filename)
            
        except Exception as e:
            shutil.rmtree(temp_dir)
            raise e
            
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Port 5001 to avoid conflict with AirPlay Receiver on macOS
    app.run(host='0.0.0.0', port=5001, debug=True)
