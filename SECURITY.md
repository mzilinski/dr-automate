# Security Policy

## Scope

Dieses Tool füllt deutsche Verwaltungsformulare anhand von Nutzereingaben. Es enthält eine Header-basierte Anmeldung hinter Authelia/Traefik (`TRUST_REMOTE_USER_HEADER`), persönliche API-Keys für `/api/v1`, Verschlüsselung sensibler Felder (Fernet), CSRF-Schutz, Rate-Limiting und Pydantic-Validierung an der Eingabegrenze. Sicherheitslücken in diesen Komponenten sowie in der PDF-Pipeline sind willkommen-zu-melden.

## Lücken melden

Bitte **nicht** als öffentliches GitHub-Issue, sondern entweder über:

- **GitHub Security Advisories**: <https://github.com/mzilinski/dr-automate/security/advisories/new> (bevorzugt, koordinierte Offenlegung)
- **E-Mail**: an den Maintainer im Repo-Profil

Eine Antwort kommt in der Regel innerhalb einer Woche. Da dies ein freizeitlich gepflegtes Tool ist, bitte um Geduld bei Fixes — kritische Findings werden prioritär behandelt.

## Was als Lücke zählt

- Auth-Bypass (fremde Identität annehmen, Zugriff auf Reisen anderer Nutzer, API-Key-Leaks etc.)
- Klartext-Abfluss verschlüsselter Felder (Adresse, IBAN, BIC, API-Keys)
- CSRF-Bypass auf state-changing Endpoints
- Fälschbare Sessions (Probleme mit `SECRET_KEY`-Handling)
- Path Traversal / unbeabsichtigtes File-Read-/Write
- Server-Side Template Injection
- Denial of Service mit kleiner Eingabe
- Probleme mit der Pydantic-Validierung, die zu Crashes oder Datenverlust beim PDF-Render führen

## Was nicht als Lücke zählt

- Betrieb mit `TRUST_REMOTE_USER_HEADER=true` ohne vorgeschalteten Proxy, der die `Remote-*`-Header setzt bzw. überschreibt (Fehlkonfiguration, siehe README).
- DoS durch viele oder große Anfragen innerhalb der konfigurierten Grenzen (Rate-Limits, `DR_AUTOMATE_MAX_UPLOAD_BYTES`, `DR_AUTOMATE_MAX_PDF_PAGES`).

## Hinweis

Wenn dir bei einem der oben ausgenommenen Punkte ein konkreter Exploit-Pfad einfällt, der über die Doku hinausgeht, bitte trotzdem melden.
