# Handoff: Nächste Schritte aus Code-Review

Priorisierte Punkte aus dem Review vom 2026-04-27. Reihenfolge ist die empfohlene Bearbeitungsfolge — CI zuerst, dann Sicherheit, dann Korrektheit, dann Aufräumen.

## 0. CI grün kriegen (BLOCKER)

**Stand:** Alle CI-Runs auf `main` sind seit Januar 2026 rot (zuletzt geprüft 2026-04-27). Effektiv läuft seit Monaten weder Lint noch Test, Docker-Build oder Bandit-Scan — die Pipeline gibt aktuell keinerlei Sicherheit.

### 0a. `ruff.toml` Syntax (✅ erledigt am 2026-04-27)

`ruff.toml` benutzte `pyproject.toml`-Sections (`[tool.ruff]`, `[tool.ruff.lint]`). Aktuelle ruff-Versionen lehnen das ab → TOML-Parse-Error → Lint-Step bricht sofort ab. Behoben: Sections umgeschrieben auf root-keys + `[lint]` + `[lint.isort]`.

### 0b. Pre-existing Lint-Findings aufräumen (✅ erledigt am 2026-04-27)

`uvx ruff check . --fix` + `uvx ruff format .` + manueller Fix für ein verbliebenes `C408` (`dict()` → `{}`-Literal in `app.py:_legal_urls`). Cleanup berührt nur Style: Imports sortiert, `Optional[X]` → `X | None`, Trailing-Whitespace, Quote-Style, Einzeiler `if x: y` aufgesplittet. Geänderte Dateien: `app.py`, `generator.py`, `models.py`, `tests/test_app.py` (~380 Zeilen Diff, rein kosmetisch). Alle 20 Tests bleiben grün.

### 0c. Verifizieren (✅ erledigt am 2026-04-27)

Lokal durchgespielt: `ruff check` und `ruff format --check` exit 0, `pytest` 20/20 passed. Docker-Build nicht lokal getestet — passiert beim CI-Run.

## 1–4. Block 1 (Sicherheit + Korrektheit) — ✅ erledigt am 2026-04-27

- `SECRET_KEY`: kein unsicherer Default mehr. Ohne `SECRET_KEY`-Env-Var crasht die App mit klarer Fehlermeldung; im Debug-Modus wird ein ephemerer Key generiert. Test-Setup über `tests/conftest.py`. Docker-CI versorgt den Smoke-Test mit `openssl rand -hex 32`.
- `secrets.compare_digest`: beide Passphrase-Vergleiche (Form-POST und URL-Token) laufen jetzt konstantzeitig über `_check_passphrase()`. Die Funktion ist robust gegen leere `PASSPHRASE` (kein "" == "" → True-Bypass).
- Login-Rate-Limit verschärft: `5/minute` und `30/hour` (vorher: `10/minute`).
- Session-Cookie-Flags: `HTTPONLY=True`, `SAMESITE=Lax`, `SECURE=not DEBUG_MODE`.
- Datums-/Zeit-Validierung: `datetime.strptime` statt Regex (`32.13.2026` und `25:00` werden jetzt abgelehnt). `model_validator(mode="after")` prüft Reise- und Dienstgeschäfts-Zeiträume auf Plausibilität (Ende ≥ Beginn).
- `generator.fill_pdf` bekommt jetzt `result.model_dump()` statt des Raw-Dicts → Pydantic-Defaults greifen wirklich.
- 6 neue Tests (Datum-Plausibilität, Cross-Field, Auth-Helper) — Suite jetzt 28/28.

## 5–6. Block 2 (Tests + Refactor) — ✅ erledigt am 2026-04-27

- **Tests**: neue Klassen `TestCheckboxBefoerderungHin`, `TestCheckboxBefoerderungRueck`, `TestCheckboxKonfiguration`, `TestCheckboxVerzicht` in `tests/test_app.py`. Decken alle 6 Beförderungs-Typen × Hin/Rück × §-Variante ab (parametrisiert), alle 9 Konfigurations-Booleans und alle 3 Verzicht-Felder. Plus Edge-Cases: `paragraph_5_nrkvo` fehlt → `II`-Default, `verzicht_erklaerung` fehlt → kein Crash. **+32 Tests, Suite jetzt 60/60.**
- **Refactor**: `apply_checkbox_logic` (70 Z., drei Belange in einer Funktion) zerlegt in drei reine Helper:
  - `_checkbox_befoerderung(trans)` — Hin/Rück-Mapping
  - `_checkbox_konfiguration(config)` — Bahncard/Rabatt/2km/Trennungsgeld/Anmerkungen
  - `_checkbox_verzicht(verzicht)` — Tagegeld/Übernachtung/Fahrtkosten
  Public Entry Point bleibt `apply_checkbox_logic(data_json)`, ist jetzt ein 5-Zeiler über die Helper. Ja/Nein-Pärchen sauber als Ternary statt `if/else`.

## 7–10. Block 3 (Aufräumen) — ✅ erledigt am 2026-04-27

- **Dockerfile**: hardcodierte `pip install flask ...`-Liste durch `pip install .` aus `pyproject.toml` ersetzt. `CMD` läuft jetzt im Shell-Form, sodass `${PORT}` echt expandiert wird (Override via `docker run -e PORT=...` funktioniert). Healthcheck honoriert die Env-Var ebenfalls.
- **`pyproject.toml`**: `[project.optional-dependencies] dev` gestrichen, einziger Dev-Pfad ist jetzt `[dependency-groups] dev`. CI installiert via `pip install --group dev` (PEP 735, pip ≥ 25.1).
- **CI Bandit**: `|| true` entfernt; Scan läuft jetzt mit `--severity-level medium`, also rot bei Medium/High. Excludes auf `./tests,./.venv,./.pytest_cache,./htmlcov` erweitert (vorher hat Bandit lokal mit `.venv` durch alle Dependencies gescannt). Einziges echtes Finding (`B104` für `HOST=0.0.0.0`) ist mit `# nosec` und Begründung markiert.
- **Codecov-Action**: v4 → v5 (Node 24 ready, Param `file` → `files` umbenannt).
- **`set_need_appearances`**: gefährlicher Branch entfernt, der bei fehlendem `/AcroForm` ein kaputtes Form-Object aus `writer._objects[-1]` zusammengebaut hätte. Jetzt: AcroForm fehlt → Warning + Skip. `print` durch `logger.warning` ersetzt.

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

- ~~Schritt 0 (CI grün)~~ — ✅
- ~~Schritte 1-4 (Sicherheit + Korrektheit, Block 1)~~ — ✅
- ~~Schritte 5-6 (Tests + Refactor, Block 2)~~ — ✅
- ~~Schritte 7-10 (Aufräumen, Block 3)~~ — ✅

**Alle Hauptblöcke durch.** Was offen bleibt steht im Nice-to-have-Abschnitt — keiner dieser Punkte blockiert irgendwas.
