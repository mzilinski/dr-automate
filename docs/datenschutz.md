# Datenschutzerklärung dr-automate

Diese Erklärung gilt zusätzlich zur [allgemeinen Datenschutzerklärung auf zilinski.eu](https://zilinski.eu/datenschutz)
und beschreibt spezifisch die Verarbeitungen auf `dr-automate.zilinski.eu`.

Stand: 2026-10-26

## Verantwortlicher

Malte Zilinski · malte@zilinski.eu · [Impressum](https://zilinski.eu/impressum)

## Welche Daten werden verarbeitet?

### Gast-Modus (ohne Login)

Wer die Seite ohne Account nutzt, verursacht **keine dauerhafte
personenbezogene Speicherung auf dem Server**. Folgende Verarbeitungen finden
trotzdem statt:

| Datum | Zweck | Rechtsgrundlage | Dauer |
|---|---|---|---|
| IP-Adresse in Access-Logs | Betrieb + Rate-Limit | Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse) | rotierende Logs, max. 100 MB je Dienst (in der Regel wenige Wochen) |
| Formulardaten beim Klick auf „PDF generieren" (Name, Adresse, IBAN, Reisedaten …) | PDF-Erzeugung | Art. 6 Abs. 1 lit. b DSGVO | nur für die Dauer der Anfrage, danach gelöscht |
| DeepSeek-API-Key (wenn genutzt) als HTTP-Header | Weiterleitung an DeepSeek | Art. 6 Abs. 1 lit. b DSGVO | nicht gespeichert, nur durchgereicht |
| Session-Cookie (CSRF-Token) | Sicherheit (Schutz vor Cross-Site-Request-Forgery) | Art. 6 Abs. 1 lit. f DSGVO | bis Browser-Schließen |

Profildaten (Name, Adresse, IBAN, …) und ein eigener KI-Schlüssel liegen im
**Browser-localStorage**. Beim Erzeugen eines PDFs gehen die Profildaten einmalig
an den Server, der damit das Formular ausfüllt und nichts davon speichert. An die
KI geht davon nur Postleitzahl und Ort (siehe „Drittanbieter").

### Account-Modus (mit Login)

Beim Anmelden via Authelia (zilinski.eu-SSO) werden zusätzlich folgende Daten
verarbeitet:

| Datum | Zweck | Rechtsgrundlage | Speicherort |
|---|---|---|---|
| Benutzername (`Remote-User`-Header von Authelia) | Account-Identifikation | Vertrag (Art. 6 Abs. 1 lit. b DSGVO) | SQLite-DB, plain |
| E-Mail aus Authelia | Kontakt + Abrechnungs-Formular | Vertrag | SQLite-DB, plain |
| Stammdaten (Vorname, Nachname, Abteilung, Telefon) | Vorbelegung der Dienstreise-Formulare | Vertrag | SQLite-DB, plain |
| **Adresse, IBAN, BIC** | Eintrag auf Reisekosten-Antrag/Abrechnung | Vertrag | SQLite-DB, **Fernet-verschlüsselt** (AES-128-CBC + HMAC-SHA256) |
| **DeepSeek-API-Key** (wenn hinterlegt) | KI-Extraktion auf mehreren Geräten (verlässt den Server nur in Richtung DeepSeek) | Einwilligung (Art. 6 Abs. 1 lit. a DSGVO) | SQLite-DB, **Fernet-verschlüsselt** |
| **Dienstreise-Anträge + Abrechnungen** (vollständiges JSON inkl. Reiseziel, Begründung, Beförderung, Bemerkungen) | Persistenz für Lifecycle-Verwaltung | Vertrag | SQLite-DB, **Fernet-verschlüsselt** |
| Generierte PDFs | Download über Dashboard | Vertrag | Dateisystem, Zugriff nur durch Owner |
| Genehmigungs-/Bezahlt-Datum, Aktenzeichen | Lifecycle-Tracking | Vertrag | SQLite-DB, plain |

Encryption-Key liegt in einem Ansible-Vault, getrennt von der DB.

## Drittanbieter und Übermittlungen

dr-automate übermittelt Daten in folgenden Fällen an Dritte:

1. **DeepSeek (Hangzhou DeepSeek Artificial Intelligence Co., Ltd., China)** —
   nur wenn du die KI-Extraktion auslöst und einen eigenen API-Key verwendest.
   Gesendet werden an `api.deepseek.com`: der eingegebene Text bzw. der Text
   des hochgeladenen PDFs, deine Hinweise/Sonderwünsche, der System-Prompt sowie
   ein Kontextblock mit dem heutigen Datum, **Postleitzahl und Ort** deines
   Wohnorts und den gewählten Verkehrsmitteln. Name, Straße, IBAN und andere
   Profildaten werden nicht gesendet.
   China ist ein **Drittland ohne Angemessenheitsbeschluss** der EU; ein der
   DSGVO gleichwertiges Schutzniveau ist nicht gewährleistet, staatliche
   Zugriffe sind möglich. Rechtsgrundlage ist deine **ausdrückliche Einwilligung
   nach Art. 49 Abs. 1 lit. a DSGVO**, die du mit dem Hinterlegen des eigenen
   Schlüssels und dem Auslösen der Extraktion erteilst. Füge deshalb keine
   personenbezogenen Daten Dritter in den Text ein, die nicht für den Antrag
   nötig sind. Ohne KI-Extraktion (Copy-Paste-Weg) findet keine Übermittlung
   statt. Details: [Datenschutzerklärung von DeepSeek](https://platform.deepseek.com/downloads/DeepSeek%20Privacy%20Policy.html).
2. **OpenStreetMap Foundation (Nominatim, Vereinigtes Königreich) und der
   OSRM-Demo-Dienst** — beim Klick auf „Entfernung schätzen" gehen die in
   diesem Dialog stehenden Adressen (Start + Ziel) an
   `nominatim.openstreetmap.org` (Geocoding) und `router.project-osrm.org`
   (Routing). Vorbelegt sind dort deine Wohnanschrift und der Zielort; du
   kannst sie vor dem Klick ändern. Keine Account-Anlage, keine Cookies, keine
   Verknüpfung mit deiner Identität beim Empfänger. Für das Vereinigte
   Königreich besteht ein Angemessenheitsbeschluss der EU.
3. **Account-Anfragen** (`/account/request`) — Name, E-Mail und Begründung
   gehen per E-Mail über den Mail-Dienst GMX (1&1 Mail & Media GmbH,
   Deutschland) an den Betreiber. Zusätzlich gibt es eine Telegram-Benachrichtigung,
   die **nur die Anfrage-Nummer** enthält, keine personenbezogenen Daten.

Darüber hinaus verlassen Daten den Server nicht (Hosting siehe unten).

## Cookies / lokaler Speicher

| Element | Zweck | Notwendigkeit |
|---|---|---|
| `session` (Flask) | CSRF-Schutz für Formulare | unbedingt erforderlich (§ 25 Abs. 2 Nr. 2 TDDDG), keine Einwilligung nötig |
| `authelia_session` (zilinski.eu) | Single-Sign-On | unbedingt erforderlich, nur im Account-Modus |
| `dr_profile` (Browser-localStorage) | Gast-Profil bzw. Kopie des Server-Profils für den Wizard; wird beim Abmelden und beim nächsten Gast-Aufruf gelöscht | unbedingt erforderlich für die Funktion |

**Keine Tracking-, Analytics- oder Marketing-Cookies.**

## Logs und Auditdaten

- HTTP-Access-Logs: Methode, Pfad, Status, IP, User-Agent. Keine Form-Daten,
  keine API-Keys, keine personenbezogenen Felder. **Aufbewahrung: rotierend,
  max. 100 MB je Dienst** (in der Regel wenige Wochen).
- Application-Logs: User-Aktionen (Reise angelegt/aktualisiert/gelöscht,
  Profil gespeichert), nie sensible Felder.

## Hosting und Server-Standort

- Reverse-Proxy + Login (Traefik + Authelia): virtueller Server bei der
  **Hetzner Online GmbH** in Deutschland (Auftragsverarbeitung). Dort endet die
  TLS-Verschlüsselung; die Anfragen gehen über einen verschlüsselten
  WireGuard-Tunnel weiter.
- Anwendung, Datenbank und PDFs: eigener Server des Betreibers in
  **Deutschland**.
- Weitere Übermittlungen nur wie unter „Drittanbieter und Übermittlungen"
  beschrieben.

## Backups

Tägliches Backup der SQLite-DB und der PDFs. Verschlüsselte Felder bleiben
verschlüsselt (der Encryption-Key liegt separat im Ansible-Vault, nicht im
Backup). Aufbewahrung: 7 tägliche, 4 wöchentliche und 12 monatliche Stände
(also bis zu 12 Monate) auf dem eigenen Server in Deutschland. Zusätzlich
gibt es eine **clientseitig verschlüsselte** Offsite-Kopie (restic) in Microsoft
OneDrive (Microsoft Ireland Operations Ltd., Auftragsverarbeitung); Microsoft
sieht davon nur verschlüsselte Daten. Gelöschte Reisen verschwinden aus den
Backups spätestens mit Ablauf dieser Fristen.

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
