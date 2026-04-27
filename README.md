# Dienstreise-Antrag Automatisierung (dr-automate)

Web-Tool, das aus unstrukturierten Reiseinformationen (E-Mails, Notizen) einen ausgefüllten Reisekostenantrag nach **NRKVO 035_001** (niedersächsisches Reisekostenrecht) als PDF erzeugt. Die Datenextraktion übernimmt ein LLM deiner Wahl (ChatGPT, Claude, Gemini, …) anhand eines mitgelieferten System-Prompts; die App validiert das JSON und füllt das offizielle Formular.

> **Hinweis:** Dieses Tool ersetzt keine rechtliche Prüfung. Erzeugte Anträge vor Einreichung selbst gegenchecken. Das verwendete Formular ist niedersachsenspezifisch.

[![CI/CD](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml/badge.svg)](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml)

## Funktionen

*   **LLM-gestützte Datenextraktion**: Mitgelieferter System-Prompt (`system_prompt.md`) konvertiert Freitext in das erwartete JSON. Der Prompt enthält außerdem Anweisungen, das LLM zur Recherche von Bahn-/Flug-/Fährverbindungen aufzufordern, falls dein LLM Web-Zugriff hat.
*   **PDF-Befüllung**: Automatisches Ausfüllen des offiziellen Formulars inkl. Checkbox-Logik für alle Beförderungsarten (PKW § II/§ III, Bahn/Bus, Dienstwagen, Flug) und korrekten Zeilenumbrüchen in Freitextfeldern.
*   **Robuste Eingabe-Bereinigung**: Markdown-Code-Fences (` ```json ``` `), Begleittext vor/nach dem JSON, Trailing Commas und Zitatmarker (`[cite_start]`, `[cite: 1]` von NotebookLM/Gemini) werden client- und serverseitig entfernt.
*   **Profil-Assistent (Browser-only)**: Persönliche Daten (Name, Abteilung, Telefon, Adresse, Mitreisender) werden ausschließlich im `localStorage` gespeichert und in den Prompt eingefügt — keine Serverübertragung.
*   **Optionaler Zugriffsschutz**: Single-Passphrase-Auth über `DR_PASSPHRASE` (Flask-Session). Wenn die Variable leer ist, läuft das Tool ohne Login.
*   **Web-UI**: Eigene CSS-Komponenten (kein Bootstrap), Dark-/Light-Mode via `prefers-color-scheme`, Live-JSON-Validierung.
*   **Smart Naming**: Dateinamen im Format `YYYYMMDD_DR-Antrag_<Stadt>_<Thema>.pdf`.
*   **Eingabe-Validierung**: Strikte Pydantic-Schemas, CSRF-Schutz (`flask-wtf`), Rate-Limit auf `/generate` und `/login` (`flask-limiter`, In-Memory-Storage — bei Multi-Worker-/Multi-Instance-Deployments einen Redis-Backend setzen).

## Voraussetzungen

*   Python 3.12 oder höher
*   [uv](https://github.com/astral-sh/uv) (empfohlen für das moderne Paketmanagement)
*   Docker (optional)

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `PORT` | Server-Port | `5001` (lokal), `5000` (Docker) |
| `HOST` | Server-Host | `0.0.0.0` |
| `FLASK_DEBUG` | Debug-Modus (nur lokal!) | `false` |
| `PDF_TEMPLATE_PATH` | Pfad zur PDF-Vorlage | `forms/DR-Antrag_035_001Stand4-2025pdf.pdf` |
| `SECRET_KEY` | **Pflicht in Produktion.** Secret für CSRF/Sessions. Generieren mit `python -c "import secrets; print(secrets.token_hex(32))"` | unsicherer Dev-Default |
| `RATE_LIMIT` | Max. Requests/Minute für `/generate` | `10` |
| `DR_PASSPHRASE` | Passwort für den Zugriffsschutz (leer = offen, kein Login) | `` |
| `IMPRESSUM_URL` | URL zur Impressumsseite | `#` |
| `DATENSCHUTZ_URL` | URL zur Datenschutzerklärung | `#` |

> **Sicherheit in Produktion:** `SECRET_KEY` und `DR_PASSPHRASE` müssen gesetzt sein. Ohne `SECRET_KEY` sind Sessions fälschbar; ohne `DR_PASSPHRASE` ist die App offen.

Eine Beispiel-Konfiguration findest du in [.env.example](.env.example).

## Installation & Start (Lokal)

1.  **Repository klonen:**
    ```bash
    git clone <repo-url>
    cd dr-automate
    ```

2.  **Abhängigkeiten installieren:**
    ```bash
    # Mit uv (empfohlen):
    uv sync

    # Oder mit pip:
    pip install .
    pip install --group dev   # Tests, Linting
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
├── .github/
│   ├── workflows/ci.yml   # CI/CD Pipeline
│   └── dependabot.yml     # Dependency-Updates
├── Dockerfile             # Container-Konfiguration
├── pyproject.toml         # Python-Projektdefinition
├── ruff.toml              # Linter-Konfiguration
├── pytest.ini             # Test-Konfiguration
├── CONTRIBUTING.md        # Mitarbeit
├── SECURITY.md            # Sicherheitsmeldungen
└── handoff.md             # Offene Punkte aus Code-Review
```

## API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/` | GET | Web-Interface (erfordert Auth wenn `DR_PASSPHRASE` gesetzt) |
| `/login` | GET, POST | Login-Seite. Optional: Auto-Login via `?token=<passphrase>` (⚠️ Token landet in Browser-History und ggf. Reverse-Proxy-Logs — nur in vertrauenswürdigen Kontexten verwenden). |
| `/logout` | GET | Session beenden, zurück zur Login-Seite |
| `/generate` | POST | PDF generieren (Rate Limited: 10/min) |
| `/example` | GET | Beispiel-JSON für Frontend |
| `/health` | GET | Health-Check für Monitoring (kein Auth) |

## Entwicklung

### Tests ausführen

```bash
uv run pytest tests/ -v
uv run pytest tests/ -v --cov=. --cov-report=html   # mit Coverage-Report
```

### Linting & Format

```bash
uvx ruff check .
uvx ruff format .
```

### Security Scan

```bash
uvx bandit -r . -x ./tests
```

### Mitarbeiten

Siehe [CONTRIBUTING.md](CONTRIBUTING.md). Sicherheitslücken bitte gemäß [SECURITY.md](SECURITY.md) melden.

## Lizenz

Dieses Projekt ist unter der [MIT-Lizenz](LICENSE) lizenziert.
