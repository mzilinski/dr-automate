"""Routing-Helper: Geocoding via Nominatim, Distanz via OSRM.

Beide Services sind kostenfrei und ohne Account nutzbar:
- Nominatim (OpenStreetMap): https://nominatim.openstreetmap.org
  Usage-Policy: 1 req/s, descriptive User-Agent Pflicht.
- OSRM Public Demo: https://router.project-osrm.org
  Heavy-Use entmutigt, fuer privates Tool ok.

Pro Address-Paar wird das Ergebnis in einem In-Memory-LRU gecached
(Reduktion der externen Calls; Cache lebt nur waehrend des Worker-
Prozesses, ueberlebt also keinen Container-Restart).
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "dr-automate/1.0 (https://dr-automate.zilinski.eu; admin@zilinski.eu)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"

# Nominatim verlangt max 1 req/s. Wir serialisieren mit einer kleinen Sperre.
_nominatim_lock = threading.Lock()
_last_nominatim_call = 0.0


class RoutingError(Exception):
    """Geocoding oder Routing fehlgeschlagen."""


def _rate_limit_nominatim() -> None:
    global _last_nominatim_call
    with _nominatim_lock:
        delta = time.monotonic() - _last_nominatim_call
        if delta < 1.05:
            time.sleep(1.05 - delta)
        _last_nominatim_call = time.monotonic()


@lru_cache(maxsize=512)
def geocode(address: str) -> tuple[float, float]:
    """Wandelt eine Adresse via Nominatim in (lat, lon)."""
    if not address or not address.strip():
        raise RoutingError("Adresse leer.")
    _rate_limit_nominatim()
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "jsonv2", "limit": 1, "addressdetails": 0},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "de"},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.warning("Nominatim error: %s", e)
        raise RoutingError(f"Geocoding fehlgeschlagen: {e}") from e
    if not data:
        raise RoutingError(f"Adresse nicht gefunden: {address!r}")
    return float(data[0]["lat"]), float(data[0]["lon"])


@lru_cache(maxsize=512)
def route_km(start: str, ende: str) -> dict:
    """Routing-Schaetzung Start → Ende via OSRM-Demo.

    Returns dict: km (gefahrene Strecke), duration_min.
    Hinweis: Fähren-Anteile sind in OSRM-Demo nicht zuverlaessig getaggt.
    Das Frontend zeigt einen statischen Hinweis, dass der User ggf. manuell
    Faehren-Strecke abziehen muss.
    """
    lat1, lon1 = geocode(start)
    lat2, lon2 = geocode(ende)
    try:
        r = requests.get(
            f"{OSRM_URL}/{lon1},{lat1};{lon2},{lat2}",
            params={"overview": "false", "alternatives": "false", "steps": "false"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.warning("OSRM error: %s", e)
        raise RoutingError(f"Routing fehlgeschlagen: {e}") from e
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"Keine Route zwischen {start!r} und {ende!r} gefunden.")
    route = data["routes"][0]
    return {
        "km": round(route["distance"] / 1000.0, 1),
        "duration_min": round(route["duration"] / 60.0, 0),
    }
