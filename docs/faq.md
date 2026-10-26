# FAQ

## Warum kann ich mich nicht selbst registrieren?

Bewusste Design-Entscheidung. Accounts werden vom Admin manuell freigeschaltet, weil:

- dr-automate teilt sich den Auth-Stack mit privaten Tools unter `zilinski.eu`.
- Die Nutzergruppe ist klein und vertrauensbasiert.
- Self-Service-Registrierung würde Spam und Brute-Force-Versuche einladen.

Nutze stattdessen das [Account-Anfrage-Formular](/account/request).

## Was passiert mit meinem DeepSeek-API-Key?

- **Gast-Modus:** Der Key liegt nur im localStorage deines Browsers. Er geht pro Anfrage im HTTP-Header `X-DeepSeek-Key` an den dr-automate-Server, wird zur DeepSeek-API weitergereicht und danach verworfen — kein Logging, keine Speicherung.
- **Account-Modus:** Hinterlegst du den Key im Profil, speichert der Server ihn **verschlüsselt** (Fernet) und nutzt ihn für deine Extraktionen. Er wird nie an den Browser zurückgegeben; löschen kannst du ihn im Profil.

In beiden Fällen geht er an niemanden außer DeepSeek.

Vorzugsweise generierst du einen Key, der nur für dr-automate verwendet wird und der ein Budget-Limit hat – falls er doch mal kompromittiert würde.

## Ich habe meinen Account verloren — wie komme ich wieder rein?

Passwort-Reset läuft über Authelia (Self-Service via E-Mail-OTP). Wenn auch der E-Mail-Zugang weg ist, hilft nur eine Anfrage an den Admin.

## Kann ich dr-automate ohne 2FA nutzen?

Nein, nicht für den Account-Modus. Wer ohne Login arbeiten will: **Gast-Modus** – kein Login, kein 2FA, dafür kein serverseitiger Speicher.

## Funktioniert die Datums-Bearbeitung mobil?

Ja. Der **Abrechnungs-Wizard** nutzt native `<input type="date">`/`type="time"`-Felder mit dem Datepicker des Geräts. Im **Antrag-Wizard** (Schritt 4) sind Datum und Uhrzeit Textfelder im Format `TT.MM.JJJJ` bzw. `HH:MM`, weil sie direkt aus der KI-Antwort kommen.

## Welche NRKVO-Sätze gelten?

Die App pinnt die aktuell gültige NRKVO-Verordnung. Den Stand findest du in der Fußzeile jeder Wizard-Seite. Aktualisierungen erfolgen, sobald eine neue Verordnung veröffentlicht wird – einsehbar in `nrkvo_rates.py`.

## Was wenn der Server down ist?

Im Account-Modus: kein Login möglich, kein Dashboard. Im **Gast-Modus** kannst du keine PDFs generieren, weil die Generierung server-seitig läuft. Du kannst aber die JSON-Daten lokal aufbewahren und bei Wiederverfügbarkeit das PDF erzeugen.

## Wieviele Reisen kann ich speichern?

Keine harte Obergrenze. Die SQLite-DB wächst pro Reise um wenige KB (verschlüsseltes JSON + Plain-Metadaten). PDFs liegen separat auf Disk – Größe abhängig vom Reise-Umfang (typisch 100-500 KB pro Datei).

## Kann ich Daten exportieren?

Pro Reise: PDF-Downloads (Antrag + Abrechnung) im Dashboard. Für komplette JSON-Exports: Anfrage per E-Mail an den Admin.

## Wird der NRKVO-Berechner getestet?

Ja. `tests/test_abrechnung.py` und `tests/test_abrechnung_nrkvo.py` enthalten Berechnungs-Tests gegen die NRKVO-Sätze und -Regeln (Tagegeld je Kalendertag, Kürzung, Daueraufenthalt, Wegstrecken-Deckel). Wenn du eine Berechnungs-Diskrepanz findest – bitte als Bug-Report einreichen mit dem zugrunde liegenden JSON.

## Wie melde ich Bugs?

Per E-Mail an malte@zilinski.eu oder direkt im Repository (falls Zugriff vorhanden).

## Ist dr-automate Open Source?

Ja, MIT-Lizenz. Das Repository liegt auf GitHub (`mzilinski/dr-automate`). Die NRKVO-Berechnungslogik wurde gegen die offizielle Verordnung verifiziert, ist aber keine offiziell anerkannte Stelle – Verantwortung für die korrekte Abrechnung bleibt bei dir.
