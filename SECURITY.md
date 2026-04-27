# Security Policy

## Scope

Dieses Tool füllt deutsche Verwaltungsformulare anhand von Nutzereingaben. Es enthält Authentifizierung (Single-Passphrase), CSRF-Schutz, Rate-Limiting und Pydantic-Validierung an der Eingabegrenze. Sicherheitslücken in diesen Komponenten sowie in der PDF-Pipeline sind willkommen-zu-melden.

## Lücken melden

Bitte **nicht** als öffentliches GitHub-Issue, sondern entweder über:

- **GitHub Security Advisories**: <https://github.com/mzilinski/dr-automate/security/advisories/new> (bevorzugt, koordinierte Offenlegung)
- **E-Mail**: an den Maintainer im Repo-Profil

Eine Antwort kommt in der Regel innerhalb einer Woche. Da dies ein freizeitlich gepflegtes Tool ist, bitte um Geduld bei Fixes — kritische Findings werden prioritär behandelt.

## Was als Lücke zählt

- Auth-Bypass (Sessions ohne `DR_PASSPHRASE` aufmachen, Token-Leaks etc.)
- CSRF-Bypass auf state-changing Endpoints
- Fälschbare Sessions (Probleme mit `SECRET_KEY`-Handling)
- Path Traversal / unbeabsichtigtes File-Read-/Write
- Server-Side Template Injection
- Denial of Service mit kleiner Eingabe
- Probleme mit der Pydantic-Validierung, die zu Crashes oder Datenverlust beim PDF-Render führen

## Was nicht als Lücke zählt

- Nutzung des Tools ohne `DR_PASSPHRASE` und `SECRET_KEY` in Produktion (das ist eine Fehlkonfiguration, kein Bug — siehe README).
- "Auto-Login via URL-Token landet in Logs" — das ist dokumentiert, kein Bug. Wenn dir das Risiko zu groß ist, das Feature nicht nutzen.
- DoS durch sehr große Eingaben am `/generate`-Endpoint (Rate-Limit existiert, größenbasierte Limits werden bei Bedarf nachgezogen).

## Bekannte offene Punkte

Diese sind dokumentiert in [`handoff.md`](handoff.md) und werden bearbeitet:

- `SECRET_KEY`-Default sollte ohne Env-Var hart abbrechen (Block 1, Schritt 1).
- Passphrase-Vergleich nicht konstantzeitig (Block 1, Schritt 1).
- Datums-Validator akzeptiert ungültige Daten wie `32.13.2026` (Block 1, Schritt 3).

Wenn dir hier ein konkreter Exploit-Pfad einfällt, der über die Doku hinausgeht, bitte trotzdem melden.
