# Mitarbeit an dr-automate

Vielen Dank fürs Interesse! Dieses Projekt ist ein persönlich-pragmatisches Tool, kein Produkt mit SLA — Beiträge sind willkommen, aber rechne mit kurzen Review-Zyklen und gelegentlich offenen Diskussionen über Scope.

## Setup

```bash
git clone https://github.com/mzilinski/dr-automate.git
cd dr-automate
uv sync
uv run app.py
```

App läuft dann auf `http://localhost:5001`.

## Vor dem Pull-Request

```bash
uvx ruff check .          # Linter, muss exit 0
uvx ruff format --check . # Format-Check, muss exit 0
uv run pytest tests/ -v   # Tests, müssen alle grün
```

CI macht dasselbe — wenn lokal grün, ist die Pipeline auch grün.

## Stil

- Python 3.12+, formatiert via `ruff format`.
- Type-Hints wo sinnvoll, `Optional` als `X | None` (PEP 604).
- Strings sind die Schnittstelle zur PDF-Welt — wo Pydantic-Validierung möglich ist, dort validieren.
- Commits in kurzer, präsenter Sprache (`fix: …`, `feat: …`, `docs: …`, `ci: …`).

## Was Pull-Requests gut machen

- **Eine Sache pro PR.** Lieber drei kleine als ein großer Mischmasch.
- **Tests dazu**, wenn Logik geändert wird — besonders bei `apply_checkbox_logic` und den Pydantic-Modellen.
- **Beschreibung mit Vorher/Nachher**, wenn UI-/Output-Verhalten betroffen ist.
- **Nichts Hardcodiertes Persönliches** (Namen, Adressen, Telefonnummern). Persönliche Defaults gehören in `system_prompt.local.md` (gitignored).

## Was nicht reinkommt

- PRs, die das niedersächsische Reisekostenrecht für andere Bundesländer „verallgemeinern" wollen — der Scope ist bewusst NRKVO. Forks gerne.
- Hartcodierte Auth-Bypässe oder Debug-Endpoints für „Convenience".
- Dependencies, die mit `pyproject.toml` driften (Dockerfile, README).

## Sicherheitslücken

Nicht über öffentliche Issues — bitte den Pfad in [SECURITY.md](SECURITY.md) nutzen.
