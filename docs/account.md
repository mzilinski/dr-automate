# Account vs. Gast

dr-automate kann **mit Account** oder **als Gast** genutzt werden. Beide Wege funktionieren komplett. Der Unterschied liegt in der Persistenz und im Komfort.

## Gast-Modus (ohne Account)

- Keine Anmeldung, kein Server-State.
- Profildaten (Name, Adresse, IBAN, …) liegen im **Browser-localStorage**. Beim Erzeugen eines PDFs gehen sie einmalig an den Server (nur zum Ausfüllen, ohne Speicherung).
- Reisen werden **nicht** serverseitig gespeichert. Du musst PDFs selbst archivieren.
- Für die Abrechnung exportierst du im Antrag-Wizard (Schritt 5) das JSON und importierst es im Abrechnungs-Wizard (Schritt 1).
- Der eigene DeepSeek-API-Key (BYOK) wird ebenfalls nur lokal gehalten und nur **on-demand per Request-Header** an den Server übermittelt – nie geloggt, nie persistiert.

> Gut für: Probefahrten, einmalige Reisen, höchstmögliche Datensparsamkeit.

## Mit Account

- Login über Authelia (Single-Sign-On unter zilinski.eu, 2-Faktor-Pflicht).
- **Profil** wird einmal angelegt und füllt jeden Wizard vor.
- Jede Reise hat einen Lifecycle (`entwurf` → `genehmigt` → `abgerechnet`).
- Antrag-PDF und Abrechnungs-PDF werden serverseitig gespeichert und sind via Dashboard jederzeit als Download verfügbar.
- Sensible Felder (Adresse, IBAN, BIC, das gesamte Antrag-/Abrechnungs-JSON) sind **verschlüsselt at-rest** (Fernet AES-128-CBC + HMAC-SHA256). Siehe [Sicherheit](/docs/security).

> Gut für: regelmäßige Dienstreisen-Erledigungen, Auffindbarkeit alter Vorgänge, weniger manuelle Schritte.

## Was passiert beim ersten Login?

1. Authelia macht den 2FA-Login.
2. dr-automate liest deinen Benutzernamen aus dem `Remote-User`-Header und legt automatisch einen User-Datensatz an (inkl. leeres Profil).
3. Du landest auf dem Dashboard – beim allerersten Mal leer.
4. Über das **Profil**-Menü die Stammdaten ausfüllen. Speichern.
5. Jeder neue Antrag/jede Abrechnung füllt die Felder daraus vor.

## Account beantragen

Self-Service-Registrierung ist **bewusst deaktiviert**. Accounts werden vom Admin freigeschaltet:

1. Auf [Account anfragen](/account/request) das Formular ausfüllen.
2. Du bekommst eine E-Mail, sobald der Admin den Account eingerichtet hat.
3. Erste Anmeldung über das Login (Authelia stellt dabei automatisch TOTP-2FA oder WebAuthn ein).

Hintergrund: dr-automate teilt sich den Auth-Stack mit weiteren Anwendungen unter `zilinski.eu`. Account-Nutzer von dr-automate haben **nur Zugriff auf dr-automate**, nicht auf die Landing-Page oder andere Tools (Gruppe `dr-automate-users`).

## Account löschen

Per E-Mail an malte@zilinski.eu. Datenlöschung erfolgt manuell:

- User-Record und alle verknüpften Reisen / Abrechnungen / PDFs werden aus der Datenbank entfernt (Cascade-Delete).
- Der User wird zusätzlich aus der Authelia-User-DB ausgetragen.

## Wechsel zwischen Gast und Account

- **Gast → Account:** Gast-Reisen werden nicht automatisch übernommen. Tipp: im Gast-Modus das Antrags-JSON exportieren, nach dem Login im Antrag-Wizard (Schritt 3, „KI-Antwort einfügen") einfügen und neu erzeugen — dann wird die Reise im Konto gespeichert. Dein Profil legst du nach dem Login einmal unter **Profil** an; das Gast-Profil im Browser wird dabei durch das Server-Profil ersetzt.
- **Account → Gast:** Daten im Account bleiben erhalten. Beim Abmelden wird die Profil-Kopie aus dem Browser entfernt; im Gast-Modus ist es eine eigene, leere Welt.
