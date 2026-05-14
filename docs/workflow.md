# Workflow: Antrag → Genehmigung → Abrechnung

dr-automate begleitet drei Stufen einer Dienstreise. Jede ist ein eigener Schritt im Dashboard.

## Stufe 1: Antrag erstellen

1. **Daten erfassen** – im Wizard alle Felder ausfüllen.
2. Wer ist Antragsteller? Wo ist das Reiseziel? Wann startet die Reise? Welche Beförderungsmittel werden genutzt?
3. **JSON validieren** – die App prüft strikt nach Pydantic-Schema. Fehler werden inline angezeigt.
4. **PDF generieren** – Klick auf „PDF erstellen". Im Account-Modus wird die Reise zusätzlich gespeichert (Status: `entwurf`).

> **Tipp:** Wer eine offizielle Ausschreibung als Text vorliegen hat, kann diesen ins KI-Feld werfen. Mit eigenem DeepSeek-Key (BYOK) erzeugt die App den JSON automatisch.

## Stufe 2: Genehmigung vermerken

Sobald deine Personalstelle / dein Vorgesetzter die Dienstreise schriftlich oder digital genehmigt hat:

1. Aufs **Dashboard** gehen.
2. Bei der Reise auf **„Genehmigung vermerken"** klicken.
3. Eintragen:
   - **Datum** der Genehmigung (Pflicht) – das Datum, an dem die Bewilligung erteilt wurde, **nicht** das Datum der Antragstellung.
   - **Aktenzeichen** (optional) – falls deine Stelle eines vergibt. Wird auf die Abrechnung übernommen.
4. Speichern. Der Status springt auf `genehmigt`.

Wenn du sofort weitermachen willst, ist „Speichern &amp; zur Abrechnung" die schnellere Wahl.

## Stufe 3: Abrechnung erstellen

Nach der Reise:

1. Im Dashboard auf **„Abrechnung"** der jeweiligen Reise.
2. Der Wizard ist mit den Antragsdaten vorbefüllt – Stammdaten, Reisezeitraum, Beförderung.
3. Eintragen, was tatsächlich war:
   - Unentgeltliche Verpflegung (Frühstück / Mittag / Abend)
   - Übernachtungen pauschal vs. mit Beleg
   - Belege für Fahrkarten / Zuschläge / Sonstige
   - Wegstreckenkilometer (bei PKW/Mitfahrt)
   - Abzüge (Zuwendungen, Reisekostenabschlag, Eigenanteile)
4. Server-autoritative NRKVO-Berechnung läuft automatisch. Tagegeld, Kürzungen, Übernachtungsgeld und Wegstrecken-Erstattung werden gemäß aktueller NRKVO-Sätze ermittelt.
5. **PDF generieren** – wieder mit Speicher-Option. Status: `abgerechnet`.

## Lifecycle-Zusammenfassung

```
entwurf  →  eingereicht  →  genehmigt  →  abgerechnet  →  bezahlt
   ↓
verworfen (manuell)
```

- `entwurf` – Antrag liegt vor, aber noch nicht eingereicht oder genehmigt.
- `eingereicht` – Du hast den Antrag bei der Personalstelle abgegeben. (Aktuell wird dieser Status automatisch übersprungen – setzt sich mit Vermerken der Genehmigung direkt auf `genehmigt`.)
- `genehmigt` – Genehmigungs-Datum eingetragen.
- `abgerechnet` – Abrechnungs-PDF erstellt und (außerhalb der App) bei der Reisekostenstelle eingereicht.
- `bezahlt` – Du hast den Geldeingang per **„✓ bezahlt"** auf dem Dashboard bestätigt. Finaler Status. Optional: Datum des Eingangs.

## Was wenn keine Genehmigung erfolgt?

- Reise auf `verworfen` setzen, indem du sie löschst (oder via Datenbank, falls Audit-Trail nötig).
- Verworfene Reisen brauchen keinen Abrechnungs-Vorgang.

## Was wenn der Antrag geändert wird?

- Solange `status = entwurf`, einfach den Wizard erneut starten und „Reise aktualisieren". Antrag-JSON und PDF werden ersetzt.
- Nach `genehmigt` sollte der Antrag nicht mehr inhaltlich verändert werden – sonst entspricht das gespeicherte JSON nicht mehr der genehmigten Reise. Stattdessen: neue Reise anlegen.
