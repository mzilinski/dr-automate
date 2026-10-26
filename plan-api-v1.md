# Entwurf: dr-automate API v1

Stand: 2026-10-26 · Status: **entschieden (Abschnitt 11), Umsetzung läuft** · Liegt bewusst nicht in `docs/`
(alles dort ist unter `/docs/<slug>` öffentlich).

## 1. Ziel und Abgrenzung

Eine stabile, maschinenlesbare Schnittstelle neben den Wizards, damit Skripte und andere
Werkzeuge Dienstreisen anlegen, berechnen und als PDF holen können — ohne Browser-Session,
ohne CSRF-Umweg und ohne an das interne Wizard-Format gebunden zu sein.

**Anwendungsfälle** (in dieser Reihenfolge priorisiert):

1. **MCP-Server für Claude/andere Assistenten** — „mach mir aus dieser Einladungsmail einen
   Dienstreiseantrag": Der Assistent extrahiert die Reisedaten selbst (eigenes LLM, kein
   DeepSeek nötig), legt die Reise per API an und liefert das PDF.
2. **Skripte** — JSON rein, PDF raus; Abrechnung berechnen lassen.
3. **Andere Dienste im Stack** — z. B. genehmigte Anträge/Abrechnungen nach Paperless
   ablegen, Erinnerung bei Reisen ohne Abrechnung.

**Nicht-Ziele:** öffentliche Registrierung, OAuth/OIDC-Clients für Dritte, Multi-Tenant,
Zugriff auf fremde Reisen (auch nicht für Admins), Webhooks (später möglich).

## 2. Grundentscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Pfad | `/api/v1/…` | eigener Authelia-Bypass, eigene Regeln, Version im Pfad |
| Authentifizierung | **persönliche API-Keys** (`Authorization: Bearer dra_…`) | kein Browser, kein 2FA-Flow; an einen bestehenden Account gebunden |
| Session/`Remote-User` | auf `/api/v1` **ignoriert** | genau ein Auth-Weg pro Route, kein Mischbetrieb |
| CSRF | für `/api/v1` aus | Bearer-Header schickt kein Browser automatisch mit → kein CSRF-Risiko |
| Format | JSON (`application/json`), PDFs als `application/pdf` | |
| Fehler | `application/problem+json` (RFC 9457) | einheitlich, Pydantic-Fehler als Liste |
| Schema | **eigene API-Modelle v1**, gemappt auf die internen Modelle | interne Refactorings (wie das Entfernen von `unterschrift`) brechen die API nicht |
| Strenge | `extra="forbid"` in API-Modellen | Tippfehler in Feldnamen werden 422 statt stillschweigend ignoriert |
| Doku | `/api/v1/openapi.json` aus den Pydantic-Modellen + `docs/api.md` | eine Quelle, testbar |
| Umsetzung | Blueprint `api_v1.py` + `services.py` (gemeinsame Logik aus `app.py` herausgezogen) | `app.py` hat 1500 Zeilen; Wizard und API nutzen dieselben Funktionen |

Kein neues Framework (APIFlask, flask-smorest): Die paar Routen sind mit Blueprint +
Pydantic + einem kleinen OpenAPI-Builder schneller und ohne neue Abhängigkeit umgesetzt.

## 3. API-Keys

### Datenmodell (Migration `008_api_keys`)

| Spalte | Typ | Inhalt |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK users, `ON DELETE CASCADE` | Eigentümer |
| `name` | str(100) | frei, z. B. „MCP Laptop" |
| `prefix` | str(12), unique | öffentlicher Teil zum Nachschlagen, z. B. `k7Hq2mZp` |
| `secret_hash` | str(64) | SHA-256 des vollständigen Tokens |
| `scopes` | JSON | Liste, siehe unten |
| `created_at`, `last_used_at`, `expires_at`, `revoked_at` | datetime | |

**Token-Format:** `dra_<prefix>_<secret>` mit 32 Byte Zufall (`secrets.token_urlsafe`).
Wird **einmal** beim Anlegen angezeigt, danach nur noch Präfix + Name. SHA-256 genügt
(Token hat volle Entropie, kein Passwort); Vergleich mit `hmac.compare_digest`.
Das Präfix `dra_` macht Leaks per Secret-Scanner (gitleaks, GitHub) erkennbar.

### Scopes

| Scope | erlaubt |
|---|---|
| `reisen:read` | Reisen, Status, PDFs lesen |
| `reisen:write` | Reisen anlegen/ändern/löschen, Genehmigung, Abrechnung, bezahlt |
| `berechnen` | zustandslose Berechnung, PDF-Erzeugung ohne Speichern, Entfernung |
| `extract` | KI-Extraktion über DeepSeek mit dem Key aus dem Server-Profil |

`extract` ist **standardmäßig aus**: Er schickt Text nach China (siehe Datenschutzerklärung).

### Verwaltung

- Unter **/profil → API-Zugänge**: anlegen (Name, Scopes, Laufzeit), Liste mit Präfix,
  Scopes, „zuletzt benutzt", widerrufen. Nur mit normaler Authelia-Session (2FA).
- Nur Mitglieder von `DR_AUTOMATE_API_GROUPS` (vorerst `admins`) sehen den Bereich und
  dürfen Keys anlegen; geprüft über `Remote-Groups` der Authelia-Session.
- Höchstens 5 aktive Keys pro Nutzer; Laufzeit 30/90/365 Tage, Standard und Obergrenze 365.
- Admin kann alle Keys eines Nutzers widerrufen (Offboarding-Schritt in `docs/admin.md`).

### Offboarding-Lücke und Gegenmaßnahme

Die API sieht keine Authelia-Header — ein in Authelia deaktivierter Nutzer hätte mit
einem Key weiter Zugriff. Gegenmaßnahme: Ein Key gilt nur, wenn der Eigentümer sich in
den letzten **90 Tagen** über Authelia mit einer API-Gruppe angemeldet hat (neue Spalte
`users.api_berechtigt_bis`, bei jedem Web-Request mit passender Gruppe auf „jetzt + 90 Tage"
gesetzt, höchstens alle 15 Minuten geschrieben). Wer aus `admins` fällt oder in Authelia
deaktiviert wird, verliert den API-Zugang spätestens nach 90 Tagen, auch ohne Widerruf.
Zusätzlich: Offboarding-Checkliste „Keys widerrufen".

## 4. Endpunkte v1

### Konto und Metadaten

| Methode | Pfad | Scope | Ergebnis |
|---|---|---|---|
| GET | `/api/v1/me` | – | Nutzer, Scopes und Ablauf des Keys |
| GET | `/api/v1/schema/antrag` | – | JSON-Schema des Antrags v1 |
| GET | `/api/v1/schema/abrechnung` | – | JSON-Schema der Abrechnung v1 |
| GET | `/api/v1/prompt` | – | System-Prompt für eigene Extraktion (gleicher Text wie im Wizard) |
| GET | `/api/v1/openapi.json` | – (ohne Key) | OpenAPI 3.1 |

`/api/v1/prompt` + `/schema/antrag` sind der Kern für den MCP-Fall: Der Assistent
extrahiert selbst nach denselben Regeln und schickt fertiges JSON.

### Reisen (gespeichert)

| Methode | Pfad | Scope | Verhalten |
|---|---|---|---|
| GET | `/api/v1/reisen?status=` | read | Liste: id, Titel, Zielort, Daten, Status, Genehmigung, vorhandene PDFs |
| POST | `/api/v1/reisen` | write | Body: Antrag v1 → 201, Reise `entwurf` + Antrag-PDF; Antragsteller/BahnCard wie im Wizard **profil-autoritativ** |
| GET | `/api/v1/reisen/{id}` | read | Reise inkl. Antrag- und Abrechnungsdaten |
| PUT | `/api/v1/reisen/{id}/antrag` | write | ersetzt den Antrag; **409**, wenn genehmigt/abgerechnet (kein stilles Anlegen einer Kopie wie im Wizard — die API entscheidet nicht für den Aufrufer) |
| GET | `/api/v1/reisen/{id}/antrag.pdf` | read | PDF |
| POST | `/api/v1/reisen/{id}/genehmigung` | write | `{datum, aktenzeichen?}` → Status `genehmigt` |
| PUT | `/api/v1/reisen/{id}/abrechnung` | write | Body: Abrechnung v1 → Server rechnet, speichert, erzeugt PDF; Antwort enthält die Berechnung |
| GET | `/api/v1/reisen/{id}/abrechnung.pdf` | read | PDF |
| POST | `/api/v1/reisen/{id}/bezahlt` | write | `{datum?}`; 409 ohne Abrechnung |
| DELETE | `/api/v1/reisen/{id}` | write | Reise + PDFs löschen, 204 |

Fremde IDs → **404** (wie im Dashboard, keine ID-Enumeration).

### Zustandslos

| Methode | Pfad | Scope | Verhalten |
|---|---|---|---|
| POST | `/api/v1/antrag/pdf` | berechnen | Antrag v1 → PDF, nichts gespeichert |
| POST | `/api/v1/abrechnung/berechnung` | berechnen | Abrechnung v1 → Berechnung inkl. Hinweisen |
| POST | `/api/v1/abrechnung/pdf` | berechnen | Abrechnung v1 → PDF |
| POST | `/api/v1/entfernung` | berechnen | `{von, nach}` → `{km, minuten, quelle}` |
| POST | `/api/v1/extract` | extract | `{freitext, hinreise, rueckreise}` oder multipart mit PDF → Reisedaten v1; nutzt nur den Key aus dem Server-Profil |

### Schema v1 (Auszug)

Antrag v1 = heutiges Antrag-JSON **ohne** `_meta`, `unterschrift`,
`weitere_anmerkungen_checkbox_aktivieren` (wird abgeleitet) und **ohne Antragsteller**
(kommt immer aus dem Profil):

```json
{
  "reise_details": { "zielort": "…", "reiseweg": "…", "zweck": "…",
    "start_datum": "15.05.2026", "start_zeit": "06:30", "ende_datum": "…", "ende_zeit": "…",
    "dienstgeschaeft_beginn_datum": "…", "dienstgeschaeft_beginn_zeit": "…",
    "dienstgeschaeft_ende_datum": "…", "dienstgeschaeft_ende_zeit": "…",
    "weitere_teilnehmer": [{ "name": "…", "dienststelle": "", "telefon": "" }] },
  "befoerderung": { "hinreise": { "typ": "PKW", "paragraph_5_nrkvo": "II" },
                    "rueckreise": { "typ": "BAHN" }, "begruendung": "" },
  "bemerkungen": "…",
  "angaben": { "dienstgeschaeft_2km_umkreis": false, "anspruch_trennungsgeld": false,
               "kosten_durch_andere_stelle": false },
  "verzicht": { "tagegeld": false, "uebernachtungsgeld": false, "fahrtkosten": false }
}
```

Datum/Zeit bleiben bewusst im Vordruck-Format `DD.MM.YYYY`/`HH:MM` (eine Konvertierung
weniger, identisch mit Prompt und PDF). Abrechnung v1 analog, ohne `berechnet`.

Mapping v1 → intern liegt in `api_models.py`; ein Test prüft für jedes Beispiel in
`docs/api.md`, dass Mapping + Validierung + PDF-Erzeugung durchlaufen.

### Fehlerformat

```json
{ "type": "https://dr-automate.zilinski.eu/docs/api#validation",
  "title": "Ungültige Eingabe", "status": 422,
  "errors": [{ "loc": ["reise_details", "start_datum"], "msg": "Ungültiges Datum: '32.05.2026'" }] }
```

Statuscodes: 400 kaputtes JSON · 401 kein/ungültiger/abgelaufener Key · 403 Scope fehlt ·
404 nicht gefunden/fremd · 409 Statuskonflikt · 413 zu groß · 422 Validierung ·
429 Rate-Limit (mit `Retry-After`) · 502/504 DeepSeek/Routing.

## 5. Rate-Limits

Pro **Key** (nicht pro IP), In-Memory wie heute (1 gunicorn-Worker):

| Gruppe | Limit |
|---|---|
| lesen, Schema, `/me` | 120/min |
| schreiben, Berechnung | 30/min |
| PDF-Erzeugung | 20/min |
| `extract` | 10/min |
| `entfernung` | 30/h (Nominatim-Nutzungsbedingungen) |
| fehlgeschlagene Authentifizierung | 10/min pro IP |

Traefik `rate-limit-strict` bleibt davor.

## 6. Sicherheit

- `Authorization` wird nie geloggt (gunicorn-Access-Log enthält keine Header — Test).
  Pro Request wird die Key-ID geloggt, nicht der Token.
- Keys nur gehasht in der DB; die DB ist ohnehin im verschlüsselten Offsite-Backup.
- `/api/v1` liefert nie Daten anderer Nutzer; Admin-Rechte gibt es über die API nicht.
- CORS: keine `Access-Control-Allow-*`-Header → Browser-Seiten anderer Herkunft können
  die API nicht nutzen; Bearer-Tokens gehören nicht in Browser-JavaScript.
- Request-Größe wie heute (10 MiB), PDF-Parsing über `pdf_text.py` (Kindprozess).
- Profil-autoritativer Merge wie im Wizard: Name, Adresse, Bankdaten und BahnCards kommen
  **nie** aus dem API-Request.

## 7. Datenschutz

Keine neuen Datenkategorien. Ergänzungen in `docs/datenschutz.md`: API-Keys (Name,
Präfix, Hash, Zeitstempel; gelöscht mit dem Account) und der Hinweis, dass `extract`
über die API dieselbe Übermittlung an DeepSeek auslöst wie im Wizard.

## 8. Deployment (`paperless_etal`)

- Authelia-Bypass `'^/api/v1/.*'` in der dr-automate-Regel (die App authentifiziert selbst).
- `strip-identity-headers` am Entrypoint bleibt — die API ignoriert `Remote-*` zusätzlich.
- `authelia-policy-check.yml`: `/api/v1/me` ohne Key → `app` (401), `/api/v1/openapi.json` → `open`.
- Checkmk: optional `http-dr-automate-api` auf `/api/v1/openapi.json`.
- Keine neuen Ports, keine neuen Container.

## 9. MCP-Server (erster Konsument, eigenes kleines Projekt)

Python, `mcp`-SDK, stdio, Key aus Umgebungsvariable. Tools:

| Tool | ruft auf |
|---|---|
| `antrag_regeln` | `GET /prompt` + `GET /schema/antrag` |
| `reise_anlegen(antrag)` | `POST /reisen` → ID + PDF-Pfad |
| `reisen_auflisten(status?)` | `GET /reisen` |
| `pdf_holen(id, art)` | `GET /reisen/{id}/antrag.pdf` bzw. `abrechnung.pdf` → Datei lokal |
| `genehmigung_vermerken(id, datum, az?)` | `POST /reisen/{id}/genehmigung` |
| `abrechnung_berechnen(daten)` / `abrechnung_speichern(id, daten)` | `POST /abrechnung/berechnung` / `PUT /reisen/{id}/abrechnung` |

Der Assistent extrahiert selbst; der Nutzer prüft die Daten im Chat, bevor `reise_anlegen`
läuft (das Tool zeigt eine Zusammenfassung und verlangt Bestätigung).

## 10. Umsetzung in Phasen

| Phase | Inhalt | Aufwand |
|---|---|---|
| 1 | `services.py` (Antrag-/Abrechnungs-Logik aus `app.py`), Migration `api_keys`, Auth-Decorator, `/me`, Key-Verwaltung im Profil, Tests | 1 Tag |
| 2 | API-Modelle v1 + Mapping, Schema-/Prompt-Endpunkte, zustandslose Endpunkte, Problem-JSON, Rate-Limits | 1 Tag |
| 3 | Reisen-Endpunkte inkl. Lifecycle-Regeln, Tests (IDOR, Scopes, 409) | 1 Tag |
| 4 | `extract`, OpenAPI-Builder, `docs/api.md`, Datenschutz, Deployment + Policy-Check | ½ Tag |
| 5 | MCP-Server | ½–1 Tag |
| 6 | Paperless-Anbindung (Abschnitt 11) | 1 Tag |

## 11. Paperless-Anbindung

Ziel: Der **genehmigte Antrag** und die **bezahlte Abrechnung** landen automatisch im
Paperless-Archiv des Nutzers, ohne Download und Upload von Hand.

| Thema | Entscheidung |
|---|---|
| Richtung | dr-automate → Paperless (Upload über die Paperless-REST-API `POST /api/documents/post_document/`) |
| Zugang | pro Nutzer ein **Paperless-API-Token im Profil** (verschlüsselt wie der DeepSeek-Key) + Schalter „automatisch ablegen"; nur für API-Gruppen (vorerst `admins`) |
| Weg | über `https://paperless.zilinski.eu` (VPS → WireGuard). Port 8000 auf dem Backend ist per nftables nur für die VPS offen; so braucht es keine Firewall-Ausnahme |
| Wann | Antrag-PDF beim Vermerken der **Genehmigung**; Abrechnungs-PDF beim Vermerken **„bezahlt"** (Endstand). Entwürfe und Zwischenstände nicht — sonst Duplikate. Zusätzlich Button „an Paperless senden" im Dashboard und `POST /api/v1/reisen/{id}/paperless` |
| Metadaten | Titel („Dienstreiseantrag <Zweck> <Datum>" bzw. „Reisekostenabrechnung …"), `created` = Reisebeginn, Tag `Dienstreise` (muss in Paperless existieren — neue Tags legt nach Paperless-README nur der Mensch an), Dokumenttyp per Name; Korrespondent macht der vorhandene KI-Workflow |
| Besitzer | Upload mit dem Token des Nutzers → Besitzer ist dieser Nutzer, damit sieht der KI-Workflow seine Korrespondenten/Tags (Gotcha aus `paperless/README.md` entfällt) |
| Zuverlässigkeit | Ausgangs-Tabelle `paperless_uploads` (Reise, Art, Status, Versuche, Fehler, Paperless-Dokument-ID); ein Hintergrund-Thread arbeitet sie jede Minute ab, mit Wiederholung (max. 5, wachsender Abstand). Status im Dashboard sichtbar |
| Idempotenz | pro Reise und Art höchstens ein erfolgreicher Upload; „erneut senden" nur ausdrücklich |
| Datenschutz | bleibt im eigenen Stack (kein neuer Dritter); Token verschlüsselt, nie im Browser |

Aufwand: etwa 1 Tag (Phase 6). Spätere Idee, nicht Teil von v1: Einladungs-Mails aus
Paperless per Tag „Dienstreise beantragen" als Entwurf in dr-automate anlegen.

## 12. Entscheidungen (2026-10-26)

1. **Keys:** vorerst nur `admins` (`DR_AUTOMATE_API_GROUPS=admins`).
2. **Laufzeit:** bis 365 Tage (Standard 365).
3. **Antrag nach Genehmigung ändern:** API weist mit **409** ab.
4. **`extract`:** wird angeboten, Scope beim Anlegen standardmäßig aus.
5. **Paperless:** wird mitgeplant (Abschnitt 11) und als Phase 6 umgesetzt.
