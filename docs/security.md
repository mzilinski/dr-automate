# Sicherheit &amp; Datenschutz

Diese Seite erklärt, was dr-automate mit deinen Daten macht – und was nicht.

## Was wird gespeichert?

### Gast-Modus

| Wo | Was |
|---|---|
| Browser-localStorage | Profildaten (Name, Adresse, IBAN, …), DeepSeek-Key (BYOK) |
| Server | **Nichts.** Reisen werden im Wizard nur zur PDF-Generierung verarbeitet, dann verworfen. |

### Mit Account

| Wo | Was | Verschlüsselt? |
|---|---|---|
| SQLite-DB | Benutzername (Authelia-Remote-User), E-Mail, Display-Name, last_login | nein – wird zum Login-Lookup gebraucht |
| SQLite-DB | Vorname, Nachname, Abteilung, Telefon | nein – non-sensible Identifikation |
| SQLite-DB | **Adresse, IBAN, BIC, BahnCards, DeepSeek-API-Key** | **ja, Fernet (AES-128-CBC + HMAC-SHA256)** |
| SQLite-DB | Reise-Metadaten (Titel, Zielort, Datum, Status, Genehmigungs-Datum/Aktenzeichen) | nein – wird zum Sortieren/Filtern auf dem Dashboard gebraucht |
| SQLite-DB | **Volles Antrag-/Abrechnungs-JSON** | **ja, Fernet** |
| Dateisystem | Generierte PDFs (`data/pdfs/<user_id>/<reise_id>/...`) | nein – PDFs liegen im persistenten Volume; Verzeichnisse 0700 + Dateien 0600, nur für den App-Container-User lesbar |

Encryption-Key (`DR_AUTOMATE_ENCRYPTION_KEY`) liegt in einem Ansible-Vault, getrennt vom DB-Dump, und ist nicht im Image enthalten. Verlust des Keys = Datenverlust für die verschlüsselten Felder.

## Was wird **nicht** gespeichert?

- **Im Gast-Modus** keine DeepSeek-API-Keys: Der Key kommt per Request-Header `X-DeepSeek-Key` an den Server, wird ausschließlich für den aktuellen API-Call verwendet und sofort verworfen.
- **Im Account-Modus** *kann* der DeepSeek-Key optional im Profil hinterlegt werden (Multi-Device-Komfort). Dann liegt er Fernet-verschlüsselt in der `user_profiles`-Tabelle und wird im `/extract`-Endpoint als Fallback genutzt, wenn der Wizard keinen Header mitschickt. Der Key kann jederzeit über das Profil-Formular gelöscht werden.
- **Keine Freitext-Eingaben aus der KI-Extraktion** über den Request-Scope hinaus. Logs enthalten den HTTP-Status, nicht den Inhalt.
- **Keine Klartext-IBANs / Klar-Keys in Backups.** Backup-Tooling sieht nur die verschlüsselten Tokens.

## Authentifizierung

Der Login läuft über **Authelia** (zentraler ForwardAuth-Provider unter `zilinski.eu`):

- **Argon2id**-Hashes für Passwörter (Speicher-hart, parametriert: 3 iterations, 64 MiB memory, parallelism 4, salt 16 byte, key 32 byte).
- **2-Faktor** verpflichtend (TOTP + WebAuthn / FIDO2 als Alternativen).
- **Brute-Force-Schutz**: 5 Fehlversuche → 15 Min Sperre.
- **Session-Cookies**: HTTPS-only, Domain `zilinski.eu`, 12h-Expiry, 2h-Inactivity.

dr-automate selbst macht **kein Password-Handling** – die App liest nur den `Remote-User`-Header, den Traefik nach erfolgreicher Authelia-Prüfung setzt.

## Trust-Boundary

In Produktion (hinter Traefik) ist `TRUST_REMOTE_USER_HEADER=true` gesetzt. In jeder anderen Umgebung (lokale Entwicklung, Tests) ist das Flag `false`, und die Header werden **ignoriert**. Damit ist ein Header-Spoofing durch einen externen Angreifer nicht möglich – Traefik überschreibt die Header bei jedem eingehenden Request.

## Rate-Limiting (zwei Schichten)

| Schicht | Wo | Konfiguration | Eigenschaften |
|---|---|---|---|
| **Edge** | Traefik `rate-limit-strict` (`traefik/dynamic/backend-services.yml`) | Ø 5 req/s, Burst 10, **per Client-IP** | Persistent über App-Restarts, wirkt vor der App, blockt Volumen-Flood am frühesten Punkt |
| **Endpoint** | Flask-limiter in `app.py` | Pro Endpoint individuell — z.B. `/generate` 10/min, `/account/request` 3/h, `/api/route` 30/h | In-Memory (`memory://`) — pro App-Prozess, resettet bei Container-Restart |

Die Endpoint-Schicht nutzt **bewusst** kein externes Storage-Backend:

- gunicorn läuft mit `--workers 1 --threads 4` → das In-Memory-Storage ist effektiv App-weit konsistent (nicht pro-Worker).
- Container-Restarts sind selten (Deploy/Update); ein theoretischer Counter-Reset würde nur das Endpoint-Limit kurz lockern, das Traefik-Edge-Limit bleibt aktiv.
- Ein Redis-Sidecar nur für diesen Zweck würde mehr Ops-Komplexität bringen als Sicherheitsgewinn.

**Wann auf Redis upgraden?** Wenn entweder:

- gunicorn auf >1 Worker hochskaliert wird (dann sind Limits pro-Worker und das Gesamt-Limit wird vervielfacht), oder
- ein gezielter Audit-Schutz gegen Restart-Reset gefordert ist.

Migrationspfad: `limits[redis]` als Dependency, neuer `dr-automate-redis`-Container im Compose-Stack, `storage_uri="redis://dr-automate-redis:6379/0"` in `app.py`. Erfordert keine DB-Migration, nur Config + Restart.

## Daten löschen

- Im Dashboard pro Reise auf **„Löschen"** → entfernt Antrag, Abrechnung, PDFs auf Disk und DB-Records (Cascade).
- Kompletten Account inklusive aller Reisen: per E-Mail an malte@zilinski.eu anfragen. Manuelle Löschung in der DB + Austragen aus Authelia-Users.
- DSGVO-Auskunft (Art. 15) und -Berichtigung (Art. 16): formloser Antrag per E-Mail.

## Backups

Tägliches Backup des SQLite-Volumes (verschlüsselte Felder bleiben verschlüsselt, das ist gewollt). Aufbewahrung: 30 Tage. Backups liegen ausschließlich auf eigenen, in DE betriebenen Servern.

## Logs

- Access-Logs: HTTP-Methode, Pfad, Status, IP, User-Agent. Keine Form-Daten, keine Header außer Standard.
- Application-Logs: User-Aktionen (Reise angelegt/aktualisiert/gelöscht, Profil gespeichert), nie sensible Felder.
- Aufbewahrung: 14 Tage rolling.

## Bekannte Limitationen

- Verschlüsselte Felder können **nicht durchsucht** werden (Fernet-Token nicht deterministisch). Wenn du z.B. „alle Reisen mit IBAN DE …" suchen willst – das geht bewusst nicht.
- Beim **Key-Rotation** (alter Key in `DR_AUTOMATE_ENCRYPTION_KEY_OLD`, neuer in `DR_AUTOMATE_ENCRYPTION_KEY`) liest die App weiterhin alte Tokens, schreibt aber neue mit dem neuen Key.
- BCs/Grosskundenrabatte landen im Reise-JSON, also verschlüsselt – die zentralen Profilflags in `user_profiles.bahncards` sind ebenfalls verschlüsselt.
