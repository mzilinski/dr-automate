# Workflow: Antrag → Genehmigung → Abrechnung

dr-automate begleitet drei Stufen einer Dienstreise. Jede ist ein eigener Schritt im Dashboard.

## Stufe 1: Antrag erstellen

Der Antrag-Wizard hat fünf Schritte:

1. **Eingabe** – Ausschreibung als PDF hochladen oder als Text einfügen (plus optionale Hinweise/Sonderwünsche).
2. **Reise** – Verkehrsmittel für Hin- und Rückreise wählen (PKW/Bahn/Bus/Dienstwagen/Mitfahrt/Flug), bei PKW § 5 II/III, bei Mitfahrt der Name; bei § 5 III und Flug ist eine Begründung Pflicht. Vorbelegt aus dem Profilfeld „Standard-Verkehrsmittel", pro Reise änderbar. Diese Angaben fließen zusammen mit dem heutigen Datum und Postleitzahl/Ort deines Wohnorts **vor** der Extraktion in die KI, damit sie Jahreszahlen ergänzen und realistische Reisezeiten schätzen kann.
3. **KI-Extraktion** – DeepSeek (BYOK) oder Copy-Paste-Prompt für ChatGPT/Claude. Die KI liefert nur die Reisedaten; **Antragsteller- und Beförderungsdaten erzeugt sie nicht** – die kommen aus deinem Profil bzw. aus Schritt 2.
4. **Prüfen** – Antragsteller (read-only aus dem Profil) und Beförderung (deine Wahl) werden angezeigt; die KI-Reisedaten und Bemerkungen sind editierbar. Verzicht auf Tagegeld/Übernachtung/Fahrtkosten wird hier gesetzt. Roh-JSON siehst du nicht mehr.
5. **PDF** – Klick auf „Antrag generieren". Bei eingeloggten Usern überschreibt der Server die Antragsteller-/BahnCard-/Großkundenrabatt-Felder autoritativ aus dem Profil (manipulationssicher); Platzhalter wie `[DEIN NAME]` werden abgewiesen. Im Account-Modus wird die Reise gespeichert (Status: `entwurf`). Im Gast-Modus sicherst du hier mit **„JSON exportieren"** die Antragsdaten für die spätere Abrechnung.

> **Tipp:** Das Profil (Name, Abteilung, Adresse, Standard-Verkehrsmittel; BahnCards im Server-Profil des Account-Modus) einmal sauber pflegen — es füllt jeden Antrag automatisch, ohne dass die KI es kennt oder Tokens dafür verbraucht.

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
   - Unentgeltliche Verpflegung (Frühstück / Mittag / Abend) — am genauesten **pro Tag**, dann wird die Kürzung je Kalendertag gedeckelt
   - Übernachtungen pauschal, mit Beleg (Anzahl Nächte + Betrag) oder unentgeltlich
   - Belege für Fahrkarten / Zuschläge / Sonstige
   - Wegstreckenkilometer (nur selbst gefahrener PKW)
   - Abzüge (Zuwendungen, Reisekostenabschlag, Eigenanteile)
4. Die Zusammenfassung in Schritt 9 kommt aus derselben Server-Berechnung, mit der das PDF gefüllt wird: Tagegeld je Kalendertag (§ 7 NRKVO, ab dem 15. Aufenthaltstag vermindert), Kürzungen, Übernachtungsgeld (§ 8) und Wegstreckenentschädigung (§ 5, 125-€-Deckel für § 5 II). Hinweise zur Berechnung stehen dort und in den Erläuterungen des PDFs.
5. **PDF generieren** – wieder mit Speicher-Option. Status: `abgerechnet`. Gespeichert wird die Abrechnung nur, wenn du sie über „Abrechnung" im Dashboard geöffnet hast (dann ist die Reise zugeordnet).

## Ablage in Paperless (nur `admins`)

Im Profil unter **Paperless** einen API-Token aus deinem Paperless (Profil → „API-Auth-Token")
hinterlegen und „Automatisch ablegen" einschalten. Dann landet der **Antrag beim Vermerken der
Genehmigung** und die **Abrechnung beim Vermerken „bezahlt"** als PDF in deinem Paperless —
mit Tag `Dienstreise` und dir als Besitzer. Im Dashboard zeigt ein Knopf je PDF den Stand
(⏳ unterwegs, ✓ abgelegt, ⚠ Fehler) und sendet auf Klick (erneut). Ein Duplikat erkennt
Paperless selbst; das gilt als erledigt.

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
- `bezahlt` – Du hast den Geldeingang per **„✓ bezahlt"** auf dem Dashboard bestätigt (erst nach erzeugter Abrechnung möglich). Finaler Status. Optional: Datum des Eingangs.

## Was wenn keine Genehmigung erfolgt?

- Reise auf `verworfen` setzen, indem du sie löschst (oder via Datenbank, falls Audit-Trail nötig).
- Verworfene Reisen brauchen keinen Abrechnungs-Vorgang.

## Was wenn der Antrag geändert wird?

- Solange `status = entwurf`, im Dashboard „Antrag bearbeiten" wählen und neu erzeugen. Antrag-JSON und PDF werden ersetzt.
- Ab `genehmigt` bleibt der genehmigte Antrag unverändert: Erzeugst du ihn erneut, legt dr-automate automatisch eine **neue Reise** an und weist darauf hin.
