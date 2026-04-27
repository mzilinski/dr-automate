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
