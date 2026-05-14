# Datenschutzerklärung dr-automate

Diese Erklärung gilt zusätzlich zur [allgemeinen Datenschutzerklärung auf zilinski.eu](https://zilinski.eu/datenschutz)
und beschreibt spezifisch die Verarbeitungen auf `dr-automate.zilinski.eu`.

Stand: 2026-05-14

## Verantwortlicher

Malte Zilinski · malte@zilinski.eu · [Impressum](https://zilinski.eu/impressum)

## Welche Daten werden verarbeitet?

### Gast-Modus (ohne Login)

Wer die Seite ohne Account nutzt, verursacht **keine personenbezogene
Server-Speicherung**. Folgende Verarbeitungen finden trotzdem statt:

| Datum | Zweck | Rechtsgrundlage | Dauer |
|---|---|---|---|
| IP-Adresse in Access-Logs | Betrieb + Rate-Limit | Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse) | 14 Tage |
| Form-Daten beim Klick auf „PDF generieren" | PDF-Erzeugung im Arbeitsspeicher | Art. 6 Abs. 1 lit. b DSGVO | nach Response sofort verworfen |
| DeepSeek-API-Key (wenn genutzt) als HTTP-Header | Weiterleitung an deepseek.com | Art. 6 Abs. 1 lit. b DSGVO | nicht gespeichert, nur durchgereicht |
| CSRF-Session-Cookie | Sicherheit (Schutz vor Cross-Site-Request-Forgery) | Art. 6 Abs. 1 lit. f DSGVO | bis Browser-Schließen |

Profildaten (Name, Adresse, IBAN, …) und KI-Schlüssel liegen ausschließlich im
**Browser-localStorage** des Nutzers — sie werden niemals an den Server übermittelt.

### Account-Modus (mit Login)

Beim Anmelden via Authelia (zilinski.eu-SSO) werden zusätzlich folgende Daten
verarbeitet:

| Datum | Zweck | Rechtsgrundlage | Speicherort |
|---|---|---|---|
| Benutzername (`Remote-User`-Header von Authelia) | Account-Identifikation | Vertrag (Art. 6 Abs. 1 lit. b DSGVO) | SQLite-DB, plain |
| E-Mail aus Authelia | Kontakt + Abrechnungs-Formular | Vertrag | SQLite-DB, plain |
| Stammdaten (Vorname, Nachname, Abteilung, Telefon) | Vorbelegung der Dienstreise-Formulare | Vertrag | SQLite-DB, plain |
| **Adresse, IBAN, BIC** | Eintrag auf Reisekosten-Antrag/Abrechnung | Vertrag | SQLite-DB, **Fernet-verschlüsselt** (AES-128-CBC + HMAC-SHA256) |
| **DeepSeek-API-Key** (wenn hinterlegt) | KI-Extraktion auf mehreren Geräten | Einwilligung (Art. 6 Abs. 1 lit. a DSGVO) | SQLite-DB, **Fernet-verschlüsselt** |
| **Dienstreise-Anträge + Abrechnungen** (vollständiges JSON inkl. Reiseziel, Begründung, Beförderung, Bemerkungen) | Persistenz für Lifecycle-Verwaltung | Vertrag | SQLite-DB, **Fernet-verschlüsselt** |
| Generierte PDFs | Download über Dashboard | Vertrag | Dateisystem, Zugriff nur durch Owner |
| Genehmigungs-/Bezahlt-Datum, Aktenzeichen | Lifecycle-Tracking | Vertrag | SQLite-DB, plain |

Encryption-Key liegt in einem Ansible-Vault, getrennt von der DB.

## Drittanbieter

dr-automate übermittelt Daten nur in zwei Fällen außerhalb des eigenen Servers,
und nur auf explizite Aktion des Nutzers:

1. **DeepSeek (Bytedance / VolcEngine, China)** — wenn der Nutzer die
   AI-Extraktion auslöst, werden der eingegebene Freitext (Ausschreibung)
   und das System-Prompt an `api.deepseek.com` gesendet. Datenverarbeitung
   nach Maßgabe von DeepSeek; siehe deren [Datenschutzerklärung](https://platform.deepseek.com/downloads/DeepSeek%20Privacy%20Policy.html).
   Diese Übermittlung findet nur statt, wenn der Nutzer einen eigenen
   API-Key bereitstellt — Auftraggeber für die Verarbeitung ist damit
   der Nutzer selbst.
2. **OpenStreetMap-Stiftung (Nominatim) und OSRM-Demo-Service (Heidelberg
   Institute for Geoinformation Technology)** — beim Klick auf „Entfernung
   schätzen" werden die in diesem Dialog eingegebenen Adressen
   (Start + Ziel, vom Nutzer dort *aktiv eingetragen*) an
   `nominatim.openstreetmap.org` (Geocoding) und `router.project-osrm.org`
   (Routing) gesendet. **Profildaten werden nicht automatisch übermittelt** —
   nur was im Routing-Dialog steht. Keine Account-Anlage, keine Cookies,
   keine Korrelation mit User-Identität auf Empfänger-Seite. Beide Dienste
   sind in Deutschland gehostet.

Außer diesen Fällen verlassen Daten den Server **nicht**.

## Cookies / lokaler Speicher

| Element | Zweck | Notwendigkeit |
|---|---|---|
| `csrf_session` (Flask) | CSRF-Schutz für Formulare | strictly necessary, kein Consent erforderlich |
| `authelia_session` (zilinski.eu) | Single-Sign-On | strictly necessary, nur bei Account-Modus |
| `dr_profile` (Browser-localStorage) | Gast-Modus-Profil + Auto-Save-Flag | strictly necessary für Funktion |
| `dr_abrechnung_reise_id` (Browser-localStorage) | Verknüpfung zwischen Antrag und Abrechnung im Wizard | strictly necessary |

**Keine Tracking-, Analytics- oder Marketing-Cookies.**

## Logs und Auditdaten

- HTTP-Access-Logs: Methode, Pfad, Status, IP, User-Agent. Keine Form-Daten,
  keine API-Keys, keine personenbezogenen Felder. **Aufbewahrung: 14 Tage rolling.**
- Application-Logs: User-Aktionen (Reise angelegt/aktualisiert/gelöscht,
  Profil gespeichert), nie sensible Felder.

## Hosting und Server-Standort

- Anwendungs-Server: VPS in **Deutschland**, betrieben unter eigener Verantwortung
  (kein Public Cloud-Anbieter mit Drittlandbezug, keine Auftragsverarbeitung
  außerhalb der EU).
- Reverse-Proxy + Auth-Layer: Traefik + Authelia, gleicher Standort.
- Daten verlassen den Server nur in den oben unter „Drittanbieter" beschriebenen
  Fällen — alles andere bleibt on-premise.

## Backups

Tägliches Backup der SQLite-DB. Verschlüsselte Felder bleiben verschlüsselt
(gewollt — der Encryption-Key liegt separat im Ansible-Vault, nicht im Backup-
Image). Aufbewahrung: 30 Tage. Backups liegen ebenfalls in Deutschland.

## Deine Rechte (DSGVO)

- **Auskunft** (Art. 15) — Was haben wir über dich? Anfrage per E-Mail an
  malte@zilinski.eu, Antwort innerhalb 30 Tagen.
- **Berichtigung** (Art. 16) — Falsche Daten korrigieren wir auf Anfrage,
  oder du tust es selbst über `/profil`.
- **Löschung** (Art. 17) — Pro Reise: Dashboard → „Löschen". Kompletter
  Account: per E-Mail anfragen, Löschung in DB + Authelia-Users.
- **Datenübertragbarkeit** (Art. 20) — JSON-Export deiner Reisen auf Anfrage.
- **Widerspruch** (Art. 21) — gegen Verarbeitungen auf Basis berechtigter
  Interessen jederzeit möglich.
- **Beschwerde** (Art. 77) — bei der zuständigen Aufsichtsbehörde
  (für Niedersachsen: Die Landesbeauftragte für den Datenschutz Niedersachsen).

## Sicherheit

- HTTPS-only (TLS 1.2+, Let's Encrypt-Zertifikat)
- Authelia mit 2-Faktor-Pflicht (TOTP oder WebAuthn) für alle Account-Routen
- Argon2id-Password-Hashing
- Brute-Force-Schutz (5 Fehlversuche → 15 Min Sperre)
- CSRF-Schutz auf allen Form-Submits
- Rate-Limit auf öffentlichen Endpunkten
- Sensitive Felder Fernet-verschlüsselt at-rest
- IDOR-Schutz: jeder Account sieht nur seine eigenen Reisen

Technische Details: [/docs/security](/docs/security).

## Haftung und Gewähr

Für die Funktionsweise, Verfügbarkeit und Korrektheit der erzeugten PDFs +
NRKVO-Berechnungen siehe separate [Haftungs- und Nutzungshinweise](/docs/haftung).

## Änderungen

Wir behalten uns vor, diese Erklärung an Funktions- oder Rechtsänderungen
anzupassen. Maßgeblich ist die jeweils aktuelle Fassung — Datum oben auf
dieser Seite.
