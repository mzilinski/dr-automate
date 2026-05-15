# Dienstreise-Antrag &amp; -Abrechnung Automatisierung (dr-automate)

Web-Tool für den kompletten Reisekosten-Workflow nach **NRKVO** (niedersächsisches Reisekostenrecht):

- **Antrag** (Formular `035_001`) — aus unstrukturierten Reiseinfos (E-Mails, Notizen) per LLM zu fertigem PDF.
- **Abrechnung** (Formular `035_002`) — Wizard-basierte Eingabe mit automatischer NRKVO-Berechnung (Tagegeld, Kürzungen, Wegstrecke, Übernachtung), Antrags-JSON wird übernommen.

> **Hinweis:** Dieses Tool ersetzt keine rechtliche Prüfung. Erzeugte Anträge und Abrechnungen vor Einreichung selbst gegenchecken. Das verwendete Formular ist niedersachsenspezifisch.

[![CI/CD](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml/badge.svg)](https://github.com/mzilinski/dr-automate/actions/workflows/ci.yml)

## Funktionen

### Antrag (`/`)
*   **5-Schritt-Wizard**: Eingabe (PDF/Text) → Reise (Verkehrsmittel-Abfrage) → KI-Extraktion → Prüfen (strukturierter Review, kein Roh-JSON) → PDF.
*   **Profil-autoritativ**: Antragsteller-, BahnCard- und Großkundenrabatt-Daten kommen aus dem Profil — die KI erzeugt sie nicht (spart Tokens, keine Platzhalter im PDF). Bei eingeloggten Usern re-merged der Server diese Felder beim Erzeugen autoritativ; übrig gebliebene Platzhalter werden abgewiesen.
*   **Verkehrsmittel als Zeit-Kontext**: Die Hin-/Rückreise-Wahl (Profil-Default `standard_verkehrsmittel`, pro Reise änderbar) wird der KI **vor** der Extraktion mitgegeben, damit Reisezeiten realistisch geschätzt werden.
*   **LLM-gestützte Datenextraktion**: Strippbarer System-Prompt (`system_prompt.md`) konvertiert die Ausschreibung in das Reisedaten-JSON. Profil-/Beförderungs-Abschnitte werden zur Laufzeit entfernt.
*   **PDF-Befüllung**: Automatisches Ausfüllen des offiziellen Formulars inkl. Checkbox-Logik für alle Beförderungsarten (PKW § II/§ III, Bahn/Bus, Dienstwagen, Flug) und korrekten Zeilenumbrüchen in Freitextfeldern.

### Abrechnung (`/abrechnung`)
*   **9-stufiger Wizard** mit Stepper-Navigation, Live-Berechnung und Pflichtfeld-Validierung.
*   **Antrag-Import**: Antrags-JSON wird in das Abrechnungs-Schema überführt — alle übernehmbaren Felder (Antragsteller, Reise, Beförderung, Konfiguration) sind vorbefüllt.
*   **NRKVO-Berechnung** (Stand 1.1.2025) clientseitig (live) und serverseitig (autoritativ): Tagegeld nach 24-h-Regel, Kürzungen für unentgeltliche Verpflegung (Frühstück 5,60 €, Mittag/Abend je 11,20 €), Wegstreckenentschädigung mit Cap (§ 5 II: 0,25 €/km max 125 €; § 5 III: 0,38 €/km), Übernachtungsgeld pauschal (20 €/Nacht, max 14), 2-km-Regel.
*   **Export/Import**: Kompletter Wizard-State als JSON downloadbar mit sprechendem Dateinamen `YYYYMMDD_DR-Abrechnung_<Stadt>_<Thema>.json`. Wieder einlesen → Wiedereinstieg in beliebigem Schritt. Wichtig, da Daten nicht serverseitig gespeichert werden und Browser/Geräte-Wechsel sonst zum Datenverlust führen würde.
*   **PDF-Befüllung** des offiziellen Formulars `035_002` inkl. char-für-char-IBAN, Tagegeld-Aufteilung in volle/Teiltage und Wegstrecken-Zeilen für Hin- und Rückreise.

### Geteilt
*   **Optionale AI-Direktextraktion (BYOK)**: Mit hinterlegtem DeepSeek-API-Key wird der Freitext direkt im Tool an DeepSeek geschickt — der Copy-Paste-Umweg über ChatGPT/Claude entfällt. Key bleibt im `localStorage` und wird pro Request einmalig im Header durchgereicht; **kein Server-Logging**, **keine Persistierung**. Ohne Key bleibt alles wie gehabt. Sowohl Antrag als auch Abrechnungs-Wizard können den Freitext nutzen — das extrahierte JSON wird **immer** vor der PDF-Erzeugung zur Prüfung angezeigt.
*   **Robuste Eingabe-Bereinigung**: Markdown-Code-Fences (` ```json ``` `), Begleittext vor/nach dem JSON, Trailing Commas und Zitatmarker (`[cite_start]`, `[cite: 1]` von NotebookLM/Gemini) werden client- und serverseitig entfernt.
*   **Zwei Nutzungsmodi**:
    *   **Gast (Default)**: Profil-Assistent im Browser, Daten ausschließlich im `localStorage`. Keine Server-Persistenz.
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
| `SECRET_KEY` | **Pflicht in Produktion.** Secret für CSRF/Sessions. Generieren mit `python -c "import secrets; print(secrets.token_hex(32))"` | unsicherer Dev-Default |
| `RATE_LIMIT` | Max. Requests/Minute für `/generate` | `10` |
| `TRUST_REMOTE_USER_HEADER` | **Nur in Produktion hinter Authelia/Traefik auf `true` setzen.** Erlaubt der App, die Identität aus dem `Remote-User`-Header zu lesen. In Dev/Tests bleibt es `false`, sonst wäre Header-Spoofing möglich. | `false` |
| `DR_AUTOMATE_ENCRYPTION_KEY` | **Pflicht in Produktion**, wenn Account-Modus genutzt wird. Fernet-Key (32 byte url-safe-base64) für Application-Level-Encryption. Erzeugen mit `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Verlust = Datenverlust. | ephemerer Key in Debug |
| `DR_AUTOMATE_ENCRYPTION_KEY_OLD` | Optional. Alter Fernet-Key für Rotation (App liest mit beiden, schreibt mit dem aktuellen). | leer |
| `DR_AUTOMATE_DATABASE_URL` | SQLite-URL. Bei Production: in persistentem Volume. | `sqlite:///data/dr-automate.db` |
| `DR_AUTOMATE_DATA_DIR` | Verzeichnis für SQLite-DB und generierte PDFs. | `data` |
| `DR_AUTOMATE_ADMIN_EMAIL` | E-Mail-Empfänger für Account-Anfragen aus `/account/request`. | leer |
| `AUTHELIA_LOGOUT_URL` | Ziel des „Abmelden"-Links in der Nav. | `/` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | SMTP-Konfig für Account-Anfrage-Mails. | leer (kein Versand) |
| `IMPRESSUM_URL` | URL zur Impressumsseite | `#` |
| `DATENSCHUTZ_URL` | URL zur Datenschutzerklärung | `#` |

> **Sicherheit in Produktion:** `SECRET_KEY` und `DR_AUTOMATE_ENCRYPTION_KEY` müssen gesetzt sein. Ohne `SECRET_KEY` sind Sessions fälschbar; ohne Encryption-Key kann der Account-Modus keine sensiblen Felder speichern. `TRUST_REMOTE_USER_HEADER=true` darf nur gesetzt sein, wenn die App ausschließlich hinter einem Reverse-Proxy (Traefik+Authelia) erreichbar ist.

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

1.  **Profil** einmalig pflegen (Name, Abteilung, Adresse, ggf. BahnCards, Standard-Verkehrsmittel, optional DeepSeek-Key).
2.  **Eingabe:** Ausschreibung als PDF hochladen oder Text einfügen.
3.  **Reise:** Verkehrsmittel für Hin-/Rückreise wählen (vorbelegt aus dem Profil).
4.  **KI-Extraktion:** mit DeepSeek-Key direkt im Tool, sonst den Prompt nach ChatGPT/Claude kopieren und die JSON-Antwort einfügen.
5.  **Prüfen:** KI-Reisedaten kontrollieren/korrigieren, Verzicht setzen.
6.  **PDF:** „Antrag generieren" — der ausgefüllte PDF-Antrag wird heruntergeladen (eingeloggt: Antragsteller-Daten serverseitig autoritativ aus dem Profil).

## Projektstruktur

```
dr-automate/
├── app.py                 # Flask-Webserver mit CSRF, Rate Limiting
├── generator.py           # Antrags-PDF-Generierung
├── generator_abrechnung.py# Abrechnungs-PDF-Generierung (Formular 035_002)
├── abrechnung_calc.py     # Server-autoritative NRKVO-Berechnung
├── nrkvo_rates.py         # Single Source of Truth für NRKVO-Sätze
├── models.py              # Pydantic-Modelle (Antrag + Abrechnung)
├── system_prompt.md       # KI-Prompt (Vorlage, nur für Antrag)
├── example_input.json     # Beispiel-JSON für Tests
├── requirements_abrechnung.md # Anforderungs-Doku für die Abrechnungs-Erweiterung
├── .env.example           # Umgebungsvariablen-Vorlage
├── forms/                 # PDF-Vorlagen (Antrag + Abrechnung)
├── static/                # Geteilte Assets
│   └── shared.css         # CSS für beide Templates
├── templates/             # HTML-Templates
│   ├── index.html         # Antrag-Interface (Profil-Wizard, JSON-Editor)
│   ├── abrechnung.html    # Abrechnungs-Wizard (9 Schritte, Live-Berechnung)
│   ├── base.html          # Layout für Dashboard/Landing/Profil/Docs
│   ├── landing.html       # Startseite mit Account/Gast-Auswahl
│   ├── dashboard.html     # Reise-Übersicht (Auth-only)
│   ├── dienstreise_genehmigung.html  # Genehmigungs-Datum vermerken
│   ├── profil.html        # Server-seitiges Profil (Auth-only)
│   ├── account_request.html  # Public: Account anfragen
│   └── docs.html          # Markdown-Doku-Renderer
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

**Public (Gast-Modus erlaubt):**

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/` | GET | Antrag-Wizard (Gast + Auth, mit Save-Banner bei Auth) |
| `/abrechnung` | GET | Abrechnungs-Wizard |
| `/abrechnung/generate` | POST | Abrechnungs-PDF generieren (Rate Limited). Mit `save_to_account=1` + Auth: persistiert in DB. |
| `/abrechnung/calc` | POST | Server-autoritative NRKVO-Berechnung |
| `/generate` | POST | Antrags-PDF generieren (Rate Limited: 10/min). Mit `save_to_account=1` + Auth: persistiert in DB, Response-Header `X-Dienstreise-Id`. |
| `/extract` | POST | KI-Extraktion via DeepSeek (BYOK, `X-DeepSeek-Key`-Header) |
| `/example` | GET | Beispiel-JSON für Frontend |
| `/landing` | GET | Startseite mit Account/Gast-Auswahl |
| `/account/request` | GET, POST | Account-Anfrage-Formular (Rate Limited: 3/h, Honeypot) |
| `/docs/<slug>` | GET | Markdown-Doku (getting-started, workflow, account, security, faq, admin) |
| `/health` | GET | Health-Check für Monitoring |

**Auth-only (Authelia-Header `Remote-User` erforderlich):**

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/dashboard` | GET | Reise-Übersicht des eingeloggten Users |
| `/dienstreisen/<id>/antrag-json` | GET | Antrag-JSON für Wizard-Pre-Fill (Owner-Check) |
| `/dienstreisen/<id>/abrechnung-json` | GET | Abrechnungs-JSON für Wizard-Pre-Fill |
| `/dienstreisen/<id>/genehmigung` | GET, POST | Genehmigungs-Datum/Aktenzeichen vermerken |
| `/dienstreisen/<id>/antrag.pdf` | GET | Antrag-PDF-Download (Owner-Check) |
| `/dienstreisen/<id>/abrechnung.pdf` | GET | Abrechnungs-PDF-Download (Owner-Check) |
| `/dienstreisen/<id>/delete` | POST | Reise + PDFs löschen |
| `/profil` | GET, POST | Server-seitiges Profil |
| `/profil/json` | GET | Profil als JSON (für Wizard-Pre-Fill) |

## NRKVO-Sätze

Die hinterlegten Sätze (Tagegeld, Wegstreckenentschädigung, Übernachtung, Kürzungen) liegen zentral in `nrkvo_rates.py` mit Stand-Datum. Bei einer Novelle dort anpassen — Frontend und Backend lesen aus derselben Quelle. Aktueller Stand wird im Footer der Abrechnungs-Seite angezeigt.

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
