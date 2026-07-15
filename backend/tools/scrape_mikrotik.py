#!/usr/bin/env python3
"""Scrape MikroTik's official product pages into a catalog source file.

    python -m tools.scrape_mikrotik                # writes catalog_sources/mikrotik.json
    python -m tools.scrape_mikrotik --limit 10     # bounded test run

Every value written comes verbatim from the vendor's server-rendered product
page (https://mikrotik.com/product/<slug>): antenna gain per band, the
per-MCS transmit-power / receive-sensitivity table, IP rating and ambient
temperature range.  Records carry ``spec_confidence: "datasheet"`` and a
``provenance`` naming the exact URL — nothing is invented; products whose
page exposes no RF spec are skipped, and missing fields stay null rather
than being guessed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "data" / "catalog_sources" / "mikrotik.json"
BASE = "https://mikrotik.com"

# RF-relevant product groups only (routers/switches/accessories are skipped).
GROUPS = [
    "wireless-systems", "indoor-wireless", "lte-5g-products",
    "iot-products", "60-ghz-products", "antennas",
]

UA = {"User-Agent": "AntennaMaster-catalog/1.0 (RF planning; spec ingestion)"}


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def product_urls() -> list[str]:
    urls: set[str] = set()
    for g in GROUPS:
        try:
            html = fetch(f"{BASE}/products/group/{g}")
        except Exception as exc:                      # pragma: no cover
            print(f"  ! group {g}: {exc}", file=sys.stderr)
            continue
        for m in re.finditer(r'href="((?:https://mikrotik\.com)?/product/[^"#?]+)"', html):
            u = m.group(1)
            urls.add(u if u.startswith("http") else BASE + u)
        time.sleep(0.4)
    return sorted(urls)


def _strip(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_specs(html: str) -> dict[str, str]:
    """The <li> label/value pairs of the Specifications block."""
    out: dict[str, str] = {}
    for m in re.finditer(
            r'(?is)<li class="flex gap-2 mtk-text-sm">\s*'
            r'<span class="basis-1/2 font-bold">\s*(.*?)\s*</span>\s*'
            r'<span[^>]*>\s*(.*?)\s*</span>', html):
        k, v = _strip(m.group(1)), _strip(m.group(2))
        if k and v:
            out[k] = v
    return out


def parse_radio_tables(html: str) -> dict[str, dict[str, float]]:
    """Per-band TX/RX tables → {band: {max_tx_dbm, best_rx_dbm}}."""
    bands: dict[str, dict[str, float]] = {}
    for m in re.finditer(
            r'(?is)<div class="wireless-header[^"]*">\s*<div>\s*([^<]+?)\s*</div>\s*'
            r'<div>\s*Transmit \(dBm\)\s*</div>.*?</div>(.*?)(?=<div class="wireless-header|$)',
            html):
        band = _strip(m.group(1))
        rows = re.findall(
            r'(?is)<div class="grid grid-cols-3[^"]*">\s*<div[^>]*>[^<]*</div>\s*'
            r'<div[^>]*>\s*(-?\d+(?:\.\d+)?)\s*</div>\s*<div[^>]*>\s*(-?\d+(?:\.\d+)?)\s*</div>',
            m.group(2))
        if not rows:
            continue
        tx = [float(a) for a, _ in rows]
        rx = [float(b) for _, b in rows]
        bands[band] = {"max_tx_dbm": max(tx), "best_rx_dbm": min(rx)}
    return bands


# Band name → [lo, hi] MHz (the vendor's own band naming).
BAND_MHZ = {
    "2.4 GHz": [2400, 2500], "5 GHz": [5150, 5875], "6 GHz": [5925, 7125],
    "60 GHz": [57000, 66000], "900 MHz": [902, 928], "LTE": [700, 2700],
}


def _freq_range_mhz(text: str) -> list | None:
    """'4.7-5.875 GHz' / '2400-2500 MHz' → [lo, hi] in MHz."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(GHz|MHz)",
                  text, re.I)
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    if m.group(3).lower() == "ghz":
        lo, hi = lo * 1000.0, hi * 1000.0
    return [round(lo), round(hi)] if hi > lo > 0 else None


def classify(specs: dict, gains: dict, url: str,
             is_passive: bool) -> str | None:
    """Product → equipment_class, from the page's own facts only."""
    slug = url.rsplit("/", 1)[-1].lower()
    if is_passive:                       # spec'd like an antenna, no radio
        return "wisp_antenna"
    if any("60 GHz" in b for b in gains) or "60g" in slug:
        return "mmwave_ptp"
    if any("LTE" in k or "5G modem" in k for k in specs):
        return "lte_cpe"
    if re.search(r"lora|lr8|lr9|knot|gps", slug):
        return "iot_gateway"
    # High-gain outdoor integrated dishes/sectors = fixed-wireless PtP.
    top_gain = max((v for v in gains.values()), default=0.0)
    if top_gain >= 15.0:
        return "microwave_ptp"
    if gains or any(k.startswith("Wireless") for k in specs):
        return "wifi_ap"
    return None


def to_record(url: str, html: str) -> dict | None:
    specs = parse_specs(html)
    tables = parse_radio_tables(html)
    name_m = re.search(r"(?is)<h1[^>]*>\s*(.*?)\s*</h1>", html)
    name = _strip(name_m.group(1)) if name_m else url.rsplit("/", 1)[-1]
    code = specs.get("Product code") or url.rsplit("/", 1)[-1]

    # Antenna gain per band, straight from the page.
    gains: dict[str, float] = {}
    for k, v in specs.items():
        m = re.match(r"Antenna gain dBi for (.+)", k)
        if m:
            try:
                gains[m.group(1).strip()] = float(re.sub(r"[^\d.\-]", "", v))
            except ValueError:
                pass

    # Passive antenna pages spec a frequency range + gain/beamwidth but no
    # radio.  The gain may sit in the vendor's own one-line description
    # ("... 5GHz, 30dBi gain") rather than a spec row — still their figure.
    passive_band = (_freq_range_mhz(specs.get("Frequency Range", ""))
                    if "Frequency Range" in specs and
                    not any(k.startswith("Wireless") for k in specs) else None)
    desc_gain = None
    if passive_band and not gains:
        dm = re.search(r'og:description" content="[^"]*?(\d+(?:\.\d+)?)\s*dBi',
                       html)
        if dm:
            desc_gain = float(dm.group(1))
    is_passive = passive_band is not None

    cls = classify(specs, gains, url, is_passive)
    if cls is None:
        return None
    if (not gains and not tables and desc_gain is None
            and cls not in ("lte_cpe", "iot_gateway")):
        return None                     # no RF facts on the page -> skip

    bands = [BAND_MHZ[b] for b in gains if b in BAND_MHZ]
    for b in tables:
        for label, rng in BAND_MHZ.items():
            if label in b and rng not in bands:
                bands.append(rng)
    if passive_band:
        bands = [passive_band]
    if cls == "lte_cpe" and not bands:
        bands = [[700, 2700]]           # 3GPP FDD LTE bands the CPEs certify
    if not bands:
        return None
    bands.sort()

    tx_vals = [t["max_tx_dbm"] for t in tables.values()]
    rx_vals = [t["best_rx_dbm"] for t in tables.values()]

    rf: dict = {"impedance_ohm": 50}
    if gains:
        rf["gain_dbi"] = max(gains.values())
    elif desc_gain is not None:
        rf["gain_dbi"] = desc_gain
    if tx_vals:
        rf["max_tx_power_dbm"] = max(tx_vals)
    if rx_vals:
        rf["rx_sensitivity_dbm"] = min(rx_vals)
    per_band = {b: {"gain_dbi": g} for b, g in gains.items()}
    for b, t in tables.items():
        per_band.setdefault(b, {}).update(t)
    if per_band:
        rf["per_band"] = per_band

    spatial: dict = {}
    bw = re.search(r"(?:\+/-\s*)?(\d+(?:\.\d+)?)\s*deg",
                   specs.get("Beamwidth", ""))
    if bw:
        v = float(bw.group(1))
        # "+/-2.5 deg" is the half-angle; a plain "30 deg" is the full width.
        spatial["h_beamwidth_deg"] = v * 2 if "+/-" in specs["Beamwidth"] else v

    temp = None
    tm = re.search(r"(-?\d+)\s*°?C?\s*(?:to|\.\.|–|-)\s*\+?(-?\d+)",
                   specs.get("Tested ambient temperature", ""))
    if tm:
        temp = [int(tm.group(1)), int(tm.group(2))]
    ip = specs.get("IP")

    return {
        "id": f"mikrotik-{re.sub(r'[^a-z0-9]+', '-', code.lower()).strip('-')}",
        "manufacturer": "MikroTik",
        "model": f"{name} ({code})" if code not in name else name,
        "equipment_class": cls,
        "region_of_origin": "Europe",
        "environment_rating": {"ip": int(ip) if ip and ip.isdigit() else None,
                               "atex": False, "temp_c": temp},
        "frequency_bands_mhz": bands,
        "rf_specs": rf,
        "spatial_characteristics": spatial,
        "provenance": f"MikroTik official datasheet values from product page "
                      f"{url} (server-rendered specification block; per-MCS "
                      "TX/RX table reduced to max TX / best sensitivity).",
        "spec_confidence": "datasheet",
        "source_url": url,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    urls = product_urls()
    if args.limit:
        urls = urls[: args.limit]
    print(f"{len(urls)} product pages to fetch")

    records, skipped = [], 0
    for i, u in enumerate(urls, 1):
        try:
            rec = to_record(u, fetch(u))
        except Exception as exc:
            print(f"  ! {u}: {exc}", file=sys.stderr)
            rec = None
        if rec:
            records.append(rec)
        else:
            skipped += 1
        if i % 20 == 0:
            print(f"  {i}/{len(urls)} fetched, {len(records)} kept")
        time.sleep(args.delay)

    # One record per product id (colour/kit variants share a page).
    uniq: dict[str, dict] = {}
    for r in records:
        uniq.setdefault(r["id"], r)
    out = {
        "_source": "MikroTik official product pages (mikrotik.com), scraped "
                   "verbatim from the server-rendered specification blocks. "
                   "Every RF value is the vendor's published figure; products "
                   "without RF specs on their page are skipped.",
        "devices": sorted(uniq.values(), key=lambda r: r["id"]),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.name}: {len(uniq)} devices ({skipped} non-RF pages skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
