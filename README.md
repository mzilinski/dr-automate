# Dienstreise-Antrag &amp; -Abrechnung Automatisierung (dr-automate)

Web-Tool für den kompletten Reisekosten-Workflow nach **NRKVO** (niedersächsisches Reisekostenrecht):

- **Antrag** (Formular `035_001`) — aus unstrukturierten Reiseinfos (E-Mails, Notizen) per LLM zu fertigem PDF.
- **Abrechnung** (Formular `035_002`) — Wizard-basierte Eingabe mit automatischer NRKVO-Berechnung (Tagegeld, Kürzungen, Wegstrecke, Übernachtung), Antrags-JSON wird übernommen.

**Ausprobieren:** <https://dr-automate.zilinski.eu> — ohne Anmeldung im Gast-Modus nutzbar (Profil bleibt im Browser). Selbst betreiben: [Installation](#installation--start-lokal) bzw. [Docker](#nutzung-mit-docker).

> **Hinweis:** Dieses Tool ersetzt keine rechtliche Prüfung. Erzeugte Anträge und Abrechnungen vor Einreichung selbst gegenchecken. Das verwendete Formular ist niedersachsenspezifisch.

[![CI/CD](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml/badge.svg)](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml)

## Funktionen

### Antrag (`/`)
*   **5-Schritt-Wizard**: Eingabe (PDF/Text) → Reise (Verkehrsmittel-Abfrage) → KI-Extraktion → Prüfen (strukturierter Review, kein Roh-JSON) → PDF.
*   **Profil-autoritativ**: Antragsteller-, BahnCard- und Großkundenrabatt-Daten kommen aus dem Profil — die KI erzeugt sie nicht (spart Tokens, keine Platzhalter im PDF). Bei eingeloggten Usern re-merged der Server diese Felder beim Erzeugen autoritativ; übrig gebliebene Platzhalter werden abgewiesen.
*   **Kontext für die KI**: Heutiges Datum, Postleitzahl/Ort des Wohnorts (Start/Ende der Reise) und die Hin-/Rückreise-Wahl (Profil-Default `standard_verkehrsmittel`, pro Reise änderbar) gehen **vor** der Extraktion an die KI — für Jahreszahlen, Reiseweg und realistische Reisezeiten. Straße, Name und IBAN gehen nicht an die KI.
*   **LLM-gestützte Datenextraktion**: Der System-Prompt (`system_prompt.md`) konvertiert die Ausschreibung in das Reisedaten-JSON (nur Reisedaten, Bemerkungen und drei belegpflichtige Angaben). Erlaubte Ergänzungen sind ausdrücklich begrenzt auf geschätzte Reisezeiten und sicher bekannte Anschriften.
*   **PDF-Befüllung**: Automatisches Ausfüllen des offiziellen Formulars inkl. Checkbox-Logik für alle Beförderungsarten (PKW § II/§ III, Bahn/Bus, Dienstwagen, Flug) und korrekten Zeilenumbrüchen in Freitextfeldern.

### Abrechnung (`/abrechnung`)
*   **9-stufiger Wizard** mit Stepper-Navigation, Live-Berechnung und Pflichtfeld-Validierung.
*   **Antrag-Import**: Antrags-JSON wird in das Abrechnungs-Schema überführt — alle übernehmbaren Felder (Antragsteller, Reise, Beförderung, Konfiguration) sind vorbefüllt.
*   **NRKVO-Berechnung** (Stand 1.1.2025) ausschließlich serverseitig (`abrechnung_calc.py`) — die Wizard-Vorschau holt dieselben Werte über `/abrechnung/calc`: Tagegeld je Kalendertag nach § 7 NRKVO i. V. m. § 9 Abs. 4a EStG (> 8 h bzw. An-/Abreisetag 14 €, voller Tag 28 €, ab dem 15. Aufenthaltstag −50 %), Kürzungen für unentgeltliche Verpflegung (Frühstück 5,60 €, Mittag/Abend je 11,20 €, optional pro Tag gedeckelt), Wegstreckenentschädigung (§ 5 II: 0,25 €/km, max. 125 € je Dienstreise; § 5 III: 0,38 €/km; nur selbst gefahrener PKW), Übernachtungsgeld pauschal (20 €/Nacht, max. 14) und Begründungspflicht über 100 €/Belegnacht, 2-km-Regel.
*   **Export/Import**: Kompletter Wizard-State als JSON downloadbar mit sprechendem Dateinamen `YYYYMMDD_DR-Abrechnung_<Stadt>_<Thema>.json`. Wieder einlesen → Wiedereinstieg in beliebigem Schritt. Wichtig im Gast-Modus, da die Daten dort nicht serverseitig gespeichert werden und ein Browser-/Gerätewechsel sonst zum Datenverlust führen würde (mit Account liegen die Reisen im Dashboard).
*   **PDF-Befüllung** des offiziellen Formulars `035_002` inkl. char-für-char-IBAN, Tagegeld-Aufteilung in volle/Teiltage und Wegstrecken-Zeilen für Hin- und Rückreise.

### Geteilt
*   **Optionale AI-Direktextraktion (BYOK)**: Mit hinterlegtem DeepSeek-API-Key wird der Freitext direkt im Tool an DeepSeek geschickt — der Copy-Paste-Umweg über ChatGPT/Claude entfällt. Gäste: Key bleibt im `localStorage` und wird pro Request im Header durchgereicht. Account: Key liegt verschlüsselt im Server-Profil und verlässt den Server nur in Richtung DeepSeek. **Kein Logging.** Ohne Key bleibt alles wie gehabt. Sowohl Antrag als auch Abrechnungs-Wizard können den Freitext nutzen — das extrahierte JSON wird **immer** vor der PDF-Erzeugung zur Prüfung angezeigt.
*   **Robuste Eingabe-Bereinigung**: Markdown-Code-Fences (` ```json ``` `), Begleittext vor/nach dem JSON, Trailing Commas und Zitatmarker (`[cite_start]`, `[cite: 1]` von NotebookLM/Gemini) werden client- und serverseitig entfernt.
*   **Zwei Nutzungsmodi**:
    *   **Gast (Default)**: Profil-Assistent im Browser, Daten im `localStorage`; der Server nutzt sie nur zum Ausfüllen des PDFs. Keine Server-Persistenz.
    *   **Mit Account**: Login über Authelia (ForwardAuth via Traefik, 2-Faktor). Profil + Dienstreisen werden serverseitig in SQLite gespeichert, sensible Felder (Adresse, IBAN, BIC, Reise-JSONs) mit Fernet verschlüsselt. Dashboard mit Lifecycle (entwurf → genehmigt → abgerechnet).
*   **Web-UI**: Eigene CSS-Komponenten (kein Bootstrap), Dark-/Light-Mode via `prefers-color-scheme`, Live-JSON-Validierung. Top-Nav mit Dashboard/Profil/Hilfe, Gast-Modus-Banner bei nicht-eingeloggter Nutzung.
*   **In-App-Doku**: Markdown-basierte Hilfe unter `/docs/<slug>` ([getting-started](docs/getting-started.md), [workflow](docs/workflow.md), [account](docs/account.md), [security](docs/security.md), [admin](docs/admin.md), [faq](docs/faq.md)).
*   **Smart Naming**: Dateinamen im Format `YYYYMMDD_DR-Antrag_<Stadt>_<Thema>.pdf`.
*   **Eingabe-Validierung**: Strikte Pydantic-Schemas, CSRF-Schutz (`flask-wtf`), Rate-Limit auf `/generate` und `/account/request` (`flask-limiter`, In-Memory-Storage — bei Multi-Worker-/Multi-Instance-Deployments einen Redis-Backend setzen).

## Voraussetzungen

*   Python 3.13 oder höher
*   [uv](https://github.com/astral-sh/uv) (empfohlen für das moderne Paketmanagement)
*   Docker (optional)

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `PORT` | Server-Port | `5001` (lokal), `5000` (Docker) |
| `HOST` | Server-Host | `0.0.0.0` |
| `FLASK_DEBUG` | Debug-Modus (nur lokal!) | `false` |
| `PDF_TEMPLATE_PATH` | Pfad zur Antrags-PDF-Vorlage | `forms/DR-Antrag_035_001Stand4-2025pdf.pdf` |
| `PDF_TEMPLATE_ABRECHNUNG_PATH` | Pfad zur Abrechnungs-PDF-Vorlage | `forms/Reisekostenvordruck.pdf` |
| `SECRET_KEY` | **Pflicht.** Secret für CSRF/Sessions. Generieren mit `python -c "import secrets; print(secrets.token_hex(32))"`. Ohne Wert startet die App nur mit `FLASK_DEBUG=true` (dann ephemerer Key). | — |
| `RATE_LIMIT` | Max. Requests/Minute für `/generate`, `/extract` und `/abrechnung/generate` | `10` |
| `TRUST_REMOTE_USER_HEADER` | **Nur in Produktion hinter Authelia/Traefik auf `true` setzen.** Erlaubt der App, die Identität aus dem `Remote-User`-Header zu lesen. In Dev/Tests bleibt es `false`, sonst wäre Header-Spoofing möglich. | `false` |
| `DR_AUTOMATE_ALLOWED_GROUPS` | Komma-Liste der Authelia-Gruppen (`Remote-Groups`), die den Account-Modus nutzen dürfen; alle anderen gelten als Gast. Leer = keine Prüfung. | leer (Produktion: `admins,dr-automate-users`) |
| `ADMIN_REMOTE_USERS` | Komma-Liste der `Remote-User`, die `/admin/account-requests` sehen dürfen. Leer = niemand. | leer |
| `PAPERLESS_URL` | Basis-URL von Paperless-ngx; gesetzt = genehmigte Anträge/bezahlte Abrechnungen können dort abgelegt werden (Token pro Nutzer im Profil). `PAPERLESS_TAG`, `PAPERLESS_DOCTYPE_ANTRAG`, `PAPERLESS_DOCTYPE_ABRECHNUNG` für die Namen. | leer (aus) |
| `DR_AUTOMATE_API_GROUPS` | Authelia-Gruppen, die API-Keys anlegen und nutzen dürfen (siehe `docs/api.md`). | `admins` |
| `DR_AUTOMATE_ENCRYPTION_KEY` | **Pflicht in Produktion**, wenn Account-Modus genutzt wird. Fernet-Key (32 byte url-safe-base64) für Application-Level-Encryption. Erzeugen mit `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Verlust = Datenverlust. | ephemerer Key in Debug |
| `DR_AUTOMATE_ENCRYPTION_KEY_OLD` | Optional. Alter Fernet-Key für Rotation (App liest mit beiden, schreibt mit dem aktuellen). | leer |
| `DR_AUTOMATE_DATABASE_URL` | SQLite-URL. Bei Production: in persistentem Volume. | `sqlite:///data/dr-automate.db` |
| `DR_AUTOMATE_DATA_DIR` | Verzeichnis für SQLite-DB und generierte PDFs. | `data` |
| `DR_AUTOMATE_ADMIN_EMAIL` | E-Mail-Empfänger für Account-Anfragen aus `/account/request`. | leer |
| `AUTHELIA_LOGOUT_URL` | Ziel des „Abmelden"-Links in der Nav. | `/` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | SMTP-Konfig für Account-Anfrage-Mails. | leer (kein Versand) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optionaler Hinweis auf neue Account-Anfragen (nur Anfrage-Nummer, keine personenbezogenen Daten). Beide leer = aus. | leer |
| `DR_AUTOMATE_MAX_UPLOAD_BYTES` | Maximale Request-Größe (u. a. PDF-Upload in `/extract`). | `10485760` (10 MiB) |
| `DR_AUTOMATE_MAX_PDF_PAGES` | Maximale Seitenzahl eines hochgeladenen PDFs. | `50` |
| `DR_AUTOMATE_DOCS_DIR` | Verzeichnis der In-App-Doku (`/docs/<slug>`). | `docs` |
| `IMPRESSUM_URL` | URL zur Impressumsseite | `#` |
| `DATENSCHUTZ_URL` | URL zur Datenschutzerklärung | `#` |

> **Sicherheit in Produktion:** `SECRET_KEY` und `DR_AUTOMATE_ENCRYPTION_KEY` müssen gesetzt sein. Ohne `SECRET_KEY` sind Sessions fälschbar; ohne Encryption-Key kann der Account-Modus keine sensiblen Felder speichern. `TRUST_REMOTE_USER_HEADER=true` darf nur gesetzt sein, wenn die App ausschließlich hinter einem Reverse-Proxy (Traefik+Authelia) erreichbar ist.

Eine Beispiel-Konfiguration findest du in [.env.example](.env.example). Die App liest die Datei **nicht** selbst ein — sie ist für `docker run --env-file .env` bzw. Docker Compose gedacht; lokal die Variablen exportieren.

## Installation & Start (Lokal)

1.  **Repository klonen:**
    ```bash
    git clone https://github.com/mzilinski/dr-automate.git
    cd dr-automate
    ```

2.  **Abhängigkeiten installieren:**
    ```bash
    # Mit uv (empfohlen):
    uv sync

    # Oder mit pip (ohne Lockfile — Versionen können vom Image abweichen):
    pip install .
    pip install --group dev   # Tests, Linting
    ```

3.  **Anwendung starten:**
    ```bash
    # Entwicklung: Debug-Modus erzeugt ephemere Schlüssel (Sessions/Account-Daten überleben keinen Neustart)
    FLASK_DEBUG=true uv run app.py

    # Ohne Debug-Modus ist SECRET_KEY Pflicht (für den Account-Modus zusätzlich DR_AUTOMATE_ENCRYPTION_KEY):
    SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") uv run app.py
    ```

4.  **Öffnen:**
    Die Anwendung ist nun unter [http://localhost:5001](http://localhost:5001) erreichbar.

## Konfiguration (Persönliche Daten)

### Option A: Profil-Assistent im Browser (empfohlen)

Beim ersten Besuch öffnet sich automatisch ein Profil-Assistent. Die eingegebenen Daten (Name, Schule/Abteilung/Funktion, Telefon, Adresse, Mitreisende) liegen im `localStorage` des Browsers und gehen nur beim Erzeugen des PDFs an den Server. Der System-Prompt enthält sie nicht — die KI bekommt im Kontextblock nur Postleitzahl und Ort.

### Option B: Account

Mit Account (Authelia) liegt das Profil verschlüsselt auf dem Server und ersetzt beim Öffnen der Wizards die Browser-Kopie. Eine personalisierte `system_prompt.local.md` gibt es nicht mehr.

## Nutzung mit Docker

Das Tool ist vollständig containerisiert und kann leicht deployed werden. Der Container läuft aus Sicherheitsgründen als Non-Root User.

1.  **Image bauen:**
    ```bash
    docker build -t dr-automate .
    ```

2.  **Container starten** (`SECRET_KEY` ist Pflicht, sonst bricht der Start ab):
    ```bash
    docker run -p 5000:5000 -e SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") dr-automate
    ```

    Mit eigener Konfiguration und persistenter Datenbank (Account-Modus):
    ```bash
    cp .env.example .env   # SECRET_KEY und DR_AUTOMATE_ENCRYPTION_KEY eintragen
    docker run -p 5000:5000 --env-file .env -e PORT=5000 -v dr-automate-data:/app/data dr-automate
    ```

3.  **Öffnen:**
    Die Anwendung läuft nun unter [http://localhost:5000](http://localhost:5000).

4.  **Health-Check:**
    Der Container verfügt über einen integrierten Health-Check. Der Status kann auch manuell geprüft werden:
    ```bash
    curl http://localhost:5000/health
    ```

## Bedienungsanleitung

1.  **Profil** einmalig pflegen (Name, Abteilung, Adresse, ggf. BahnCards, Standard-Verkehrsmittel, optional DeepSeek-Key).
2.  **Eingabe:** Ausschreibung als PDF hochladen oder Text einfügen.
3.  **Reise:** Verkehrsmittel für Hin-/Rückreise wählen (vorbelegt aus dem Profil).
4.  **KI-Extraktion:** mit DeepSeek-Key direkt im Tool, sonst den Prompt nach ChatGPT/Claude kopieren und die JSON-Antwort einfügen.
5.  **Prüfen:** KI-Reisedaten kontrollieren/korrigieren, Verzicht setzen.
6.  **PDF:** „Antrag generieren" — der ausgefüllte PDF-Antrag wird heruntergeladen (eingeloggt: Antragsteller-Daten serverseitig autoritativ aus dem Profil).

## Projektstruktur

```
dr-automate/
├── app.py                  # Flask-App: Routen, CSRF, Rate Limiting, Doku-Renderer
├── auth.py                 # Authelia-ForwardAuth (Remote-User-Header, Gruppen)
├── services.py             # Gemeinsame Logik für Web-UI und API (PDF, Speichern)
├── generator.py            # Antrags-PDF (Formular 035_001)
├── generator_abrechnung.py # Abrechnungs-PDF (Formular 035_002)
├── abrechnung_calc.py      # Server-autoritative NRKVO-Berechnung
├── nrkvo_rates.py          # Single Source of Truth für NRKVO-Sätze
├── models.py               # Pydantic-Modelle (Antrag + Abrechnung)
├── models_db.py, db.py     # SQLAlchemy-Modelle und DB-Setup (SQLite)
├── crypto.py, rotate_keys.py # Fernet-Verschlüsselung sensibler Felder, Key-Rotation
├── ai_extract.py, ki_kontext.py, pdf_text.py # DeepSeek-Extraktion (BYOK), KI-Kontext, PDF-Text
├── routing.py              # Entfernung über OpenStreetMap/OSRM
├── paperless_sync.py       # Ablage in Paperless-ngx (optional)
├── api_v1.py, api_models.py, api_openapi.py, api_keys.py # REST-API v1
├── system_prompt.md        # KI-Prompt (nur Antrag)
├── example_input.json      # Beispiel-JSON
├── alembic/                # DB-Migrationen (laufen beim Container-Start)
├── forms/                  # Offizielle PDF-Vorlagen
├── templates/, static/     # HTML-Templates, CSS
├── docs/                   # In-App-Doku (/docs/<slug>)
│   └── dev/                # Entwicklungsnotizen (nicht öffentlich gerendert)
├── mcp/                    # MCP-Server für Claude Desktop (nutzt die API v1)
├── tests/                  # pytest-Suite
├── .github/                # CI, Dependabot, Issue-Vorlagen
├── Dockerfile, pyproject.toml, uv.lock, ruff.toml, pytest.ini
└── CONTRIBUTING.md, SECURITY.md, LICENSE
```

## API-Endpunkte

**Public (Gast-Modus erlaubt):**

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/` | GET | Antrag-Wizard (Gast; mit Login → `/dashboard`, mit Parametern → `/konto/`) |
| `/abrechnung` | GET | Abrechnungs-Wizard (Gast; mit Login → `/konto/abrechnung`) |
| `/abrechnung/generate` | POST | Abrechnungs-PDF generieren (Rate Limited). Mit `save_to_account=1` + Auth: persistiert in DB. |
| `/abrechnung/calc` | POST | Server-autoritative NRKVO-Berechnung (Quelle der Wizard-Vorschau, 60/min) |
| `/api/route` | POST | Entfernung schätzen über OpenStreetMap/OSRM (30/h) |
| `/generate` | POST | Antrags-PDF generieren (Rate Limited: 10/min). Mit `save_to_account=1` + Auth: persistiert in DB, Response-Header `X-Dienstreise-Id`. |
| `/extract` | POST | KI-Extraktion via DeepSeek (BYOK, `X-DeepSeek-Key`-Header) |
| `/example` | GET | Beispiel-JSON für Frontend |
| `/landing` | GET | Startseite mit Account/Gast-Auswahl |
| `/account/request` | GET, POST | Account-Anfrage-Formular (Rate Limited: 3/h, Honeypot) |
| `/docs/<slug>` | GET | Markdown-Doku (getting-started, workflow, account, security, faq, admin) |
| `/health` | GET | Health-Check für Monitoring |

**REST-API v1** (`/api/v1/…`, Bearer-Key statt Login, nur `admins`): Reisen anlegen/lesen/ändern,
Berechnung, PDFs, Extraktion — Beschreibung in [docs/api.md](docs/api.md), OpenAPI unter
`/api/v1/openapi.json`, Entwurf und Entscheidungen in [`docs/dev/plan-api-v1.md`](docs/dev/plan-api-v1.md).

**Auth-only (Authelia-Header `Remote-User` erforderlich):**

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/konto/`, `/konto/abrechnung` | GET | Wizards im Account-Modus (Profil, Speichern) |
| `/konto/generate`, `/konto/extract`, `/konto/abrechnung/generate` | POST | Account-Varianten (speichern, Profil-Key) |
| `/dashboard` | GET | Reise-Übersicht des eingeloggten Users |
| `/dienstreisen/<id>/antrag-json` | GET | Antrag-JSON für Wizard-Pre-Fill (Owner-Check) |
| `/dienstreisen/<id>/abrechnung-json` | GET | Abrechnungs-JSON für Wizard-Pre-Fill |
| `/dienstreisen/<id>/genehmigung` | GET, POST | Genehmigungs-Datum/Aktenzeichen vermerken |
| `/dienstreisen/<id>/antrag.pdf` | GET | Antrag-PDF-Download (Owner-Check) |
| `/dienstreisen/<id>/abrechnung.pdf` | GET | Abrechnungs-PDF-Download (Owner-Check) |
| `/dienstreisen/<id>/bezahlt` | POST | Geldeingang vermerken bzw. zurücksetzen (erst nach Abrechnung) |
| `/dienstreisen/<id>/delete` | POST | Reise + PDFs löschen |
| `/admin/account-requests` | GET, POST | Account-Anfragen verwalten (nur `ADMIN_REMOTE_USERS`) |
| `/profil` | GET, POST | Server-seitiges Profil |
| `/profil/json` | GET | Profil als JSON (für Wizard-Pre-Fill) |

## NRKVO-Sätze

Die hinterlegten Sätze (Tagegeld, Wegstreckenentschädigung, Übernachtung, Kürzungen) liegen zentral in `nrkvo_rates.py` mit Stand-Datum. Bei einer Novelle dort anpassen — die Templates bekommen sie als `nrkvo` (Anzeige/Tooltips), gerechnet wird nur in `abrechnung_calc.py`. Aktueller Stand wird im Footer der Abrechnungs-Seite angezeigt.

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
