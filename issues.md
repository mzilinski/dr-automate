# Bekannte Issues

Offene Punkte im dr-automate-Code, aufgekommen aus Reviews realer Anträge/Abrechnungen
und aus dem Vergleich mit dem MMBBS-Skill (Stand 04/2025-Vordruck).

## 1. Antrag: `Mitfahrt_bei` / `Mitfahrt_bei1` werden nicht befüllt

**Symptom:** Bei `befoerderung.hinreise.typ == "MITFAHRT"` oder `rueckreise.typ == "MITFAHRT"`
setzt `generator.py` nur die Checkbox `OBJ44` (Hin) bzw. `OBJ50` (Rück), schreibt den
Fahrernamen aber nicht in das vorgesehene Textfeld. Laut System-Prompt landet der Name
aktuell im `zusatz_infos.bemerkungen_feld` — also außerhalb der dafür vorgesehenen
Formularfelder.

**Fix-Skizze:**
- Schema-Erweiterung in `models.py`:
  - `befoerderung.hinreise.mitfahrer_name: str = ""`
  - `befoerderung.rueckreise.mitfahrer_name: str = ""`
- Mapping in `generator.py` `FIELD_MAPPING`:
  - `"befoerderung.hinreise.mitfahrer_name": "Mitfahrt_bei"`
  - `"befoerderung.rueckreise.mitfahrer_name": "Mitfahrt_bei1"`
- `system_prompt.md`: Anweisung ergänzen, dass der Fahrername bei MITFAHRT in das
  neue Schemafeld gehört, nicht ins Bemerkungen-Feld.
- Tests in `tests/test_app.py`: Roundtrip für MITFAHRT mit `mitfahrer_name`.

**Aufwand:** ~10 Zeilen Code + 1 Test.

**Referenz:** MMBBS-Skill `dienstreise-antrag-mmbbs.skill`, Feldraster.

---

## 2. Antrag: `Obj53` (Kosten durch andere Stelle übernommen) fehlt im Schema

**Symptom:** Wenn die Tagungsgebühr Übernachtung und/oder Verpflegung enthält, sollte
die Checkbox „Reisekosten werden ganz/teilweise von anderer Stelle übernommen" (`Obj53`)
gesetzt werden. Aktuell kennt dr-automate das Konzept überhaupt nicht — der entsprechende
Code-Pfad in `generator.py` referenziert `Obj53` nirgendwo.

**Auswirkung:** Bei Reisen mit Tagungsgebühr-Inklusivleistungen muss der Antragsteller
manuell nachtragen oder die Sachbearbeitung fragt zurück.

**Fix-Skizze:**
- Schema-Erweiterung in `models.py`:
  - `konfiguration_checkboxen.kosten_durch_andere_stelle: bool = False`
  - Optional: `kosten_durch_andere_stelle_erlaeuterung: str = ""` (für Bemerkungen)
- `generator.py` `_checkbox_konfiguration`:
  - `if config.get("kosten_durch_andere_stelle"): cb["Obj53"] = "/Yes"`
- `system_prompt.md`: Trigger-Bedingung („Veranstalter übernimmt Reisekosten",
  „Tagungsgebühr inkl. Übernachtung/Verpflegung", …).
- Tests analog zu den anderen Checkbox-Tests.

**Aufwand:** ~15 Zeilen + 2 Tests.

**Referenz:** MMBBS-Skill, Standardbelegung „Obj53 bei Tagungsgebühr inkl. Übernachtung/Verpflegung".

---

## 3. Antrag: BahnCard-Checkboxen werden unbedingt gesetzt

**Symptom:** `generator.py:132-137` setzt `BCB_Nein`, `BC_Nein`, `Beschaffung_Nein`
immer, wenn die jeweiligen Booleans `False` sind — auch bei reinen PKW- oder Mitfahrt-
Reisen, bei denen die Bahn-Sektion des Formulars eigentlich gar nicht ausgefüllt
werden sollte.

**Auswirkung:** Visuell wird das BahnCard-Block im PDF mit „Nein"-Kreuzchen markiert,
obwohl die Person gar keine Bahn benutzt. Nicht kritisch, aber inkonsistent — der
MMBBS-Skill setzt die Felder explizit **nur bei Bahn/Bus**.

**Fix-Skizze:**
- In `generator.py` `_checkbox_konfiguration` Bahn-Felder nur setzen, wenn ein
  Beförderungsmittel im Antrag tatsächlich `BAHN` oder `BUS` ist:
  ```python
  hat_bahn = (
      data["befoerderung"]["hinreise"]["typ"] in ("BAHN", "BUS")
      or data["befoerderung"]["rueckreise"]["typ"] in ("BAHN", "BUS")
  )
  if hat_bahn:
      if not config["bahncard_business_vorhanden"]:
          cb["BCB_Nein"] = "/Yes"
      ...
  ```
  Signatur muss `befoerderung` zusätzlich übergeben bekommen, oder die Logik wandert
  in die zentrale `apply_checkbox_logic`.
- Auch `Obj7` (Großkundenrabatt: Nein) und `Begruendung3` nur bei Bahn — der MMBBS-
  Skill setzt `Obj7` zwar grundsätzlich, aber das ist Detail.
- Tests: Roundtrip PKW-only → kein `BCB_Nein` im PDF.

**Aufwand:** ~10 Zeilen + 1 Test.

**Referenz:** MMBBS-Skill „Checkboxen — Sonstiges (Standardbelegung)", Kommentar
„nur bei Bahn".

---

## 4. Erledigt (zur Referenz)

Folgende Issues aus dem ersten Review wurden in dieser Session bereits gefixt:

- **`/abrechnung/generate` rechnete nicht selbst:** `result.berechnet` wird jetzt
  serverseitig aus `berechnung()` befüllt, bevor `fill_pdf` läuft. Das im README
  versprochene „serverseitig autoritativ" stimmt damit wieder.
  Regressionstest: `test_abrechnung_generate_rechnet_kuerzung_serverseitig`.

- **`EUR7`/Netto-Tagegeld-Zeile blieb leer bei Netto = 0 €:** `_fmt_eur(0)` lieferte
  `""`, sodass eine voll gekürzte Tagegeld-Zeile visuell aussah wie „nicht gerechnet".
  Logik in `generator_abrechnung.py` zeigt jetzt explizit `0,00 €`, sobald
  `kuerzung_eur > 0`.

- **AI-Direktextraktion (BYOK) per DeepSeek:** Antrag und Abrechnungs-Wizard
  können Freitext direkt im Tool extrahieren lassen. Key bleibt im `localStorage`,
  wird pro Request einmal durchgereicht, weder geloggt noch persistiert. Fallback
  auf den Copy-Paste-Workflow, wenn kein Key gesetzt ist.
