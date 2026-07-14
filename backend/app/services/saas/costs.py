"""CAPEX/OPEX hardware estimator for deployment planning & ROI pitches.

Per-technology bill-of-materials with indicative street prices (USD).
Deliberately conservative list-price ballparks - the numbers a pre-sales
architect needs for a first-pass budget slide, not a quote.
"""
from __future__ import annotations

# technology key -> per-site BOM: (item, qty, unit_capex_usd)
_BOM: dict[str, list[tuple[str, int, float]]] = {
    "default": [
        ("Base radio / access point", 1, 1500.0),
        ("Antenna + mounting kit", 1, 400.0),
        ("Coax / connectors / grounding", 1, 250.0),
        ("Installation labour (day rate)", 1, 900.0),
    ],
    "gsm900": [
        ("2G/4G multi-mode BTS", 1, 9000.0), ("Sector antenna x3", 3, 700.0),
        ("Feeder + jumpers + grounding", 1, 1200.0),
        ("Site install & commissioning", 1, 4500.0),
    ],
    "private_lte_b48": [
        ("CBRS eNodeB/gNodeB", 1, 6500.0), ("Sector antenna x2", 2, 650.0),
        ("Edge core (per-site share)", 1, 2500.0),
        ("SAS subscription setup", 1, 500.0),
        ("Install & integration", 1, 3500.0),
    ],
    "private_nr_n77": [
        ("5G gNodeB (mid-band)", 1, 12000.0), ("mMIMO panel", 1, 4500.0),
        ("Edge UPF/core (per-site share)", 1, 4000.0),
        ("Install & integration", 1, 5000.0),
    ],
    "wifi2400": [
        ("Outdoor Wi-Fi AP", 1, 800.0), ("Sector/omni antenna", 1, 250.0),
        ("PoE switch port + surge", 1, 200.0), ("Install", 1, 600.0),
    ],
    "wifi5800": [
        ("PtMP base radio", 1, 1200.0), ("Sector antenna", 1, 350.0),
        ("PoE + surge protection", 1, 200.0), ("Install", 1, 800.0),
    ],
    "ptp18000": [
        ("Licensed microwave ODU+IDU pair", 1, 7500.0),
        ("Parabolic dish pair (60 cm)", 2, 900.0),
        ("Alignment & commissioning", 1, 2500.0),
        ("Link license (first year)", 1, 1200.0),
    ],
    "lora868": [
        ("LoRaWAN gateway", 1, 450.0), ("Antenna + cabling", 1, 150.0),
        ("Install", 1, 400.0),
    ],
    "tetra400": [
        ("TETRA base station", 1, 15000.0), ("Antenna system", 1, 1800.0),
        ("Dispatcher/console share", 1, 3000.0), ("Install", 1, 5000.0),
    ],
}

# OPEX as a fraction of CAPEX per year (power, maintenance, licenses).
_OPEX_FRACTION = {"default": 0.12, "ptp18000": 0.18, "private_lte_b48": 0.20,
                  "private_nr_n77": 0.20, "tetra400": 0.15}


def estimate(technology: str, sites: int = 1) -> dict:
    """Per-site BOM + fleet totals + 5-year TCO."""
    bom = _BOM.get(technology, _BOM["default"])
    items = [{"item": name, "qty": qty, "unit_usd": unit,
              "line_usd": qty * unit} for name, qty, unit in bom]
    capex_site = sum(i["line_usd"] for i in items)
    opex_frac = _OPEX_FRACTION.get(technology, _OPEX_FRACTION["default"])
    opex_site_year = round(capex_site * opex_frac, 2)
    sites = max(int(sites), 1)
    return {
        "technology": technology,
        "sites": sites,
        "bom_per_site": items,
        "capex_per_site_usd": round(capex_site, 2),
        "opex_per_site_year_usd": opex_site_year,
        "capex_total_usd": round(capex_site * sites, 2),
        "opex_total_year_usd": round(opex_site_year * sites, 2),
        "tco_5y_usd": round(sites * (capex_site + 5 * opex_site_year), 2),
    }
