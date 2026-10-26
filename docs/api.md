# REST-API v1

Mit der API legen Skripte und Assistenten (z. B. ein MCP-Server) Dienstreisen an,
berechnen Abrechnungen und holen die PDFs — ohne Browser. Die vollständige,
maschinenlesbare Beschreibung liegt unter [`/api/v1/openapi.json`](/api/v1/openapi.json).

## Zugang

- **Wer:** vorerst nur Nutzer der Gruppe `admins`.
- **Key anlegen:** [Profil → API-Zugänge](/profil#api). Name, Laufzeit (30/90/365 Tage) und
  Berechtigungen wählen; der Key (`dra_…`) wird **einmal** angezeigt. Höchstens 5 aktive Keys.
- **Senden:** `Authorization: Bearer dra_<prefix>_<secret>` bei jedem Request.
- **Gültigkeit:** bis zum gewählten Ablauf, bis zum Widerruf — und nur, solange du dich
  mindestens alle **90 Tage** im Web mit deinem Account anmeldest.
- Ein Key handelt in deinem Namen. Wie ein Passwort behandeln, nie in Repos oder
  Browser-JavaScript.

| Berechtigung (Scope) | erlaubt |
|---|---|
| `reisen:read` | Reisen, Status und PDFs lesen |
| `reisen:write` | Reisen anlegen, ändern, löschen; Genehmigung, Abrechnung, bezahlt |
| `berechnen` | PDFs ohne Speichern, Abrechnung berechnen, Entfernung |
| `extract` | KI-Extraktion über DeepSeek mit dem Key aus deinem Profil — schickt Text nach China, daher standardmäßig aus |

## Endpunkte

Alle Pfade unter `/api/v1`. Datum/Zeit in Anträgen wie im Vordruck: `DD.MM.YYYY`, `HH:MM`.

| Methode | Pfad | Scope | Zweck |
|---|---|---|---|
| GET | `/me` | – | eigener Account, Scopes, Ablauf |
| GET | `/schema/antrag`, `/schema/abrechnung` | – | JSON-Schema der Eingaben |
| GET | `/prompt` | – | System-Prompt + Kontextblock (Datum, PLZ/Ort) für eigene Extraktion |
| POST | `/antrag/pdf` | berechnen | Antrag-PDF ohne Speichern |
| POST | `/abrechnung/berechnung` | berechnen | NRKVO-Berechnung |
| POST | `/abrechnung/pdf` | berechnen | Abrechnungs-PDF ohne Speichern |
| POST | `/entfernung` | berechnen | PKW-Entfernung (OpenStreetMap/OSRM), 30/Stunde |
| POST | `/extract` | extract | KI-Entwurf aus Text oder PDF |
| GET | `/reisen?status=` | reisen:read | eigene Reisen |
| POST | `/reisen` | reisen:write | Reise anlegen (201, Status `entwurf`, Antrag-PDF gespeichert) |
| GET | `/reisen/{id}` | reisen:read | Reise mit Antrag, Abrechnung und Berechnung |
| PUT | `/reisen/{id}/antrag` | reisen:write | Antrag ersetzen — **409**, sobald genehmigt |
| GET | `/reisen/{id}/antrag.pdf`, `/abrechnung.pdf` | reisen:read | gespeicherte PDFs |
| POST | `/reisen/{id}/genehmigung` | reisen:write | `{"datum": "01.05.2026", "aktenzeichen": ""}` |
| PUT | `/reisen/{id}/abrechnung` | reisen:write | Abrechnung speichern, Status `abgerechnet` |
| POST | `/reisen/{id}/bezahlt` | reisen:write | `{"datum": "…"}` oder leer = heute; **409** ohne Abrechnung |
| DELETE | `/reisen/{id}` | reisen:write | Reise und PDFs löschen (204) |

Name, Anschrift, Telefon, Bankdaten und BahnCards kommen **immer aus deinem Profil** —
die API nimmt sie nicht entgegen. Fehlt dort etwas, antwortet sie mit 422 und nennt die Felder.
Unbekannte Felder im JSON werden abgelehnt (422), damit Tippfehler auffallen. Ein
GET-Ergebnis (`antrag`, `abrechnung`) lässt sich unverändert per PUT zurückschreiben.

## Beispiele

```bash
KEY=dra_…
API=https://dr-automate.zilinski.eu/api/v1

curl -s -H "Authorization: Bearer $KEY" $API/me

# Reise anlegen (Antrag v1), Antwort enthält die id
curl -s -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d @antrag.json $API/reisen

# PDF holen
curl -s -H "Authorization: Bearer $KEY" -o antrag.pdf $API/reisen/42/antrag.pdf
```

Minimaler Antrag (`antrag.json`):

```json
{
  "reise_details": {
    "zielort": "Akademie für Lehrerfortbildung, Richthofenstr. 29, 30159 Hannover",
    "reiseweg": "Lingen -> Hannover -> Lingen",
    "zweck": "Fortbildung: Digitale Prüfungsformate",
    "start_datum": "12.03.2027", "start_zeit": "06:30",
    "ende_datum": "12.03.2027", "ende_zeit": "19:00",
    "dienstgeschaeft_beginn_datum": "12.03.2027", "dienstgeschaeft_beginn_zeit": "09:30",
    "dienstgeschaeft_ende_datum": "12.03.2027", "dienstgeschaeft_ende_zeit": "16:00"
  },
  "befoerderung": { "hinreise": { "typ": "BAHN" }, "rueckreise": { "typ": "BAHN" } }
}
```

## Fehler

Fehler kommen als `application/problem+json`:

```json
{ "type": "https://dr-automate.zilinski.eu/docs/api#validation", "title": "Ungültige Eingabe",
  "status": 422, "errors": [{ "loc": ["reise_details", "start_datum"], "msg": "…" }] }
```

| Status | Bedeutung |
|---|---|
| 400 | kein gültiges JSON |
| 401 | Key fehlt, falsch, abgelaufen, widerrufen oder 90 Tage ohne Web-Login |
| 403 | Scope fehlt |
| 404 | nicht gefunden — auch für Reisen anderer Nutzer |
| 409 | passt nicht zum Status (Antrag nach Genehmigung ändern, bezahlt ohne Abrechnung) |
| 415 | Content-Type ist nicht `application/json` |
| 422 | Eingabe ungültig oder Profil unvollständig |
| 429 | Rate-Limit — `Retry-After` beachten |

## Rate-Limits

Je Key: lesen 120/min, schreiben 30/min, PDF-Erzeugung 20/min, `extract` 10/min,
`entfernung` 30/h. Fehlgeschlagene Anmeldungen: 10/min je IP.

## Mit eigenem Sprachmodell (MCP)

Ein Assistent braucht DeepSeek nicht: `GET /prompt` und `GET /schema/antrag` liefern Regeln
und Schema, der Assistent extrahiert selbst, zeigt dir die Daten zur Prüfung und legt die
Reise dann mit `POST /reisen` an.
