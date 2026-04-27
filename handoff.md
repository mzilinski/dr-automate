# Handoff

Alle Hauptblöcke aus dem Code-Review vom 2026-04-27 sind durch (CI grün, Sicherheit + Korrektheit, Tests + Refactor, Aufräumen). Offen bleiben nur Nice-to-have-Punkte — keiner blockiert etwas:

- Login-Rate-Limit weiter verschärfen: `3/minute` und `30/hour` für `POST /login` (aktuell `5/minute`, `30/hour`).
- Tests für `_strip_citations` / `_strip_citations_raw` mit echten Beispielen aus Gemini/NotebookLM-Output.
- End-to-End-Test: PDF generieren, mit `pypdf` zurücklesen, Felder gegen Erwartung prüfen.
- `_meta`-Feld in `ReiseantragData` umbenennen (Pydantic v2 ignoriert führende Underscores beim Validieren).
- `CLEAR_DIENSTWAGEN`-Mapping in `generator.py:65` umbenennen oder an `befoerderung.hinreise.typ` koppeln — der aktuelle Name suggeriert bedingtes Löschen, der Code löscht aber immer.
- `templates/index.html` (988 Z. inline CSS+JS) in `static/` auslagern für Caching.
