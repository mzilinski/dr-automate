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

- ~~Schritt 0 (CI grün)~~ — ✅ erledigt
- ~~Schritte 1-4 (Sicherheit + Korrektheit, Block 1): ~40 Min~~ — ✅ erledigt
- Schritte 5-6 (Tests + Refactor, Block 2): ~75 Min — **noch offen**
- ~~Schritte 7-10 (Aufräumen, Block 3): ~30 Min~~ — ✅ erledigt

Bleibt nur noch Block 2 (Tests für `apply_checkbox_logic` + Refactor in 3 Helper). Das ist Code-Qualität, kein Sicherheits- oder Public-Auftritts-Thema.
