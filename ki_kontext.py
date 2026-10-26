"""System-Prompt und Kontextblock für die KI-Extraktion — gemeinsam für
Wizard (/extract, Copy-Paste-Pfad) und REST-API (/api/v1/prompt, /extract)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt.md")


def _load_system_prompt() -> str:
    """Lädt den Antrag-System-Prompt.

    Antragsteller-, BahnCard- und Beförderungsdaten stehen bewusst nicht im
    Prompt — das System ergänzt sie aus Profil bzw. Reise-Abfrage. Die frühere
    personalisierte ``system_prompt.local.md`` mit Platzhaltern wie
    ``[DEIN NAME]`` gibt es nicht mehr (``/generate`` weist Platzhalter ab).
    Fehlt die Datei, ist das ein Deploy-Fehler: lieber 500 als ein
    Fehlertext, der als System-Prompt an die KI geht.
    """
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


_VERKEHRSMITTEL_LABEL = {
    "PKW": "PKW (selbst gefahren)",
    "BAHN": "Bahn",
    "BUS": "Bus",
    "DIENSTWAGEN": "Dienstwagen",
    "MITFAHRT": "Mitfahrt",
    "FLUG": "Flug",
}


def _format_reise_kontext(raw: str) -> str:
    """Formatiert die Reise-Abfrage-Antworten als Klartext-Kontext für die KI
    (nur für die Zeitschätzung — die Beförderung selbst gibt die KI nicht aus).

    Erwartet JSON wie ``{"hinreise":{"typ":"PKW","paragraph_5_nrkvo":"II"},
    "rueckreise":{"typ":"BAHN"}}``. Bei leer/kaputt → "".
    """
    if not raw or not raw.strip():
        return ""
    try:
        ra = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""

    def _line(richtung: str, key: str) -> str:
        teil = ra.get(key) or {}
        typ = str(teil.get("typ", "")).upper()
        if not typ:
            return ""
        label = _VERKEHRSMITTEL_LABEL.get(typ, typ)
        if typ == "PKW":
            para = str(teil.get("paragraph_5_nrkvo", "II")).upper()
            label += f", § 5 {para if para in ('II', 'III') else 'II'} NRKVO"
        if typ == "MITFAHRT" and teil.get("mitfahrer_name"):
            label += f" bei {teil['mitfahrer_name']}"
        return f"{richtung}: {label}"

    zeilen = [z for z in (_line("Hinreise", "hinreise"), _line("Rückreise", "rueckreise")) if z]
    return "\n".join(zeilen)


_PLZ_ORT_RE = re.compile(r"\b\d{5}\s+[^,;\n]+")


def _wohnort(adresse: str) -> str:
    """Nur „PLZ Ort" aus einer Anschrift — Straße und Hausnummer gehen nicht
    an den KI-Anbieter (Datensparsamkeit)."""
    adresse = (adresse or "").strip()
    m = _PLZ_ORT_RE.search(adresse)
    if m:
        return m.group(0).strip()[:100]
    return adresse.split(",")[-1].strip()[:100] if "," in adresse else ""


def _ki_kontext(reise_antworten_raw: str, wohnort: str) -> str:
    """Kontextblock am Ende der KI-Eingabe (system_prompt.md, Abschnitt 2):
    heutiges Datum, Wohnort (Start/Ende der Reise) und Verkehrsmittel."""
    from zoneinfo import ZoneInfo

    heute = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y")
    zeilen = [f"Heutiges Datum: {heute}"]
    if wohnort:
        zeilen.append(f"Wohnort (Start und Ende der Reise): {wohnort}")
    befoerderung = _format_reise_kontext(reise_antworten_raw)
    if befoerderung:
        zeilen.append("Vom Nutzer gewählte Beförderung:")
        zeilen.append(befoerderung)
    return "--- Kontext (nur für Datumsbezug und Zeitschätzung, NICHT ausgeben) ---\n" + "\n".join(zeilen)


_CITATION_RE = re.compile(r"\s*\[cite:[^\]]+\]", re.IGNORECASE)
_CITATION_RAW_RE = re.compile(r"\[cite_start\]|\[cite_end\]|\s*\[cite:[^\]]+\]", re.IGNORECASE)


def _strip_citations_raw(text: str) -> str:
    """Entfernt KI-Zitatmarker aus rohem JSON-Text vor dem Parsen."""
    return _CITATION_RAW_RE.sub("", text)


def _strip_citations(obj):
    """Entfernt KI-Zitatmarker wie [cite: 1, 2] rekursiv aus allen String-Werten."""
    if isinstance(obj, dict):
        return {k: _strip_citations(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_citations(i) for i in obj]
    if isinstance(obj, str):
        return _CITATION_RE.sub("", obj).strip()
    return obj
