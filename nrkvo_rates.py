"""
Single Source of Truth für NRKVO-Sätze (Niedersächsische Reisekostenverordnung).

Die Sätze werden bei jeder Novelle aktualisiert. Server-Berechnung und
Frontend-Anzeige nutzen ausschließlich diese Konstanten.
"""

from typing import Final

# Stand der hier hinterlegten Sätze. Wird im UI/Footer angezeigt.
RATES_STAND: Final = "01.01.2025"

# § 5 NRKVO — Wegstreckenentschädigung
WEGSTRECKE_KLEIN_EUR_PRO_KM: Final = 0.25  # § 5 II
WEGSTRECKE_KLEIN_MAX_EUR: Final = 125.00  # Cap pro Dienstreise
WEGSTRECKE_GROSS_EUR_PRO_KM: Final = 0.38  # § 5 III, triftiger Grund
WEGSTRECKE_FAHRRAD_EUR_PRO_KM: Final = 0.10

# § 6 NRKVO i. V. m. § 9 Abs. 4a EStG — Tagegeld (Verpflegungspauschale)
TAGEGELD_VOLLER_TAG_EUR: Final = 28.00  # 24-h-Tag
TAGEGELD_TEILTAG_EUR: Final = 14.00  # > 8 h oder An-/Abreisetag

# Kürzungen bei unentgeltlicher Verpflegung (Prozent vom vollen Tagegeld 28 €)
KUERZUNG_FRUEHSTUECK_PROZENT: Final = 20  # → 5,60 €
KUERZUNG_MITTAGESSEN_PROZENT: Final = 40  # → 11,20 €
KUERZUNG_ABENDESSEN_PROZENT: Final = 40  # → 11,20 €

# § 8 NRKVO — Übernachtungsgeld
UEBERNACHTUNG_PAUSCHAL_EUR: Final = 20.00  # ohne Beleg
UEBERNACHTUNG_PAUSCHAL_MAX_NAECHTE: Final = 14
UEBERNACHTUNG_BELEG_OHNE_BEGRUENDUNG_MAX_EUR: Final = 100.00  # darüber Begründungspflicht

# § 6 NRKVO — Reduktion bei Daueraufenthalt
DAUERAUFENTHALT_REDUKTION_AB_TAG: Final = 15
DAUERAUFENTHALT_REDUKTION_PROZENT: Final = 50

# 2-km-Regel (§ 6 NRKVO): kein Tagegeld bei Dienstgeschäft im Umkreis
ZWEI_KM_REGEL_KEIN_TAGEGELD: Final = True


def kuerzung_fruehstueck_eur() -> float:
    """5,60 € — 20 % von 28 €."""
    return TAGEGELD_VOLLER_TAG_EUR * KUERZUNG_FRUEHSTUECK_PROZENT / 100


def kuerzung_mittagessen_eur() -> float:
    """11,20 € — 40 % von 28 €."""
    return TAGEGELD_VOLLER_TAG_EUR * KUERZUNG_MITTAGESSEN_PROZENT / 100


def kuerzung_abendessen_eur() -> float:
    """11,20 € — 40 % von 28 €."""
    return TAGEGELD_VOLLER_TAG_EUR * KUERZUNG_ABENDESSEN_PROZENT / 100


def wegstrecke_satz_eur(paragraph: str) -> float:
    """Liefert den Wegstrecken-Satz für § 5 II oder III."""
    return WEGSTRECKE_GROSS_EUR_PRO_KM if paragraph == "III" else WEGSTRECKE_KLEIN_EUR_PRO_KM
