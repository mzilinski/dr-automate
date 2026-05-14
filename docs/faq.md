# FAQ

## Warum kann ich mich nicht selbst registrieren?

Bewusste Design-Entscheidung. Accounts werden vom Admin manuell freigeschaltet, weil:

- dr-automate teilt sich den Auth-Stack mit privaten Tools unter `zilinski.eu`.
- Die Nutzergruppe ist klein und vertrauensbasiert.
- Self-Service-Registrierung würde Spam und Brute-Force-Versuche einladen.

Nutze stattdessen das [Account-Anfrage-Formular](/account/request).

## Was passiert mit meinem DeepSeek-API-Key?

Er wird **ausschließlich pro Request** an den dr-automate-Server übermittelt (im HTTP-Header `X-DeepSeek-Key`), zur DeepSeek-API weitergereicht, und nach dem Response sofort verworfen. Kein Logging, keine Persistenz, keine Übertragung an Dritte außer DeepSeek selbst.

Vorzugsweise generierst du einen Key, der nur für dr-automate verwendet wird und der ein Budget-Limit hat – falls er doch mal kompromittiert würde.

## Ich habe meinen Account verloren — wie komme ich wieder rein?

Passwort-Reset läuft über Authelia (Self-Service via E-Mail-OTP). Wenn auch der E-Mail-Zugang weg ist, hilft nur eine Anfrage an den Admin.

## Kann ich dr-automate ohne 2FA nutzen?

Nein, nicht für den Account-Modus. Wer ohne Login arbeiten will: **Gast-Modus** – kein Login, kein 2FA, dafür kein serverseitiger Speicher.

## Funktioniert die Datums-Bearbeitung mobil?

Ja. Der Wizard nutzt das native `<input type="date">`-Element. Auf mobilen Geräten erscheint der OS-Datepicker (iOS/Android). Auf Desktops kommt der Browser-Picker.

## Welche NRKVO-Sätze gelten?

Die App pinnt die aktuell gültige NRKVO-Verordnung. Den Stand findest du in der Fußzeile jeder Wizard-Seite. Aktualisierungen erfolgen, sobald eine neue Verordnung veröffentlicht wird – einsehbar in `nrkvo_rates.py`.

## Was wenn der Server down ist?

Im Account-Modus: kein Login möglich, kein Dashboard. Im **Gast-Modus** kannst du keine PDFs generieren, weil die Generierung server-seitig läuft. Du kannst aber die JSON-Daten lokal aufbewahren und bei Wiederverfügbarkeit das PDF erzeugen.

## Wieviele Reisen kann ich speichern?

Keine harte Obergrenze. Die SQLite-DB wächst pro Reise um wenige KB (verschlüsseltes JSON + Plain-Metadaten). PDFs liegen separat auf Disk – Größe abhängig vom Reise-Umfang (typisch 100-500 KB pro Datei).

## Kann ich Daten exportieren?

Pro Reise: PDF-Downloads (Antrag + Abrechnung) im Dashboard. Für komplette JSON-Exports: Anfrage per E-Mail an den Admin.

## Wird der NRKVO-Berechner getestet?

Ja. `tests/test_abrechnung.py` enthält Berechnungs-Tests gegen die offiziellen NRKVO-Sätze. Wenn du eine Berechnungs-Diskrepanz findest – bitte als Bug-Report einreichen mit dem zugrunde liegenden JSON.

## Wie melde ich Bugs?

Per E-Mail an malte@zilinski.eu oder direkt im Repository (falls Zugriff vorhanden).

## Ist dr-automate Open Source?

Ja, MIT-Lizenz. Das Repository liegt auf der internen GitLab-Instanz. Die NRKVO-Berechnungslogik wurde gegen die offizielle Verordnung verifiziert, ist aber keine offiziell anerkannte Stelle – Verantwortung für die korrekte Abrechnung bleibt bei dir.
