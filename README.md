# Dienstreise-Antrag Automatisierung (dr-automate)

Dieses Tool automatisiert das Ausfüllen von Dienstreiseanträgen (Formular NRKVO 035_001) mithilfe von KI-gestützter Datenextraktion. Es bietet eine einfache Web-Oberfläche, um unstrukturierte Reisedaten (z. B. aus E-Mails) über ein LLM in ein fertiges PDF-Formular zu verwandeln.

[![CI/CD](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml/badge.svg)](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml)

## Funktionen

*   **KI-Integration**: Nutzt einen optimierten System-Prompt (`system_prompt.md`), um Reisedaten mit einem LLM (z. B. ChatGPT, Claude) in ein strukturiertes JSON-Format zu konvertieren.
*   **Intelligente Verbindungssuche**: Der Prompt weist das LLM an, bei Bedarf Bahn-, Flug- und Fährverbindungen zu recherchieren.
*   **PDF-Generierung**: Füllt das offizielle PDF-Formular automatisch aus, inkl. vollständiger Checkbox-Logik für alle Beförderungsarten (PKW §II/§III, Bahn/Bus, Dienstwagen, Flug) und korrekten Zeilenumbrüchen in Freitextfeldern.
*   **Robuste KI-Output-Bereinigung**: Beim Einfügen werden Markdown-Code-Fences (` ```json ``` `), Begleittext vor/nach dem JSON, Trailing Commas und Zitatmarker (z. B. `[cite_start]`, `[cite: 1]` von NotebookLM/Gemini) automatisch entfernt – serverseitig und clientseitig.
*   **Web-Interface**: Benutzerfreundliche Oberfläche mit Dark/Light Mode, Live-JSON-Validierung (inkl. Erkennung leerer Pflichtfelder) und Ladeanimation (kein Bootstrap, eigene CSS-Komponenten).
*   **Profil-Assistent**: Einmaliges Erfassen persönlicher Daten (Name, Abteilung, Telefon, Adresse, Mitreisender) direkt im Browser. Daten werden in `localStorage` gespeichert und automatisch in den KI-Prompt eingefügt – ohne Serverübertragung.
*   **Zugriffsschutz**: Passwort-gesicherter Zugang via Flask-Session (`DR_PASSPHRASE`). Unterstützt Auto-Login über URL-Token (`/login?token=...`).
*   **Smart Naming**: Generiert aussagekräftige Dateinamen (z. B. `20260510_DR-Antrag_Wangerooge_Fortbildung.pdf`).
*   **Sicherheit**: CSRF-Schutz, Rate Limiting (Nginx + Flask-Limiter), strikte JSON-Validierung mit Pydantic.

## Voraussetzungen

*   Python 3.12 oder höher
*   [uv](https://github.com/astral-sh/uv) (empfohlen für das moderne Paketmanagement)
*   Docker (optional)

## Umgebungsvariablen

Die Anwendung kann über folgende Umgebungsvariablen konfiguriert werden:

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `PORT` | Server-Port | `5001` (lokal), `5000` (Docker) |
| `HOST` | Server-Host | `0.0.0.0` |
| `FLASK_DEBUG` | Debug-Modus aktivieren | `false` |
| `PDF_TEMPLATE_PATH` | Pfad zur PDF-Vorlage | `forms/DR-Antrag_035_001Stand4-2025pdf.pdf` |
| `SECRET_KEY` | Secret für CSRF/Sessions | `dev-secret-key...` |
| `RATE_LIMIT` | Max. Requests/Minute für `/generate` | `10` |
| `DR_PASSPHRASE` | Passwort für den Zugriffsschutz (leer = offen) | `` |
| `IMPRESSUM_URL` | URL zur Impressumsseite | `#` |
| `DATENSCHUTZ_URL` | URL zur Datenschutzerklärung | `#` |

Eine Beispiel-Konfiguration findest du in [.env.example](.env.example).

## Installation & Start (Lokal)

1.  **Repository klonen:**
    ```bash
    git clone <repo-url>
    cd dr-automate
    ```

2.  **Abhängigkeiten installieren:**
    ```bash
    uv sync
    # oder manuell mit pip:
    # pip install flask flask-wtf flask-limiter gunicorn pypdf reportlab pillow pydantic
    
    # Für Entwicklung (Tests, Linting):
    # pip install pytest pytest-cov ruff bandit
    ```

3.  **Anwendung starten:**
    ```bash
    uv run app.py
    ```

4.  **Öffnen:**
    Die Anwendung ist nun unter [http://localhost:5001](http://localhost:5001) erreichbar.

## Konfiguration (Persönliche Daten)

### Option A: Profil-Assistent im Browser (empfohlen)

Beim ersten Besuch öffnet sich automatisch ein Profil-Assistent. Die eingegebenen Daten (Name, Schule/Abteilung/Funktion, Telefon, Adresse, Mitreisender) werden ausschließlich im `localStorage` des Browsers gespeichert – sie werden nie an den Server übertragen. Der System-Prompt wird beim Kopieren automatisch mit diesen Daten befüllt.

### Option B: Lokale System-Prompt-Datei

Für server-seitige Vorausfüllung (z. B. wenn mehrere Personen den selben Browser nutzen):

1.  Kopiere die Datei `system_prompt.md` zu `system_prompt.local.md`.
2.  Bearbeite `system_prompt.local.md` und fülle die Platzhalter (z. B. `[DEIN NAME]`, `[DEINE ABTEILUNG]`) mit deinen echten Daten.
3.  Die Anwendung bevorzugt automatisch die `.local.md`-Datei, falls vorhanden. Diese Datei wird von Git ignoriert und landet nicht im Repository.

## Nutzung mit Docker

Das Tool ist vollständig containerisiert und kann leicht deployed werden. Der Container läuft aus Sicherheitsgründen als Non-Root User.

1.  **Image bauen:**
    ```bash
    docker build -t dr-automate .
    ```

2.  **Container starten:**
    ```bash
    docker run -p 5000:5000 dr-automate
    ```
    
    Mit Umgebungsvariablen:
    ```bash
    docker run -p 5000:5000 -e FLASK_DEBUG=true dr-automate
    ```

3.  **Öffnen:**
    Die Anwendung läuft nun unter [http://localhost:5000](http://localhost:5000).

4.  **Health-Check:**
    Der Container verfügt über einen integrierten Health-Check. Der Status kann auch manuell geprüft werden:
    ```bash
    curl http://localhost:5000/health
    ```

## Bedienungsanleitung

1.  **Schritt 1:** Öffne die Webanwendung.
2.  **Schritt 2:** Kopiere den angezeigten **System-Prompt** und deine spezifische Reiseausschreibung (Text/E-Mail) in ein LLM deiner Wahl (ChatGPT, etc.).
3.  **Schritt 3:** Das LLM generiert ein **JSON-Objekt**. Kopiere dieses JSON.
4.  **Schritt 4:** Füge das JSON in das Textfeld der Webanwendung ein und klicke auf "Antrag Generieren".
5.  **Fertig:** Der ausgefüllte PDF-Antrag wird automatisch heruntergeladen.

## Projektstruktur

```
dr-automate/
├── app.py                 # Flask-Webserver mit CSRF, Rate Limiting
├── generator.py           # PDF-Generierungslogik
├── models.py              # Pydantic-Modelle für JSON-Validierung
├── system_prompt.md       # KI-Prompt (Vorlage)
├── example_input.json     # Beispiel-JSON für Tests
├── .env.example           # Umgebungsvariablen-Vorlage
├── forms/                 # PDF-Vorlagen
├── templates/             # HTML-Templates (Dark/Light Mode, kein Bootstrap)
│   ├── index.html         # Haupt-Interface (Profil-Assistent, JSON-Editor, PDF-Download)
│   └── login.html         # Login-Seite (nur wenn DR_PASSPHRASE gesetzt)
├── tests/                 # Unit-Tests
│   └── test_app.py
├── .github/workflows/     # CI/CD Pipeline
│   └── ci.yml
├── Dockerfile             # Container-Konfiguration
├── pyproject.toml         # Python-Projektdefinition
├── ruff.toml              # Linter-Konfiguration
└── pytest.ini             # Test-Konfiguration
```

## API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/` | GET | Web-Interface (erfordert Auth wenn `DR_PASSPHRASE` gesetzt) |
| `/login` | GET, POST | Login-Seite; Auto-Login via `?token=<passphrase>` |
| `/logout` | GET | Session beenden, zurück zur Login-Seite |
| `/generate` | POST | PDF generieren (Rate Limited: 10/min) |
| `/example` | GET | Beispiel-JSON für Frontend |
| `/health` | GET | Health-Check für Monitoring (kein Auth) |

## Entwicklung

### Tests ausführen

```bash
# Alle Tests
pytest tests/ -v

# Mit Coverage-Report
pytest tests/ -v --cov=. --cov-report=html
```

### Linting

```bash
# Code prüfen
ruff check .

# Automatisch formatieren
ruff format .
```

### Security Scan

```bash
bandit -r . -x ./tests
```

## Lizenz

Dieses Projekt ist unter der [MIT-Lizenz](LICENSE) lizenziert.
