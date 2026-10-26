# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0", "httpx>=0.27"]
# ///
"""MCP-Server für dr-automate (plan-api-v1.md, Abschnitt 9).

Spricht die REST-API v1 mit einem persönlichen API-Key an. Der Assistent
extrahiert Reisedaten selbst (Regeln + Schema über ``antrag_regeln``), zeigt
sie dem Nutzer und legt die Reise erst nach Bestätigung an.

    DR_AUTOMATE_API_KEY=dra_…  uv run --script mcp/dr_automate_mcp.py

Optional: ``DR_AUTOMATE_URL`` (Standard https://dr-automate.zilinski.eu),
``DR_AUTOMATE_PDF_DIR`` (Standard ~/Downloads).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

BASE = os.environ.get("DR_AUTOMATE_URL", "https://dr-automate.zilinski.eu").rstrip("/") + "/api/v1"
PDF_DIR = Path(os.environ.get("DR_AUTOMATE_PDF_DIR", "~/Downloads")).expanduser()

LESEN = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SCHREIBEN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

server = MCPServer(
    "dr-automate",
    instructions=(
        "Dienstreiseanträge und -abrechnungen nach NRKVO (Niedersachsen). Für einen neuen Antrag: "
        "zuerst antrag_regeln aufrufen, die Reisedaten selbst nach diesen Regeln aus dem Text des "
        "Nutzers extrahieren, Beförderung erfragen, dann reise_anlegen ohne bestaetigt aufrufen, die "
        "Zusammenfassung dem Nutzer zeigen und erst nach seinem Ja mit bestaetigt=true wiederholen. "
        "Name, Adresse und Bankdaten kommen aus dem Profil — nie mitschicken."
    ),
)


class ApiFehler(Exception):
    pass


def _client() -> httpx.Client:
    key = os.environ.get("DR_AUTOMATE_API_KEY", "")
    if not key:
        raise ApiFehler("DR_AUTOMATE_API_KEY ist nicht gesetzt (Key unter /profil#api anlegen).")
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {key}"}, timeout=60)


def _api(methode: str, pfad: str, **kw) -> httpx.Response:
    with _client() as c:
        r = c.request(methode, pfad, **kw)
    if r.status_code >= 400:
        try:
            p = r.json()
            text = p.get("detail") or p.get("title") or r.text
            if p.get("errors"):
                text += " — " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in p["errors"])
        except ValueError:
            text = r.text[:300]
        raise ApiFehler(f"HTTP {r.status_code}: {text}")
    return r


def _json(methode: str, pfad: str, **kw):
    return _api(methode, pfad, **kw).json()


def _zusammenfassung(antrag: dict) -> str:
    rd = antrag.get("reise_details", {})
    bf = antrag.get("befoerderung", {})
    zeilen = [
        f"Zweck: {rd.get('zweck', '')}",
        f"Ziel: {rd.get('zielort', '')}",
        f"Reiseweg: {rd.get('reiseweg', '')}",
        f"Reise: {rd.get('start_datum', '')} {rd.get('start_zeit', '')} bis {rd.get('ende_datum', '')} {rd.get('ende_zeit', '')}",
        f"Dienstgeschäft: {rd.get('dienstgeschaeft_beginn_datum', '')} {rd.get('dienstgeschaeft_beginn_zeit', '')} "
        f"bis {rd.get('dienstgeschaeft_ende_datum', '')} {rd.get('dienstgeschaeft_ende_zeit', '')}",
        f"Hin: {bf.get('hinreise', {}).get('typ', '?')} · Rück: {bf.get('rueckreise', {}).get('typ', '?')}",
    ]
    if bf.get("begruendung"):
        zeilen.append(f"Begründung: {bf['begruendung']}")
    if rd.get("weitere_teilnehmer"):
        zeilen.append("Mitreisende: " + ", ".join(t.get("name", "") for t in rd["weitere_teilnehmer"]))
    if antrag.get("bemerkungen"):
        zeilen.append(f"Bemerkungen: {antrag['bemerkungen']}")
    return "\n".join(zeilen)


@server.tool(annotations=LESEN)
def antrag_regeln() -> dict:
    """Regeln (System-Prompt), Kontext (heutiges Datum, Wohnort) und JSON-Schema für einen
    Dienstreiseantrag. Vor dem Extrahieren aufrufen und die Regeln befolgen."""
    p = _json("GET", "/prompt")
    return {"regeln": p["system_prompt"], "kontext": p["kontext"], "schema": _json("GET", "/schema/antrag")}


@server.tool(annotations=SCHREIBEN)
def reise_anlegen(antrag: dict, bestaetigt: bool = False) -> str:
    """Legt eine Dienstreise mit Antrag an (Antrag v1: reise_details, befoerderung,
    bemerkungen, angaben). Ohne bestaetigt=true wird nur geprüft und eine Zusammenfassung
    zurückgegeben, die dem Nutzer zur Bestätigung zu zeigen ist."""
    if not bestaetigt:
        _api("POST", "/antrag/pdf", json=antrag)  # validiert vollständig, speichert nichts
        return "Bitte dem Nutzer zur Bestätigung zeigen:\n" + _zusammenfassung(antrag)
    r = _json("POST", "/reisen", json=antrag)
    return f"Reise #{r['id']} angelegt (Status {r['status']}). PDF mit pdf_holen({r['id']}, 'antrag')."


@server.tool(annotations=LESEN)
def reisen_auflisten(status: str | None = None) -> str:
    """Eigene Dienstreisen, optional gefiltert (entwurf, genehmigt, abgerechnet, bezahlt)."""
    reisen = _json("GET", "/reisen", params={"status": status} if status else None)["reisen"]
    if not reisen:
        return "Keine Reisen."
    return "\n".join(
        f"#{r['id']} {r['start_datum'] or '—'} {r['titel']} · {r['status']}"
        + (f" · genehmigt {r['genehmigung']['datum']}" if r["genehmigung"]["datum"] else "")
        for r in reisen
    )


@server.tool(annotations=LESEN)
def reise_anzeigen(reise_id: int) -> dict:
    """Eine Reise mit Antrag, Abrechnung, Berechnung und Paperless-Stand."""
    return _json("GET", f"/reisen/{reise_id}")


@server.tool(annotations=SCHREIBEN)
def pdf_holen(reise_id: int, art: str = "antrag") -> str:
    """Lädt das gespeicherte PDF (art: antrag oder abrechnung) in den Download-Ordner."""
    if art not in ("antrag", "abrechnung"):
        raise ApiFehler("art muss 'antrag' oder 'abrechnung' sein")
    r = _api("GET", f"/reisen/{reise_id}/{art}.pdf")
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    ziel = PDF_DIR / f"DR-{art.capitalize()}-{reise_id}.pdf"
    ziel.write_bytes(r.content)
    return f"Gespeichert: {ziel}"


@server.tool(annotations=SCHREIBEN)
def genehmigung_vermerken(reise_id: int, datum: str, aktenzeichen: str = "") -> str:
    """Genehmigung eintragen (datum DD.MM.YYYY). Danach ist der Antrag nicht mehr änderbar."""
    r = _json("POST", f"/reisen/{reise_id}/genehmigung", json={"datum": datum, "aktenzeichen": aktenzeichen})
    return f"Reise #{reise_id}: {r['status']} am {r['genehmigung']['datum']}."


@server.tool(annotations=LESEN)
def abrechnung_berechnen(abrechnung: dict) -> dict:
    """NRKVO-Berechnung für eine Abrechnung v1 (Schema: GET /schema/abrechnung), ohne Speichern."""
    return _json("POST", "/abrechnung/berechnung", json=abrechnung)


@server.tool(annotations=LESEN)
def abrechnung_schema() -> dict:
    """JSON-Schema einer Abrechnung v1."""
    return _json("GET", "/schema/abrechnung")


@server.tool(annotations=SCHREIBEN)
def abrechnung_speichern(reise_id: int, abrechnung: dict, bestaetigt: bool = False) -> str:
    """Speichert die Abrechnung zur Reise und erzeugt das PDF. Ohne bestaetigt=true nur die
    Berechnung zur Bestätigung durch den Nutzer."""
    if not bestaetigt:
        b = _json("POST", "/abrechnung/berechnung", json=abrechnung)
        hinweise = "\n".join(f"- {h}" for h in b.get("hinweise", []))
        return (
            "Bitte dem Nutzer zur Bestätigung zeigen:\n"
            + json.dumps({k: v for k, v in b.items() if k.endswith("_eur")}, ensure_ascii=False, indent=1)
            + (f"\nHinweise:\n{hinweise}" if hinweise else "")
        )
    r = _json("PUT", f"/reisen/{reise_id}/abrechnung", json=abrechnung)
    return f"Abrechnung gespeichert, Auszahlbetrag {r['berechnung']['auszahlbetrag_eur']:.2f} €."


@server.tool(annotations=SCHREIBEN)
def bezahlt_vermerken(reise_id: int, datum: str = "") -> str:
    """Geldeingang vermerken (datum DD.MM.YYYY, leer = heute)."""
    r = _json("POST", f"/reisen/{reise_id}/bezahlt", json={"datum": datum})
    return f"Reise #{reise_id}: bezahlt am {r['bezahlt_datum']}."


@server.tool(annotations=SCHREIBEN)
def an_paperless_senden(reise_id: int, art: str = "antrag") -> str:
    """Schickt das PDF (antrag oder abrechnung) an Paperless; Stand über reise_anzeigen."""
    r = _json("POST", f"/reisen/{reise_id}/paperless", json={"art": art})
    return f"Paperless: {art} {r.get(art, {}).get('status', 'eingereiht')}."


if __name__ == "__main__":
    server.run("stdio")
