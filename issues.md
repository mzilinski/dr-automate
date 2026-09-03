# Bekannte Issues

(Stand 2026-05-14 — alle aufgeführten Punkte sind aktuell **erledigt**.)

## Erledigt

### 1. Antrag: `Mitfahrt_bei` / `Mitfahrt_bei1` werden befüllt ✓

- Schema: `Befoerderungsart.mitfahrer_name: str = ""` ergänzt (`models.py`).
- Mapping: `befoerderung.hinreise.mitfahrer_name` → `Mitfahrt_bei`,
  Rückreise → `Mitfahrt_bei1` (`generator.py` FIELD_MAPPING).
- `system_prompt.md`: Hinweis aufgenommen, dass der Fahrername bei MITFAHRT
  ins dedizierte Feld gehört.
- Regressions-Test: `TestCheckboxBefoerderungHin::test_mitfahrer_name_lands_in_dedicated_pdf_field`.

### 2. Antrag: `Obj53` (Kosten durch andere Stelle) ✓

- Schema: `KonfigurationCheckboxen.kosten_durch_andere_stelle: bool = False`.
- Mapping in `_checkbox_konfiguration`: bei `True` → `Obj53 = /Yes`.
- `system_prompt.md`: Trigger-Bedingung dokumentiert (Tagungsgebühr inkl.
  Übernachtung/Verpflegung).
- Regressions-Tests: `test_kosten_durch_andere_stelle_sets_Obj53` +
  `test_kosten_durch_andere_stelle_false_does_not_set_Obj53`.

### 3. Antrag: Bahn-Sektion immer beantworten (revidiert 2026-09-03) ✓

- **Ursprüngliche Entscheidung (2026-05):** BahnCard-/Großkundenrabatt-
  Checkboxen nur bei BAHN/BUS setzen, bei reinen PKW-/Mitfahrt-/Dienstwagen-/
  Flug-Reisen die Bahn-Sektion leer lassen.
- **Revidiert 2026-09-03:** Der Vordruck 035_001 verlangt die Bahn-Sektion
  („Ich besitze eine BahnCard Business / BahnCard", „Beschaffung aufgegeben",
  „Ermäßigungskarte" — *Bitte immer ausfüllen*) und die Großkundenrabatt-Frage
  (*Bitte immer beantworten!*) **unabhängig vom Verkehrsmittel**. Ein
  PKW-Antrag (Cisco Akademietag 2026) kam deshalb von der Schulleitung als
  „unvollständig" zurück.
- `_checkbox_konfiguration` beantwortet die Sektion jetzt immer aus den
  Profil-Werten (Default „Nein"). Bei „Großkundenrabatt: Nein" ohne
  Bahn-/Busfahrt leitet `grosskundenrabatt_begruendung()` die Pflicht-
  Begründung (`Begruendung3`) aus der Verkehrsmittel-Wahl ab („Keine
  Bahn-/Busfahrt: Hin- und Rückreise mit privatem Pkw."); bei Bahnreise
  bleibt sie Nutzersache.
- Regressions-Tests: `test_pkw_only_reise_answers_bahn_sektion_with_nein`,
  `test_pkw_only_reise_with_profile_bahncard_sets_ja`,
  `TestGrosskundenrabattBegruendung`.

### 4. Pre-existing Fixes (zur Referenz)

- **`/abrechnung/generate` rechnet jetzt serverseitig** — `result.berechnet`
  wird vor `fill_pdf` befüllt (autoritative NRKVO-Berechnung).
- **`EUR7`/Netto-Tagegeld-Zeile** zeigt jetzt explizit `0,00 €`, sobald
  `kuerzung_eur > 0` (vorher leer).
- **AI-Direktextraktion (BYOK)** für DeepSeek im Antrag- und Abrechnungs-
  Wizard. Key bleibt im `localStorage` (Gast-Modus) oder verschlüsselt
  im Server-Profil (Account-Modus). Pro Request weitergereicht, nie geloggt.

## Code-Review-Fixes (Stand 2026-05-14)

- **Rate-Limit pro-Worker statt global** — gunicorn auf `--workers 1 --threads 4`
  gestellt; ProxyFix bei `TRUST_REMOTE_USER_HEADER=true` für echte Client-IP.
- **File-Permissions** — `data/` 0700, SQLite-DB 0600, PDFs 0600 + Dirs 0700,
  einmaliges one-shot-Tightening für bestehende Dateien beim Startup.
- **`_parse_iso_date`** — sauber rewritten, akzeptiert sowohl ISO als auch DD.MM.YYYY.
- **`tagegeld_tage`** — Mitternachts-Bug behoben: 23:00→06:00 zählt nicht mehr
  als 2 Teiltage. Logik: `<8h → 0`, `8–24h → 1 Teil`, `≥24h → voll + 2 Teil`.
- **IBAN-Truncation** — WARN-Log bei >22 Zeichen IBAN (Vordruck hat nur 22 Felder).
- **`begruendung_ueber_100`** — wird nicht mehr stillschweigend verworfen, wenn
  `anzahl_pauschal == 0`. Plausibilitäts-Check auf Gesamt-Kosten als Fallback.

---

Tests: 135 grün (Stand 2026-05-14, alle obigen Fixes inkl. Regressions-Tests).
