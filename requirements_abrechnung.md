# Requirements: DR-Abrechnung (Erweiterung)

Stand: 2026-04-28. Basis: NRKVO-Modernisierung (Stand 1.1.2025), Formular `forms/Reisekostenvordruck.pdf` (035_002).

## 1. Ausgangslage

Die App generiert aktuell den **Antrag** (Formular `035_001`) aus LLM-JSON. Daten leben nur im Browser-`localStorage` (Profil) plus pro Lauf eingegebenes JSON — kein Server-State.

**Erweiterung:** Auch die **Abrechnung** (Formular `035_002`) soll automatisiert werden, mit Vorbefüllung aus dem zuvor erstellten Antrag.

## 2. Leitprinzipien

- **Kein LLM für die Abrechnung.** Daten sind zahlen-/feldbasiert, nicht extraktionsbasiert. Wizard ist der einzige Eingabepfad.
- **Kein Server-State.** Stammdaten in `localStorage`, Reise-State ausschließlich als JSON-Datei (Export/Import). PDF-Generierung ist die einzige Server-Berührung.
- **Belege bleiben Papier.** App erfasst nur Beträge und Pflicht-Begründungen, keine Beleg-Listen oder Uploads.
- **Inland v1.** Auslandsdienstreise (§§ 15–18 NRKVO) ist out-of-scope.
- **NRKVO-Sätze konfigurierbar.** Single Source of Truth in `nrkvo_rates.py`, nicht hardcoded.

## 3. Feld-Mapping: Antrag → Abrechnung

| Abrechnungsfeld | Quelle | Status |
|---|---|---|
| Beschäftigungsstelle, Dienstort | `antragsteller.abteilung` | Übernehmbar |
| Name, Vorname | `antragsteller.name` | Übernehmbar |
| Wohnungsanschrift, Telefon | `antragsteller.adresse_privat`, `antragsteller.telefon` | Übernehmbar |
| E-Mail | Profil | NEU |
| IBAN, BIC | Profil | NEU |
| Abrechnende Dienststelle | Profil | NEU |
| Grund der RKR (DR/VR/AFR/RPR/RRS/GNE) | Profil-Default + Wizard-Auswahl | NEU |
| Datum/Daten der Reise(n) | `reise_details.start_datum/ende_datum` | Übernehmbar |
| Reiseziel/Reiseweg | `reise_details.zielort/reiseweg` | Übernehmbar |
| Beförderungsmittel + § 5 II/III | `befoerderung.*` | Übernehmbar |
| Sonderfall-Begründung | `befoerderung.sonderfall_begruendung_textfeld` | Übernehmbar |
| BahnCard, Großkundenrabatt, Ermäßigungskarte | `konfiguration_checkboxen.*` | Übernehmbar |
| 2-km-Umkreis, Trennungsgeld | `konfiguration_checkboxen.*` | Übernehmbar |
| Beginn/Ende Reise + Dienstgeschäft | `reise_details.*_datum/zeit` | Übernehmbar |
| Bei RRS: Az. der Sachakten | Wizard | NEU (nur bei RKR=RRS) |
| 035_001 / 035_003 beigefügt? | Wizard | NEU |
| Auf Anordnung/Genehmigung durch Dienststelle/Datum | Wizard | NEU |
| Unentgeltliche Verpflegung (Frühstück/Mittag/Abend, Counts) | Wizard | NEU |
| Unentgeltliche Unterkunft (Nächte) | Wizard | NEU |
| DR mit Urlaub > 5 Tage verbunden | Wizard | NEU |
| Tagegeld (Tage, EUR, Kürzung) | berechnet | NEU |
| Übernachtungsgeld pauschal | berechnet | NEU |
| Erstattung Übernachtungskosten | Wizard (mit Begründung > 100 €/Nacht) | NEU |
| Wegstreckenentschädigung (km, Satz, Summe) | km Wizard, Satz aus § 5 II/III | NEU |
| Fahrkarte / Zuschläge / Wagenklasse | Wizard (nur bei BAHN/BUS) | NEU |
| Sonstige Fahrtkosten | Wizard | NEU |
| Erstattung sonstiger Kosten + Erläuterung | Wizard | NEU |
| Zuwendungen Dritter | Wizard | NEU |
| Reisekostenabschlag erhalten | Wizard | NEU |
| Eigenanteile + Erläuterung | Wizard | NEU |
| Datum Unterschrift | Auto (heute) | — |

## 4. NRKVO-Kalkulationen (Stand 1.1.2025)

| Posten | Satz | Norm |
|---|---|---|
| Wegstrecke § 5 II (kleine) | 0,25 €/km, max 125 € pro Reise | § 5 NRKVO |
| Wegstrecke § 5 III (große, triftiger Grund) | 0,38 €/km | § 5 NRKVO |
| Wegstrecke Fahrrad | 0,10 €/km | § 5 NRKVO |
| Tagegeld > 8 h / An- bzw. Abreisetag | 14 € | § 6 NRKVO i. V. m. § 9 Abs. 4a EStG |
| Tagegeld 24-h-Tag | 28 € | dito |
| Übernachtungsgeld pauschal | 20 €/Nacht, max 14 Nächte | § 8 NRKVO |
| Übernachtungskosten mit Beleg | bis 100 €/Nacht (sonst Begründung) | § 8 NRKVO |
| Kürzung Frühstück | 20 % vom vollen Tagegeld (5,60 €) | § 6 NRKVO |
| Kürzung Mittag-/Abendessen | je 40 % (11,20 €) | § 6 NRKVO |
| Reduktion ab Tag 15 am selben Ort | -50 % Tagegeld | § 6 NRKVO |

**Regeln:**
- Tag = 24 h ab Reisebeginn, nicht Kalendertag.
- Bei < 2 km Umkreis (`konfiguration_checkboxen.dienstgeschaeft_2km_umkreis` = `true`): kein Tagegeld.
- Bei `verzicht_*` aus Antrag: Posten nicht ausgewiesen.
- Sätze in `nrkvo_rates.py` zentral, mit Stand-Datum versioniert.

## 5. Funktionale Anforderungen

### F1 — Pre-Fill aus Antrag

Antrags-JSON (Datei oder Paste) wird in das erweiterte Abrechnungs-Schema überführt. Übernehmbare Felder werden gesetzt, neue Felder bleiben leer/Default.

### F2 — Wizard (einziger Eingabepfad)

Mehrstufiger Web-Wizard auf eigener Route `/abrechnung`. Schritte direkt anspringbar (Stepper, nicht zwingend linear):

1. **Antrag laden** — JSON hochladen *oder* leerer Start.
2. **Stammdaten-Check** — wenn Profil-Pflichtfelder für Abrechnung fehlen (IBAN/BIC/E-Mail/abrechnende Dienststelle), Pflichtabfrage über erweiterten Profil-Wizard.
3. **Reise-Bestätigung** — Daten aus Antrag prüfen/korrigieren (tatsächliche Zeiten weichen oft vom Antrag ab).
4. **Verpflegung & Unterkunft** — pro Tag: Frühstück/Mittag/Abend unentgeltlich? Anzahl unentgeltlicher Nächte. Treibt Kürzung + Übernachtungsposten.
5. **Belege & Beträge** — Übernachtungskosten, Fahrkarte/Zuschläge/Wagenklasse (nur BAHN/BUS), sonstige Fahrtkosten, sonstige Kosten. Live-Validation: > 100 €/Nacht → Begründungspflicht-Hinweis.
6. **Wegstrecke** — km bei PKW/Fahrrad. App rechnet Satz × km, zeigt Cap-Hinweis (125 € bei § 5 II).
7. **Abzüge** — Zuwendungen Dritter, Reisekostenabschlag, Eigenanteile.
8. **Sonstiges** — RRS-Az., 035_001 / 035_003 beigefügt, Urlaub > 5 d.
9. **Zusammenfassung** — Live-Summe (Tagegeld − Kürzungen + Übernachtung + Fahrt + Sonstiges − Abzüge = auszuzahlen). PDF-Generieren-Button.

### F3 — Live-Berechnung

Tagegeld, Kürzung, Übernachtungsgeld pauschal, Wegstreckenentschädigung, Zwischensumme und Auszahlbetrag werden **clientseitig** in JS bei jeder Eingabe aktualisiert. Berechnungslogik existiert zusätzlich serverseitig (autoritativ beim PDF-Befüllen) — Konsistenzcheck.

### F4 — PDF-Generierung

Neuer `generator_abrechnung.py` analog zu `generator.py`, mit Field-Mapping für `forms/Reisekostenvordruck.pdf` (Field-IDs einmalig per `pypdf` auslesen und dokumentieren).

Dateiname: `YYYYMMDD_DR-Abrechnung_<Stadt>_<Thema>.pdf` (Schema vom Antrag übernommen).

Endpoint: `POST /abrechnung/generate`, CSRF + Rate-Limit analog `/generate`.

### F5 — Export / Import

- **Export:** Kompletter Abrechnungs-State als JSON-Download. Dateiname: `YYYYMMDD_DR-Abrechnung_<Stadt>_<Thema>.json` — matcht den PDF-Namen, sodass JSON und PDF im Filesystem zusammenliegen.
- **Auto-Export-Empfehlung** bei PDF-Generierung: Banner „JSON sichern, falls Korrektur nötig" + 1-Klick-Download. Begründung: Re-Generierung nach Korrektur ohne Wizard-Neudurchlauf.
- **Import:** JSON hochladen → State wiederherstellen, beliebigen Wizard-Schritt anspringen.
- **Antrags-Import:** Antrags-JSON importieren startet die Abrechnung mit Pre-Fill (siehe F1).
- **localStorage** speichert nur Stammdaten (Profil). Reisespezifischer State liegt **nicht** in localStorage — die JSON-Datei ist die alleinige Wahrheit.

### F6 — Datenschutz

- IBAN/BIC verlassen den Browser nur als Teil der heruntergeladenen JSON oder im erzeugten PDF.
- Server bekommt JSON nur kurz zur PDF-Befüllung, keine Persistierung (analog Antrag).
- Hinweis im Profil-Dialog: „Diese Daten werden nur lokal in deinem Browser gespeichert."

### F7 — Profil-Wizard erweitert

`templates/index.html` Wizard `wizardOverlay` (ab Zeile 559) bekommt einen zweiten, **einklappbaren Block „Daten für die Abrechnung (optional)"** mit:
- IBAN
- BIC
- Dienstliche E-Mail
- Abrechnende Dienststelle
- RKR-Default-Code (DR/VR/AFR/RPR/RRS/GNE/SONSTIGE)

Default eingeklappt — Antrags-only-User sehen davon nichts. Auf `/abrechnung` mit fehlenden Pflichtfeldern: Banner „Profil ergänzen" mit Direktsprung in diesen Block.

## 6. Daten-Modell (Skizze)

Neues Pydantic-Modell `AbrechnungData` per Composition (nicht Inheritance — Antrags-Modell bleibt unverändert):

```
AbrechnungData
├── stammdaten (NEU): iban, bic, email, abrechnende_dienststelle
├── antragsteller, reise_details, befoerderung,
│   konfiguration_checkboxen, verzicht_erklaerung
│   (1:1 vom Antrag, optional vorbefüllt)
├── rkr: Literal["DR","VR","AFR","RPR","RRS","GNE","SONSTIGE"]
├── rrs_aktenzeichen: str | None
├── anlagen_beigefuegt: {genehmigung_035_001: bool, anlagen_035_003: bool}
├── anordnung: {dienststelle: str, datum: str}
├── verpflegung: {fruehstueck_anzahl, mittag_anzahl, abend_anzahl: int}
├── uebernachtungen: {anzahl_pauschal, anzahl_unentgeltlich: int,
│                    kosten_eur: float | None,
│                    begruendung_ueber_100: str | None}
├── beleg_betraege: {fahrkarte_eur, zuschlaege_eur, wagenklasse,
│                   sonstige_fahrt_eur, sonstige_kosten_eur,
│                   sonstige_kosten_erlaeuterung}
├── wegstrecke: {km_hinreise, km_rueckreise: int}
│   (Satz wird aus befoerderung.*.paragraph_5_nrkvo abgeleitet)
├── abzuege: {zuwendungen_eur, reisekostenabschlag_eur,
│            eigenanteile_eur, eigenanteile_erlaeuterung}
├── flags: {urlaub_ueber_5_tage: bool}
└── berechnet (read-only, autoritativ vom Server):
    {tagegeld, kuerzung, uebernachtungsgeld_pauschal,
     wegstreckenentschaedigung, zwischensumme, auszahlbetrag}
```

## 7. Out-of-Scope (v1)

- Auslandsdienstreise (§§ 15–18 NRKVO).
- Belegupload (PDFs/Bilder) — Belege bleiben Papier zur abrechnenden Stelle.
- Mehrtägige Reisen mit verschiedenen Geschäftsorten — v1: ein Geschäftsort.
- Reduktion ab Tag 15 — als Hinweis möglich, ohne Auto-Rechnung.
- LLM-Helper für Verpflegungs-Counts.
- Bestehender LLM-Antragsworkflow bleibt unangetastet.

## 8. Implementierungs-Phasen

1. **PDF-Felder mappen.** `Reisekostenvordruck.pdf` mit `pypdf` auslesen, Field-IDs → JSON-Pfade dokumentieren. Parallel: `nrkvo_rates.py` als Single Source of Truth.
2. **Pydantic-Modell + Server-Endpoint** `/abrechnung/generate` (autoritative Berechnung, PDF-Befüllung, CSRF, Rate-Limit).
3. **Wizard-UI** auf `/abrechnung` (Stepper, Live-Rechnung in JS, Import/Export-Buttons).
4. **Profil-Erweiterung** im bestehenden `wizardOverlay` (einklappbarer Abrechnungs-Block).
5. **Antrags-Import** (JSON → Pre-Fill).
6. **Tests:** Pydantic-Validierung, Berechnungslogik (Tabellen-driven), PDF-Roundtrip.
7. **Doku:** README-Abschnitt, Disclaimer „keine Rechtsberatung", NRKVO-Stand-Datum sichtbar im Footer.
