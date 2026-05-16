# Workflow: Antrag → Genehmigung → Abrechnung

dr-automate begleitet drei Stufen einer Dienstreise. Jede ist ein eigener Schritt im Dashboard.

## Stufe 1: Antrag erstellen

Der Antrag-Wizard hat fünf Schritte:

1. **Eingabe** – Ausschreibung als PDF hochladen oder als Text einfügen (plus optionale Hinweise/Sonderwünsche).
2. **Reise** – Verkehrsmittel für Hin- und Rückreise wählen (PKW/Bahn/Bus/Dienstwagen/Mitfahrt), bei PKW § 5 II/III, bei Mitfahrt der Name. Vorbelegt aus dem Profilfeld „Standard-Verkehrsmittel", pro Reise änderbar. Diese Angaben fließen **vor** der Extraktion in die KI, damit sie realistische Reisezeiten schätzen kann.
3. **KI-Extraktion** – DeepSeek (BYOK) oder Copy-Paste-Prompt für ChatGPT/Claude. Die KI liefert nur die Reisedaten; **Antragsteller- und Beförderungsdaten erzeugt sie nicht** – die kommen aus deinem Profil bzw. aus Schritt 2.
4. **Prüfen** – Antragsteller (read-only aus dem Profil) und Beförderung (deine Wahl) werden angezeigt; die KI-Reisedaten und Bemerkungen sind editierbar. Verzicht auf Tagegeld/Übernachtung/Fahrtkosten wird hier gesetzt. Roh-JSON siehst du nicht mehr.
5. **PDF** – Klick auf „Antrag generieren". Bei eingeloggten Usern überschreibt der Server die Antragsteller-/BahnCard-/Großkundenrabatt-Felder autoritativ aus dem Profil (manipulationssicher); Platzhalter wie `[DEIN NAME]` werden abgewiesen. Im Account-Modus wird die Reise gespeichert (Status: `entwurf`).

> **Tipp:** Das Profil (Name, Abteilung, Adresse, BahnCards, Standard-Verkehrsmittel) einmal sauber pflegen — es füllt jeden Antrag automatisch, ohne dass die KI es kennt oder Tokens dafür verbraucht.

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
