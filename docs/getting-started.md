# Erste Schritte

dr-automate erzeugt aus deinen Reisedaten die offiziellen PDF-Formulare für Dienstreise-Antrag (DR-Antrag 035-001) und Reisekostenabrechnung (Vordruck 035-002). Du kannst es auf zwei Arten nutzen:

| | Gast-Modus | Mit Account |
|---|---|---|
| **Speicherung** | Nur in deinem Browser (`localStorage`) | Serverseitig, sensible Felder verschlüsselt |
| **Reisen-Historie** | Pro Browser, geht beim Cache-Leeren verloren | Persistent, von jedem Gerät erreichbar |
| **Pre-Fill aus Profil** | Manuell, im Browser | Automatisch, zentrales Profil |
| **Login** | Keiner | Authelia mit 2-Faktor |
| **Eigene KI-Schlüssel** | Möglich (DeepSeek BYOK) | Ebenfalls möglich |

Empfohlen: für regelmäßige Dienstreisen-Erledigungen den **Account-Pfad**. Für eine einmalige Probefahrt reicht der Gast.

## Account-Anlage

Accounts werden **vom Admin manuell freigeschaltet**. Das heißt:

1. Auf [Account anfragen](/account/request) Name + E-Mail + (optional) Begründung angeben.
2. Du bekommst eine E-Mail, sobald dein Account aktiv ist.
3. Auf [Anmelden](/dashboard) klicken → Authelia-Login (Username + Passwort + 2FA).
4. Profil ausfüllen: Adresse, IBAN, BIC, Abteilung, BahnCard – alles einmalig.
5. Mit dem [neuen Antrag](/) starten.

## Erster Antrag

1. Im Wizard die Felder ausfüllen (oder Freitext einer Reise-Ausschreibung in das KI-Feld werfen, falls DeepSeek-Key vorhanden).
2. JSON-Validierung läuft automatisch.
3. „PDF generieren" klicken. Im Account-Modus wird die Reise gespeichert und im **Dashboard** sichtbar.
4. Sobald dein Vorgesetzter die Reise genehmigt: aufs Dashboard, **„Genehmigung vermerken"** drücken, Datum + Aktenzeichen eintragen. Status springt auf `genehmigt`.
5. Nach der Reise: **„Abrechnung starten"** → Abrechnungs-Wizard läuft mit Pre-Fill aus dem Antrag.

## Wo finde ich was?

- **Dashboard**: Übersicht aller Reisen mit Status-Badge und Aktionen.
- **Neuer Antrag**: Wizard für das Antrag-PDF.
- **Abrechnung**: Wizard für das Abrechnungs-PDF.
- **Profil**: Stammdaten, IBAN, BahnCards.
- **Hilfe**: diese Doku.

Weitere Themen:

- [Workflow im Detail](/docs/workflow) – Antrag → Genehmigung → Abrechnung
- [Account vs. Gast](/docs/account) – Welche Daten landen wo
- [Sicherheit](/docs/security) – Verschlüsselung, Backups, Lösch-Anfragen
- [FAQ](/docs/faq) – Häufige Fragen
