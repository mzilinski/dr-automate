# Handoff: Nächste Schritte aus Code-Review

Priorisierte Punkte aus dem Review vom 2026-04-27. Reihenfolge ist die empfohlene Bearbeitungsfolge — CI zuerst, dann Sicherheit, dann Korrektheit, dann Aufräumen.

## 0. CI grün kriegen (BLOCKER)

**Stand:** Alle CI-Runs auf `main` sind seit Januar 2026 rot (zuletzt geprüft 2026-04-27). Effektiv läuft seit Monaten weder Lint noch Test, Docker-Build oder Bandit-Scan — die Pipeline gibt aktuell keinerlei Sicherheit.

### 0a. `ruff.toml` Syntax (✅ erledigt am 2026-04-27)

`ruff.toml` benutzte `pyproject.toml`-Sections (`[tool.ruff]`, `[tool.ruff.lint]`). Aktuelle ruff-Versionen lehnen das ab → TOML-Parse-Error → Lint-Step bricht sofort ab. Behoben: Sections umgeschrieben auf root-keys + `[lint]` + `[lint.isort]`.

### 0b. Pre-existing Lint-Findings aufräumen

Mit reparierter Config kommen 92 Lint-Findings ans Licht (waren bisher unsichtbar). Alle in vorhandenen Dateien — nichts Neues durch das Review verursacht.

```
ruff check . --output-format=concise
# 92 errors, 67 auto-fixbar
ruff format --check .
# 4 Dateien würden umformatiert: app.py, generator.py, models.py, tests/test_app.py
```

Findings nach Kategorie:
- `W293` (~50×): Whitespace auf Blank-Lines — auto-fixbar
- `UP045` (~7×): `Optional[X]` → `X | None` — auto-fixbar
- `F401` (2×): Unused Imports `unittest.mock.MagicMock`, `io.BytesIO` in `tests/test_app.py` — auto-fixbar
- `I001` (2×): Import-Reihenfolge in `tests/test_app.py` — auto-fixbar

**Vorgehen:**
```bash
uvx ruff check . --fix
uvx ruff format .
# danach prüfen, ob Tests noch grün sind
uv run pytest tests/ -v
```

Das `ruff format`-Diff wird groß sein (4 Dateien, viele Whitespace-/Quote-Änderungen). Vor dem Commit reviewen, dass nichts Funktionales geändert wurde.

### 0c. Verifizieren

Nach 0a + 0b lokal vollständig durchspielen, was die CI macht:
```bash
uvx ruff check . --output-format=github  # muss exit 0
uvx ruff format --check .                # muss exit 0
uv run pytest tests/ -v --cov=.          # muss grün
docker build -t dr-automate:local .      # muss bauen
```

Erst dann pushen — sonst entsteht wieder ein roter Run und wir sind zurück am Anfang.

**Aufwand gesamt:** ~15 Min (auto-fix + Diff-Review + lokaler CI-Smoketest).

## 1. Passphrase-Vergleich konstantzeitig + `SECRET_KEY` absichern

**Datei:** `app.py:19, 95, 102`

- `SECRET_KEY` darf in Produktion keinen Default haben. Entweder hart auf `os.environ["SECRET_KEY"]` umstellen (KeyError beim Start) oder explizit prüfen:
  ```python
  if not DEBUG_MODE and not os.environ.get("SECRET_KEY"):
      raise RuntimeError("SECRET_KEY env var must be set in production")
  ```
- Beide Passphrase-Vergleiche (URL-Token in `login()` und Form-POST) auf `secrets.compare_digest` umstellen:
  ```python
  import secrets
  if PASSPHRASE and secrets.compare_digest(
      request.form.get("passphrase", ""), PASSPHRASE
  ):
      ...
  ```
- Zusätzlich: prüfen, ob das URL-Token-Auto-Login wirklich gebraucht wird. Falls ja, mittelfristig durch kurzlebige Einmal-Token ersetzen statt der Dauer-Passphrase in URL/Logs.

**Aufwand:** ~10 Min.

## 2. Session-Cookie-Flags für Produktion

**Datei:** `app.py` (nach `app.config['SECRET_KEY'] = SECRET_KEY`)

```python
app.config.update(
    SESSION_COOKIE_SECURE=not DEBUG_MODE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
```

**Aufwand:** ~2 Min.

## 3. Datums-Validierung verschärfen + Cross-Field-Check

**Datei:** `models.py:45-51`

- Regex durch echtes `datetime.strptime` ersetzen (sonst rutschen z.B. `32.13.2026` durch).
- `model_validator(mode="after")` ergänzen, der prüft:
  - `ende_datum/zeit >= start_datum/zeit`
  - `dienstgeschaeft_ende >= dienstgeschaeft_beginn`
  - `dienstgeschaeft_*` liegt innerhalb von `start`/`ende`

**Aufwand:** ~20 Min. inkl. Tests.

## 4. Validiertes Modell an `fill_pdf` weiterreichen

**Datei:** `app.py:164-174`

Aktuell wird `data` (raw dict) an `generator.fill_pdf` übergeben — Pydantic-Defaults (`"" → "II"` etc.) gehen verloren. Stattdessen:

```python
is_valid, result = validate_reiseantrag(data)
if not is_valid:
    return jsonify({"error": f"Validierungsfehler: {result}"}), 400
output_path = generator.fill_pdf(result.model_dump(), PDF_TEMPLATE_PATH, temp_dir)
```

**Aufwand:** ~5 Min.

## 5. Tests für `apply_checkbox_logic`

**Datei:** `tests/test_app.py` (neue `TestCheckboxLogic`-Klasse)

Wichtigste fehlende Test-Stelle. Tabelle aller Kombinationen:
- Hin/Rück × {BAHN, BUS, PKW-II, PKW-III, FLUG, DIENSTWAGEN}
- Plus die Konfigurations-Booleans (Bahncard, Großkundenrabatt, Trennungsgeld, 2km-Umkreis)
- Plus Verzichtserklärungen

Pro Fall: erwartete Set von `OBJxx` / `BCB_*` / `Obj*` Keys mit `/Yes` prüfen.

**Aufwand:** ~45-60 Min.

## 6. `apply_checkbox_logic` aufteilen

**Datei:** `generator.py:91-158`

Die 70-Zeilen-Funktion in drei Helper splitten:
- `_checkbox_befoerderung(trans) -> dict`
- `_checkbox_konfiguration(config) -> dict`
- `_checkbox_verzicht(verzicht) -> dict`

Erst nach Schritt 5 — die Tests sind das Sicherheitsnetz für den Refactor.

**Aufwand:** ~15 Min.

## 7. Dockerfile auf `pyproject.toml` umstellen

**Datei:** `Dockerfile:14-16`

Aktuell hardcodierte `pip install flask flask-wtf ...`-Liste, driftet von `pyproject.toml`. Stattdessen:

```dockerfile
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
```

Außerdem Port-Inkonsistenz auflösen: `.env.example` (5001) vs. `Dockerfile EXPOSE/CMD` (5000) vs. `app.py` Default (5001) — einen Standard wählen und überall verwenden.

**Aufwand:** ~10 Min.

## 8. `dev`-Dependencies konsolidieren

**Datei:** `pyproject.toml:19-33`

Aktuell zweimal deklariert (`[project.optional-dependencies] dev` UND `[dependency-groups] dev`) mit unterschiedlichen Versionen. Eine Variante wählen — bei `uv` ist `[dependency-groups]` der moderne Pfad. Die andere löschen.

**Aufwand:** ~3 Min.

## 9. Bandit-CI ernstnehmen oder entfernen

**Datei:** `.github/workflows/ci.yml:105`

`bandit ... || true` lässt jeden Befund durchgehen. Entweder:
- `--severity-level medium` setzen und das `|| true` entfernen, oder
- den Job ganz löschen, wenn er nicht durchgesetzt werden soll.

**Aufwand:** ~5 Min.

## 10. `set_need_appearances` privater-API-Hack

**Datei:** `generator.py:160-176`

Der `if "/AcroForm" not in catalog`-Zweig benutzt `writer._objects[len(...)-1]` und ist für Templates mit Formularfeldern unerreichbar. Wenn er je läuft, baut er ein kaputtes AcroForm. Empfehlung:
- Den unsicheren Zweig löschen (Template hat immer AcroForm), oder
- Eine korrekte AcroForm-Erzeugung implementieren falls echt nötig.
- Außerdem `print(...)` durch `logger.warning(...)` ersetzen.

**Aufwand:** ~10 Min.

---

## Nice-to-have (niedrigere Priorität)

- Login Rate-Limit verschärfen: `3/minute` und `30/hour` für `POST /login`.
- Tests für `_strip_citations` / `_strip_citations_raw` mit echten Beispielen aus Gemini/NotebookLM-Output.
- End-to-End-Test: PDF generieren, mit `pypdf` zurücklesen, Felder gegen Erwartung prüfen.
- `_meta`-Feld in `ReiseantragData` umbenennen (Pydantic v2 ignoriert führende Underscores beim Validieren).
- `CLEAR_DIENSTWAGEN`-Mapping in `generator.py:65` umbenennen oder an `befoerderung.hinreise.typ` koppeln — der aktuelle Name suggeriert bedingtes Löschen, der Code löscht aber immer.
- `templates/index.html` (988 Z. inline CSS+JS) in `static/` auslagern für Caching.

---

## Geschätzter Gesamtaufwand

- Schritt 0 (CI grün, Voraussetzung für alles weitere): ~15 Min.
- Schritte 1-4 (Sicherheit + Korrektheit, Block 1): ~40 Min.
- Schritte 5-6 (Tests + Refactor, Block 2): ~75 Min.
- Schritte 7-10 (Aufräumen, Block 3): ~30 Min.

Schritt 0 zuerst — ohne grüne CI fängt jeder folgende Commit den nächsten roten Run. Block 1 danach hat den höchsten Sicherheits-Hebel.
