# dr-automate MCP-Server

Bindet die REST-API v1 als Werkzeuge in Claude Code, Claude Desktop oder andere
MCP-Clients ein. Ein Skript, Abhängigkeiten per PEP 723 — `uv` installiert sie selbst.

## Einrichten

1. Unter **dr-automate → Profil → API-Zugänge** einen Key anlegen (Scopes
   `reisen:read`, `reisen:write`, `berechnen`).
2. In Claude Code registrieren:

   ```bash
   claude mcp add dr-automate \
     --env DR_AUTOMATE_API_KEY=dra_… \
     -- uv run --script ~/Developer/dr-automate/mcp/dr_automate_mcp.py
   ```

   Claude Desktop (`claude_desktop_config.json`):

   ```json
   { "mcpServers": { "dr-automate": {
       "command": "uv",
       "args": ["run", "--script", "/Users/<du>/Developer/dr-automate/mcp/dr_automate_mcp.py"],
       "env": { "DR_AUTOMATE_API_KEY": "dra_…" } } } }
   ```

Optional: `DR_AUTOMATE_URL` (Standard `https://dr-automate.zilinski.eu`),
`DR_AUTOMATE_PDF_DIR` (Standard `~/Downloads`).

## Werkzeuge

| Tool | Zweck |
|---|---|
| `antrag_regeln` | Regeln, Kontext (Datum, PLZ/Ort) und Schema für die Extraktion |
| `reise_anlegen(antrag, bestaetigt)` | ohne Bestätigung nur Prüfung + Zusammenfassung, mit `bestaetigt=true` anlegen |
| `reisen_auflisten(status)` / `reise_anzeigen(id)` | Überblick bzw. Details inkl. Paperless-Stand |
| `pdf_holen(id, art)` | Antrag- oder Abrechnungs-PDF in den Download-Ordner |
| `genehmigung_vermerken(id, datum, aktenzeichen)` | Status `genehmigt` |
| `abrechnung_schema` / `abrechnung_berechnen(abrechnung)` | Schema bzw. NRKVO-Berechnung ohne Speichern |
| `abrechnung_speichern(id, abrechnung, bestaetigt)` | erst Vorschau, dann speichern + PDF |
| `bezahlt_vermerken(id, datum)` | Status `bezahlt` |
| `an_paperless_senden(id, art)` | PDF an Paperless (Profil-Token nötig) |

Der Assistent extrahiert die Reisedaten selbst — DeepSeek wird dafür nicht gebraucht.
Anlegen und Speichern passieren erst nach ausdrücklicher Bestätigung im Chat.
