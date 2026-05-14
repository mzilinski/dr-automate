# Haftungs- und Nutzungshinweise

Stand: 2026-05-14

## Zweck der Anwendung

dr-automate ist ein **Hilfswerkzeug** für die Erstellung von Dienstreise-Anträgen
und Reisekostenabrechnungen nach der Niedersächsischen Reisekostenverordnung
(NRKVO). Es ist kein offizielles Werkzeug der Niedersächsischen Landesverwaltung,
sondern ein privat betriebener Service.

## NRKVO-Berechnungen — keine verbindliche Auskunft

Die in der App durchgeführten Berechnungen (Tagegeld, Kürzungen,
Wegstreckenentschädigung, Übernachtungsgeld) folgen den NRKVO-Sätzen nach
bestem Wissen und Stand der jeweils aktuellen Fassung. **Verbindlich ist
ausschließlich die Auskunft der zuständigen Reisekostenstelle**.

- Fehler in der Berechnung können nicht ausgeschlossen werden.
- NRKVO-Novellen können dazu führen, dass hinterlegte Sätze veraltet sind —
  der NRKVO-Stand wird im Footer jeder Wizard-Seite angezeigt.
- Bei Diskrepanz zwischen App-Ergebnis und Auszahlung gilt die Auszahlung.

Wer die App geschäftlich nutzt, trägt die Verantwortung, das erzeugte PDF
**vor der Einreichung zu prüfen**. Bug-Reports sind willkommen
(`malte@zilinski.eu`), aber begründen keinen Schadenersatz-Anspruch.

## Verfügbarkeit / SLA

Es besteht **keine Verfügbarkeits-Garantie**. Der Service kann jederzeit
vorübergehend oder dauerhaft eingestellt werden — sei es wegen Wartung,
Infrastruktur-Problemen oder weil der Betreiber den Betrieb beendet.

Account-Nutzer werden im Fall einer Einstellung mindestens **30 Tage vorher
per E-Mail informiert** und erhalten die Möglichkeit, ihre Daten
(JSON + PDFs) zu exportieren.

## PDF-Formulare (amtliche Vordrucke)

Die in der App verwendeten Vordrucke

- **DR-Antrag 035-001** (Stand 04/2025)
- **Reisekostenvordruck 035-002**

sind amtliche Vordrucke des Landes Niedersachsen und Eigentum des
zuständigen Ressorts (NLBV/MF). Die Verwendung erfolgt zum vorgesehenen
Zweck — der Befüllung im Rahmen einer eigenen Dienstreise-Abwicklung —
ohne dass damit Rechte des Landes berührt werden. Die App fügt den
Vordrucken Daten hinzu, verändert sie aber nicht inhaltlich.

## Externe KI-Extraktion (DeepSeek, optional)

Wer die KI-Extraktions-Funktion mit eigenem DeepSeek-API-Key nutzt, sendet
den eingegebenen Freitext (Ausschreibung etc.) an einen Drittanbieter
außerhalb der EU. Verantwortlich für diese Übermittlung ist der Nutzer
selbst — der API-Key kommt aus seinem eigenen DeepSeek-Konto. dr-automate
ist insoweit nur **Übermittlungs-Werkzeug** (Header-Durchreichung), kein
Verantwortlicher i.S.v. Art. 4 Nr. 7 DSGVO für diese spezielle
Verarbeitung.

Wer das nicht möchte: einfach keinen Key hinterlegen — die App
funktioniert auch ohne (Prompt manuell in ChatGPT/Claude/… kopieren).

## Routing-Dienst (OpenStreetMap)

Die optionale „Entfernung schätzen"-Funktion sendet die im Routing-Dialog
**aktiv vom Nutzer eingegebenen** Adressen an OpenStreetMap-Server (Nominatim)
und einen OSRM-Demo-Endpunkt (HeiGIT, Heidelberg). Die Schätzung dient als
Orientierung; **maßgeblich für die Abrechnung ist die tatsächlich gefahrene
Strecke**.

## Verlinkung externer Inhalte

Sofern in dieser App auf externe Seiten verlinkt wird (DeepSeek, OSM,
Aufsichtsbehörden), erfolgt dies zur Information. Für deren Inhalte ist
der jeweilige Anbieter verantwortlich. dr-automate macht sich diese
Inhalte nicht zu eigen.

## Schlussbestimmungen

Es gilt deutsches Recht. Gerichtsstand für eventuelle Streitigkeiten,
soweit gesetzlich zulässig: Lingen (Ems).

Sollten einzelne Bestimmungen unwirksam sein, bleiben die übrigen
Bestimmungen unberührt.
