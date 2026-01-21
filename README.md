# Dienstreise-Antrag Automatisierung (dr-automate)

Dieses Tool automatisiert das Ausfüllen von Dienstreiseanträgen (Formular NRKVO 035_001) mithilfe von KI-gestützter Datenextraktion. Es bietet eine einfache Web-Oberfläche, um unstrukturierte Reisedaten (z. B. aus E-Mails) über ein LLM in ein fertiges PDF-Formular zu verwandeln.

## Funktionen

*   **KI-Integration**: Nutzt einen optimierten System-Prompt (`system_prompt.md`), um Reisedaten mit einem LLM (z. B. ChatGPT, Claude) in ein strukturiertes JSON-Format zu konvertieren.
*   **PDF-Generierung**: Füllt das offizielle PDF-Formular automatisch aus, inkl. Checkbox-Logik (z. B. PKW-Nutzung, BahnCard).
*   **Web-Interface**: Benutzerfreundliche Oberfläche zum Kopieren des Prompts und Generieren des Antrags.
*   **Smart Naming**: Generiert aussagekräftige Dateinamen (z. B. `20260510_DR-Antrag_Wangerooge_Fortbildung.pdf`).

## Voraussetzungen

*   Python 3.12 oder höher
*   [uv](https://github.com/astral-sh/uv) (empfohlen für das moderne Paketmanagement)
*   Docker (optional)

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
    # pip install flask gunicorn pypdf reportlab pillow
    ```

3.  **Anwendung starten:**
    ```bash
    uv run app.py
    ```

4.  **Öffnen:**
    Die Anwendung ist nun unter [http://localhost:5001](http://localhost:5001) erreichbar.

## Konfiguration (Persönliche Daten)

Damit du nicht jedes Mal deine persönlichen Daten in den Prompt im Web-Interface eintragen musst, kannst du eine lokale Konfigurationsdatei anlegen:

1.  Kopiere die Datei `system_prompt.md` zu `system_prompt.md.local`.
2.  Bearbeite `system_prompt.md.local` und fülle die Platzhalter (z. B. `[DEIN NAME]`, `[DEINE ABTEILUNG]`) mit deinen echten Daten.
3.  Die Anwendung bevorzugt automatisch die `.local`-Datei, falls vorhanden. Diese Datei wird von Git ignoriert und landet nicht im Repository.

## Nutzung mit Docker

Das Tool ist vollständig containerisiert und kann leicht deployed werden.

1.  **Image bauen:**
    ```bash
    docker build -t dr-automate .
    ```

2.  **Container starten:**
    ```bash
    docker run -p 5000:5000 dr-automate
    ```

3.  **Öffnen:**
    Die Anwendung läuft nun unter [http://localhost:5000](http://localhost:5000).

## Bedienungsanleitung

1.  **Schritt 1:** Öffne die Webanwendung.
2.  **Schritt 2:** Kopiere den angezeigten **System-Prompt** und deine spezifische Reiseausschreibung (Text/E-Mail) in ein LLM deiner Wahl (ChatGPT, etc.).
3.  **Schritt 3:** Das LLM generiert ein **JSON-Objekt**. Kopiere dieses JSON.
4.  **Schritt 4:** Füge das JSON in das Textfeld der Webanwendung ein und klicke auf "Antrag Generieren".
5.  **Fertig:** Der ausgefüllte PDF-Antrag wird automatisch heruntergeladen.

## Projektstruktur

*   `app.py`: Der Flask-Webserver.
*   `generator.py`: Kernlogik zum Ausfüllen des PDFs.
*   `system_prompt.md`: Der Prompt für das Sprachmodell.
*   `forms/`: Enthält die leere PDF-Vorlage (`DR-Antrag_035_001Stand4-2025pdf.pdf`).
*   `templates/`: HTML-Templates für die Web-GUI.
*   `Dockerfile`: Konfiguration für den Docker-Container.

## Lizenz

Dieses Projekt ist unter der [MIT-Lizenz](LICENSE) lizenziert.
