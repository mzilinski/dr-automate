"""OpenAPI-3.1-Beschreibung der REST-API v1, aus den Pydantic-Modellen erzeugt.

Die Routen-Tabelle hier ist die Dokumentationsquelle; ein Test prüft, dass
sie genau den registrierten /api/v1-Routen entspricht.
"""

from __future__ import annotations

from pydantic.json_schema import models_json_schema

import api_models as am

_REF = "#/components/schemas/{model}"

# (Methode, Pfad, Scope, Zusammenfassung, Request-Modell, Antwort)
# Antwort: Modellname, "pdf", "json" (frei), None (204)
ROUTEN = [
    ("get", "/me", None, "Eigener Account, Scopes und Ablauf des Keys", None, "json"),
    ("get", "/schema/antrag", None, "JSON-Schema des Antrags v1", None, "json"),
    ("get", "/schema/abrechnung", None, "JSON-Schema der Abrechnung v1", None, "json"),
    ("get", "/prompt", None, "System-Prompt + Kontextblock für eigene Extraktion", None, "json"),
    ("post", "/antrag/pdf", "berechnen", "Antrag-PDF erzeugen (ohne Speichern)", am.AntragV1, "pdf"),
    ("post", "/abrechnung/berechnung", "berechnen", "NRKVO-Berechnung", am.AbrechnungV1, am.BerechnungV1),
    ("post", "/abrechnung/pdf", "berechnen", "Abrechnungs-PDF erzeugen (ohne Speichern)", am.AbrechnungV1, "pdf"),
    ("post", "/entfernung", "berechnen", "PKW-Entfernung schätzen (OpenStreetMap/OSRM)", am.EntfernungV1, "json"),
    ("post", "/extract", "extract", "KI-Extraktion über DeepSeek (Entwurf)", am.ExtractV1, "json"),
    ("get", "/reisen", "reisen:read", "Eigene Reisen (Filter ?status=)", None, "json"),
    ("post", "/reisen", "reisen:write", "Reise mit Antrag anlegen (Status entwurf)", am.AntragV1, "json"),
    ("get", "/reisen/{reise_id}", "reisen:read", "Reise inkl. Antrag, Abrechnung, Berechnung", None, "json"),
    ("put", "/reisen/{reise_id}/antrag", "reisen:write", "Antrag ersetzen (409 ab genehmigt)", am.AntragV1, "json"),
    ("get", "/reisen/{reise_id}/antrag.pdf", "reisen:read", "Gespeichertes Antrag-PDF", None, "pdf"),
    ("post", "/reisen/{reise_id}/genehmigung", "reisen:write", "Genehmigung vermerken", am.GenehmigungV1, "json"),
    ("put", "/reisen/{reise_id}/abrechnung", "reisen:write", "Abrechnung speichern + PDF", am.AbrechnungV1, "json"),
    ("get", "/reisen/{reise_id}/abrechnung.pdf", "reisen:read", "Gespeichertes Abrechnungs-PDF", None, "pdf"),
    (
        "post",
        "/reisen/{reise_id}/bezahlt",
        "reisen:write",
        "Geldeingang vermerken (409 ohne Abrechnung)",
        am.BezahltV1,
        "json",
    ),
    ("delete", "/reisen/{reise_id}", "reisen:write", "Reise und PDFs löschen", None, None),
    ("get", "/openapi.json", None, "Diese Beschreibung (ohne Key)", None, "json"),
]

_FEHLER = {
    "400": "Ungültiges JSON",
    "401": "Kein oder ungültiger API-Key",
    "403": "Scope fehlt",
    "404": "Nicht gefunden (auch fremde Reisen)",
    "409": "Statuskonflikt",
    "415": "Content-Type muss application/json sein",
    "422": "Validierung oder fachlicher Fehler",
    "429": "Rate-Limit",
}


def spec(server_url: str = "/api/v1") -> dict:
    modelle = sorted(
        {m for *_, req, res in ROUTEN for m in (req, res) if isinstance(m, type)},
        key=lambda m: m.__name__,
    )
    _, defs = models_json_schema([(m, "validation") for m in modelle], ref_template=_REF)
    schemas = defs.get("$defs", {})
    problem = {"application/problem+json": {"schema": {"$ref": _REF.format(model="Problem")}}}
    schemas["Problem"] = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "integer"},
            "detail": {"type": "string"},
            "errors": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["type", "title", "status"],
    }

    paths: dict = {}
    for methode, pfad, scope, summary, req, res in ROUTEN:
        op: dict = {"summary": summary, "responses": {}}
        if pfad == "/openapi.json":
            op["security"] = []
        if scope:
            op["x-scope"] = scope
            op["description"] = f"Benötigt den Scope `{scope}`."
        if "{reise_id}" in pfad:
            op["parameters"] = [{"name": "reise_id", "in": "path", "required": True, "schema": {"type": "integer"}}]
        if req is not None:
            op["requestBody"] = {
                "required": req is not am.BezahltV1,
                "content": {"application/json": {"schema": {"$ref": _REF.format(model=req.__name__)}}},
            }
        if res is None:
            op["responses"]["204"] = {"description": "gelöscht"}
        elif res == "pdf":
            op["responses"]["200"] = {"description": "PDF", "content": {"application/pdf": {}}}
        elif isinstance(res, type):
            op["responses"]["200"] = {
                "description": "OK",
                "content": {"application/json": {"schema": {"$ref": _REF.format(model=res.__name__)}}},
            }
        else:
            code = "201" if (methode, pfad) == ("post", "/reisen") else "200"
            op["responses"][code] = {"description": "OK", "content": {"application/json": {}}}
        for code, text in _FEHLER.items():
            op["responses"][code] = {"description": text, "content": problem}
        paths.setdefault(pfad, {})[methode] = op

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "dr-automate API",
            "version": "1.0.0",
            "description": "Dienstreiseanträge und -abrechnungen nach NRKVO. Doku: /docs/api",
        },
        "servers": [{"url": server_url}],
        "security": [{"bearer": []}],
        "components": {
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "dra_<prefix>_<secret>"}
            },
            "schemas": schemas,
        },
        "paths": paths,
    }
